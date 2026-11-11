"""AI service: the GenAI-DBT pipeline for every AI function (Plan §5.4; Phase 4 tasks 2-7).

    input -> input filter (schema, length cap, prompt-injection heuristic)
          -> retrieval (skill-scoped) -> prompt build (registry) -> provider
          -> OutputValidator (repair -> remap -> validate) -> rule checks
          -> [one regeneration on failure] -> result | authored fallback
          -> AIInteraction log (+ cache for caregiver items)

The model never controls state or access: callers get a validated `AIResult` and decide what
to do with it. Risk screening of participant input happens before this service is called
(SafetyService.screen_text, Plan §5.7); `assess_risk` is the LLM channel of that screening.

Grounding (D6, D51): skill-scoped calls retrieve only that skill's chunks, so any hit counts as
sufficient; unscoped calls use the knowledge base's similarity threshold (D46). With no
sufficient material the model must answer as labelled general knowledge.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import templating
from app.ai.provider import GuardedProvider, LLMRequest, LLMResult, ProviderError
from app.ai.rules import RuleChecker, SourceChunk, Violation
from app.ai.schemas import FUNCTIONS, FunctionSpec, In, SelectSkillOut, TeachingMessageOut
from app.ai.validator import OutputInvalidError, validate
from app.content.loader import ContentBundle
from app.content.models import PromptTemplate, SkillTaxonomy
from app.core.logging import get_logger
from app.models.ai import AICacheItem, AIInteraction, AIOutcome, CacheReview, ContentSource
from app.settings import Settings

log = get_logger("ai")

LANGUAGE_NAMES = {"zh-CN": "简体中文", "en": "English"}
MAX_ATTEMPTS = 2  # first call + one regeneration (Plan §5.4: retry <= 1)

# Heuristic only: flagged inputs are still wrapped as data and logged, never blocked by this.
INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)"
    r"|disregard (the|your) (rules|instructions|system prompt)"
    r"|(system|developer) prompt|you are now|act as (an?|my) |jailbreak|\bDAN\b"
    r"|<!--|META:|<<<DATA|DATA>>>"
    r"|忽略(之前|以上|前面|所有)的?(指令|规则|说明|提示)|系统提示|你现在是|扮演(一个|我的)|越狱",
    re.IGNORECASE,
)

MOOD_TEXT = {
    "zh-CN": {1: "很差", 2: "不太好", 3: "一般", 4: "不错", 5: "很好"},
    "en": {1: "very low", 2: "not great", 3: "okay", 4: "good", 5: "very good"},
}


class AIInputError(ValueError):
    """The caller passed input that does not fit the function's input schema or limits."""


@dataclass(frozen=True)
class Retrieved:
    chunks: list[SourceChunk]
    sufficient: bool
    kb_version: int | None


Retriever = Callable[[Session, str, str, str, list[str], uuid.UUID | None], Retrieved]
"""(db, function, query, language, skill_ids, actor_id) -> Retrieved"""


@dataclass(frozen=True)
class SourceRef:
    chunk_id: str
    handout_id: str
    module: str


@dataclass(frozen=True)
class AIResult:
    function: str
    role: str
    language: str
    output: dict[str, Any] | None  # validated output (AI) or authored fallback output
    notice: str | None  # authored "not available" text when the AI output is not used
    source: ContentSource
    outcome: AIOutcome
    grounding: str
    sources: list[SourceRef] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    interaction_id: str | None = None
    cache_hit: bool = False

    @property
    def is_fallback(self) -> bool:
        return self.outcome is AIOutcome.fallback


@dataclass(frozen=True)
class StreamEvent:
    kind: str  # "delta" (checked text to show) | "replace" (discard deltas) | "final"
    text: str = ""
    result: AIResult | None = None


@dataclass
class _Attempt:
    data: dict[str, Any] | None = None
    repaired: bool = False
    failures: list[str] = field(default_factory=list)
    llm: LLMResult | None = None


class AIService:
    def __init__(
        self,
        content: ContentBundle,
        settings: Settings,
        provider: GuardedProvider,
        *,
        retriever: Retriever | None = None,
        fingerprint: frozenset[str] | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        rules = content.output_rules
        if rules is None:
            raise RuntimeError("content/safety/output_rules.yaml is required")
        self.content = content
        self.settings = settings
        self.provider = provider
        self.retriever = retriever
        self.checker = RuleChecker(rules, content.forbidden_phrases, fingerprint)
        self.session_factory = session_factory
        tax = content.taxonomy
        self.taxonomy: SkillTaxonomy | None = tax
        self.skill_module: dict[str, str] = (
            {s.id: m.id for m in tax.modules for s in m.skills} if tax else {}
        )

    # --- names -----------------------------------------------------------------------------

    def skill_name(self, skill_id: str | None, language: str) -> str:
        if not skill_id or self.taxonomy is None:
            return ""
        for m in self.taxonomy.modules:
            for s in m.skills:
                if s.id == skill_id and s.name is not None:
                    return s.name.zh_CN if language == "zh-CN" else s.name.en
        return skill_id

    def module_name(self, module_id: str | None, language: str) -> str:
        if not module_id or self.taxonomy is None:
            return ""
        for m in self.taxonomy.modules:
            if m.id == module_id and m.name is not None:
                return m.name.zh_CN if language == "zh-CN" else m.name.en
        return module_id

    # --- public API ------------------------------------------------------------------------

    def run(
        self,
        db: Session | None,
        function: str,
        inputs: dict[str, Any] | In,
        *,
        role: str,
        language: str,
        caller: str,
        actor_id: uuid.UUID | None = None,
        use_cache: bool = True,
        hints: dict[str, Any] | None = None,
    ) -> AIResult:
        """Run one AI function. Never raises for model/provider problems: returns a fallback."""
        if db is None:
            if self.session_factory is None:
                raise RuntimeError("no database session")
            with self.session_factory() as own:
                result = self.run(
                    own,
                    function,
                    inputs,
                    role=role,
                    language=language,
                    caller=caller,
                    actor_id=actor_id,
                    use_cache=use_cache,
                    hints=hints,
                )
                own.commit()
                return result
        spec, data = self._check_input(function, inputs, role, language)
        if spec.streamed:
            final: AIResult | None = None
            for ev in self.stream(
                db, function, data, role=role, language=language, caller=caller, actor_id=actor_id
            ):
                if ev.kind == "final":
                    final = ev.result
            assert final is not None
            return final
        return self._run(db, spec, data, role, language, caller, actor_id, use_cache, hints or {})

    def stream(
        self,
        db: Session,
        function: str,
        inputs: dict[str, Any] | In,
        *,
        role: str,
        language: str,
        caller: str,
        actor_id: uuid.UUID | None = None,
        hints: dict[str, Any] | None = None,
    ) -> Iterator[StreamEvent]:
        """Streamed `teaching_turn`: release text sentence by sentence after the rule checks.

        Unchecked model text never reaches the participant: a sentence is yielded only after it
        passes the pattern, overlap and medical-caution rules (with everything released before
        it). On any failure the stream ends with "replace" and an authored fallback.
        """
        spec, data = self._check_input(function, inputs, role, language)
        started = time.perf_counter()
        ctx = self._context(db, spec, data, language, actor_id)
        tpl, sha = self._prompt(spec.name, role, language)
        messages = self._messages(tpl, spec, ctx, language)
        req = self._request(spec, messages, ctx, language, streamed=True, hints=hints)
        released: list[str] = []
        buffer = ""
        meta_raw: str | None = None
        failures: list[str] = []
        pieces = self.provider.stream(req)
        try:
            for piece in pieces:
                if meta_raw is not None:
                    meta_raw += piece
                    continue
                buffer += piece
                if "<!--" in buffer:
                    buffer, _, meta_raw = buffer.partition("<!--")
                sentences, buffer = _split_sentences(buffer)
                for sent in sentences:
                    bad = self._sentence_violations(released, sent, ctx["_sources"])
                    if bad:
                        failures += [str(v) for v in bad]
                        raise _StreamAbortError
                    released.append(sent)
                    yield StreamEvent("delta", sent)
        except _StreamAbortError:
            pass
        except ProviderError as exc:
            failures.append(f"provider:{exc.code}")
        finally:
            close = getattr(pieces, "close", None)
            if close is not None:
                close()
        if not failures and buffer.strip():
            bad = self._sentence_violations(released, buffer, ctx["_sources"])
            if bad:
                failures += [str(v) for v in bad]
            else:
                released.append(buffer)
                yield StreamEvent("delta", buffer)
        attempt = _Attempt(failures=failures)
        if not failures:
            attempt = self._finish_stream(spec, "".join(released), meta_raw, ctx, language)
        result = self._conclude(
            db,
            spec,
            data,
            role,
            language,
            caller,
            actor_id,
            tpl,
            sha,
            ctx,
            attempt,
            attempts=1,
            started=started,
            use_cache=False,
        )
        if result.is_fallback and released:
            yield StreamEvent("replace", result=result)
        yield StreamEvent("final", result=result)

    # --- pipeline pieces ---------------------------------------------------------------------

    def _check_input(
        self, function: str, inputs: dict[str, Any] | In, role: str, language: str
    ) -> tuple[FunctionSpec, In]:
        spec = FUNCTIONS.get(function)
        if spec is None:
            raise AIInputError(f"unknown AI function {function!r}")
        if role not in spec.roles:
            raise AIInputError(f"{function} is not available for role {role}")
        if language not in LANGUAGE_NAMES:
            raise AIInputError(f"unsupported language {language!r}")
        try:
            data = (
                inputs
                if isinstance(inputs, spec.input)
                else spec.input.model_validate(
                    inputs.model_dump() if isinstance(inputs, BaseModel) else inputs
                )
            )
        except ValidationError as exc:
            raise AIInputError(
                f"invalid input for {function}: {exc.error_count()} error(s)"
            ) from exc
        cap = self.settings.lesson_message_max_chars
        for name in ("message", "checkin_answer", "mood_note", "answer"):
            value = getattr(data, name, None)
            if isinstance(value, str) and len(value) > cap:
                raise AIInputError(f"{name} is longer than {cap} characters")
        skill = getattr(data, "skill_id", None)
        if skill and self.skill_module and skill not in self.skill_module:
            raise AIInputError(f"unknown skill {skill}")
        return spec, data

    def _prompt(self, function: str, role: str, language: str) -> tuple[PromptTemplate, str]:
        found = self.content.prompt(function, role, language)
        if found is None:
            raise RuntimeError(f"no prompt for {function}/{role}/{language}")
        return found

    def _retrieve(
        self, db: Session, spec: FunctionSpec, data: In, language: str, actor_id: uuid.UUID | None
    ) -> Retrieved:
        if not spec.retrieval or self.retriever is None:
            return Retrieved([], False, None)
        skill = getattr(data, "skill_id", None)
        parts = [self.skill_name(skill, "zh-CN"), self.skill_name(skill, "en")] if skill else []
        for name in ("message", "checkin_answer", "answer"):
            value = getattr(data, name, None)
            if isinstance(value, str) and value:
                parts.append(value)
        item = getattr(data, "item", None)
        if item is not None:
            parts.append(item.prompt)
        query = " ".join(p for p in parts if p)[:400] or "DBT"
        return self.retriever(db, spec.name, query, language, [skill] if skill else [], actor_id)

    def _context(
        self, db: Session, spec: FunctionSpec, data: In, language: str, actor_id: uuid.UUID | None
    ) -> dict[str, Any]:
        """Template values (all strings) plus private `_` entries used by the service."""
        r = self._retrieve(db, spec, data, language, actor_id)
        skill = getattr(data, "skill_id", None)
        module = self.skill_module.get(skill or "", "")
        zh = language == "zh-CN"
        v: dict[str, Any] = {
            "language_name": LANGUAGE_NAMES[language],
            "skill_name": self.skill_name(skill, language),
            "module_name": self.module_name(module, language),
            "sources": _format_sources(r.chunks, language, self),
            "_sources": r.chunks,
            "_sufficient": r.sufficient,
            "_kb_version": r.kb_version,
            "_skill": skill,
            "_module": module,
            "_injection": False,
        }
        texts: list[str] = []
        for name, value in data:
            if name == "profile":
                v["profile"] = _format_profile(value, language)
            elif name == "mood":
                v["mood"] = (
                    "—"
                    if value is None
                    else f"{value}/5（{MOOD_TEXT[language][value]}）"
                    if zh
                    else f"{value}/5 ({MOOD_TEXT[language][value]})"
                )
            elif name in ("mood_note", "checkin_answer", "message", "answer"):
                texts.append(value or "")
                v[name] = templating.as_data(value) if value else ("（无）" if zh else "(none)")
            elif name in ("history_skills", "recent_skills", "weak_skills"):
                v[name] = (
                    "、".join(self.skill_name(s, language) + f"（{s}）" for s in value)
                    if zh
                    else ", ".join(f"{self.skill_name(s, language)} ({s})" for s in value)
                ) or ("无" if zh else "none")
            elif name in ("history",):
                for t in value:
                    if t.role == "student":
                        texts.append(t.content)
                v["history"] = _format_history(value, language)
            elif name == "plan_steps":
                cur = getattr(data, "current_step", 1)
                v["plan"] = _format_plan(value, cur, language)
                v["first_step"] = (
                    _format_plan(value[:1], 1, language)
                    if value
                    else ("（无）" if zh else "(none)")
                )
            elif name == "item":
                opts = "".join(f"\n  {chr(65 + i)}. {o}" for i, o in enumerate(value.options))
                v["item"] = f"{value.scenario}\n{value.prompt}{opts}"
            elif name in ("key_points", "previous_questions", "recent", "keyword_terms"):
                if name == "recent":
                    texts.extend(value)
                    v[name] = "\n".join(templating.as_data(x) for x in value) or (
                        "（无）" if zh else "(none)"
                    )
                else:
                    v[name] = "\n".join(f"- {x}" for x in value) or ("（无）" if zh else "(none)")
            elif name == "previous_scores":
                v[name] = ", ".join(f"{x}/5" for x in value) or ("无" if zh else "none")
            elif name == "assess_risk":
                v["risk_instruction"] = _risk_instruction(bool(value), language)
                v["_assess_risk"] = bool(value)
            elif name in ("authored_feedback", "step_prompt", "hint_scope", "selection_reason"):
                v[name] = value or ("（无）" if zh else "(none)")
            elif name == "message_text":
                pass
            else:
                v[name] = "" if value is None else str(value)
        if spec.name == "assess_risk":
            v["message"] = templating.as_data(str(getattr(data, "message", "")))
        if spec.name == "select_skill":
            v["skill_catalogue"] = self._catalogue(language)
        v.setdefault("risk_instruction", _risk_instruction(False, language))
        v.setdefault("last_message_type", "")
        v["_injection"] = any(INJECTION.search(t) for t in texts if t)
        return v

    def _catalogue(self, language: str) -> str:
        if self.taxonomy is None:
            return ""
        lines = []
        for m in self.taxonomy.modules:
            skills = "; ".join(f"{s.id} = {self.skill_name(s.id, language)}" for s in m.skills)
            lines.append(f"[{m.id}] {self.module_name(m.id, language)}: {skills}")
        return "\n".join(lines)

    def _messages(
        self, tpl: PromptTemplate, spec: FunctionSpec, ctx: dict[str, Any], language: str
    ) -> list[dict[str, str]]:
        values = {k: str(v) for k, v in ctx.items() if not k.startswith("_")}
        parts = [templating.render(tpl.system, values)]
        for block_id in tpl.blocks:
            block = self.content.prompt_block(block_id, language)
            if block is not None:
                parts.append(block.text)
        parts.append(templating.output_format(spec.output, language, streamed=spec.streamed))
        return [
            {"role": "system", "content": "\n\n".join(parts)},
            {"role": "user", "content": templating.render(tpl.user, values)},
        ]

    def _request(
        self,
        spec: FunctionSpec,
        messages: list[dict[str, str]],
        ctx: dict[str, Any],
        language: str,
        *,
        streamed: bool = False,
        hints: dict[str, Any] | None = None,
    ) -> LLMRequest:
        allowed = [[sid, mid] for sid, mid in self.skill_module.items()]
        return LLMRequest(
            function=spec.name,
            messages=messages,
            json_mode=not streamed,
            max_tokens=spec.max_tokens
            if spec.max_tokens != 2048
            else self.settings.llm_max_output_tokens,
            timeout=float(self.settings.llm_timeout_seconds),
            temperature=self.settings.llm_temperature,
            hints={
                "language": language,
                "skill_name": ctx.get("skill_name"),
                "module_name": ctx.get("module_name"),
                "labels": [c.label for c in ctx["_sources"]],
                "sufficient": ctx["_sufficient"],
                "retrieval": spec.retrieval,
                "allowed_skills": allowed,
                "streamed": streamed,
                **(hints or {}),
            },
        )

    def _post_checks(
        self, spec: FunctionSpec, data: dict[str, Any], ctx: dict[str, Any], language: str
    ) -> list[Violation]:
        out: list[Violation] = []
        if spec.output is SelectSkillOut and self.skill_module:
            out += RuleChecker.taxonomy(
                str(data["selected_skill"]),
                [str(a) for a in data["alternative_skills"]],
                str(data["selected_module"]),
                self.skill_module,
            )
        out += self.checker.check(
            data,
            language=language,
            sources=ctx["_sources"],
            sufficient=ctx["_sufficient"],
            user_facing=spec.user_facing,
        )
        return out

    def _attempt(
        self, spec: FunctionSpec, req: LLMRequest, ctx: dict[str, Any], language: str
    ) -> _Attempt:
        try:
            llm = self.provider.complete(req)
        except ProviderError as exc:
            return _Attempt(failures=[f"provider:{exc.code}"])
        try:
            v = validate(llm.text, spec.output)
        except OutputInvalidError as exc:
            # Field paths and error types only (never model text), to diagnose fallbacks (O24).
            log.warning("ai_output_invalid", function=spec.name, code=exc.code, detail=exc.summary)
            return _Attempt(failures=[exc.code], llm=llm)
        data = v.model.model_dump()
        relabelled = _relabel_unscoped(data, ctx)
        bad = self._post_checks(spec, data, ctx, language)
        if bad:
            return _Attempt(failures=[str(x) for x in bad], llm=llm)
        return _Attempt(data=data, repaired=v.repaired or relabelled, llm=llm)

    def _run(
        self,
        db: Session,
        spec: FunctionSpec,
        data: In,
        role: str,
        language: str,
        caller: str,
        actor_id: uuid.UUID | None,
        use_cache: bool,
        hints: dict[str, Any],
    ) -> AIResult:
        started = time.perf_counter()
        ctx = self._context(db, spec, data, language, actor_id)
        tpl, sha = self._prompt(spec.name, role, language)
        variant = str(getattr(data, "variant", "standard"))
        if spec.cacheable and use_cache:
            hit = self._cache_get(db, spec, ctx, role, language, variant, sha)
            if hit is not None:
                return self._log_cache_hit(
                    db, spec, data, role, language, caller, actor_id, tpl, sha, ctx, hit, started
                )
        messages = self._messages(tpl, spec, ctx, language)
        user_text = messages[1]["content"]
        failures: list[str] = []
        attempt = _Attempt()
        attempts = 0
        tokens_in = tokens_out = 0
        for n in range(MAX_ATTEMPTS):
            attempts = n + 1
            req = self._request(spec, messages, ctx, language, hints=hints)
            attempt = self._attempt(spec, req, ctx, language)
            if attempt.llm is not None:
                tokens_in += attempt.llm.input_tokens or 0
                tokens_out += attempt.llm.output_tokens or 0
            if attempt.data is not None:
                break
            failures += attempt.failures
            if any(f.startswith("provider:") for f in attempt.failures):
                break  # the provider already retried; go straight to the fallback
            # Regenerate once with the failure codes (never the failed text) appended.
            note = _retry_note(attempt.failures, language)
            messages = [messages[0], {"role": "user", "content": user_text + "\n\n" + note}]
        attempt.failures = failures
        result = self._conclude(
            db,
            spec,
            data,
            role,
            language,
            caller,
            actor_id,
            tpl,
            sha,
            ctx,
            attempt,
            attempts=attempts,
            started=started,
            use_cache=use_cache,
            tokens=(tokens_in or None, tokens_out or None),
            variant=variant,
        )
        return result

    def _finish_stream(
        self,
        spec: FunctionSpec,
        content: str,
        meta_raw: str | None,
        ctx: dict[str, Any],
        language: str,
    ) -> _Attempt:
        meta: dict[str, Any] = {}
        if meta_raw is not None:
            body = meta_raw.split("-->", 1)[0].strip()
            body = body[5:] if body.startswith("META:") else body
            try:
                meta = json.loads(body) if body.startswith("{") else {}
            except json.JSONDecodeError:
                meta = {}
        defaulted = False
        if not meta and content.strip() and not ctx.get("_assess_risk"):
            # The model sometimes drops the trailing META line. As in DBT_Revised, keep the reply
            # with neutral defaults: no citations, so it is labelled general knowledge; it still
            # goes through every output rule below. Not when this turn had to judge risk inline:
            # a missing verdict is never assumed safe.
            meta = {"message_type": "explanation", "grounding": "general", "confidence": "low"}
            defaulted = True
        try:
            v = validate({**meta, "content": content.strip()}, spec.output)
        except OutputInvalidError as exc:
            log.warning(
                "ai_output_invalid",
                function=spec.name,
                code=exc.code if meta else "missing_metadata",
                detail=exc.summary,
                content_chars=len(content.strip()),
            )
            return _Attempt(failures=[exc.code if meta else "missing_metadata"])
        data = v.model.model_dump()
        bad = self._post_checks(spec, data, ctx, language)
        if bad:
            return _Attempt(failures=[str(x) for x in bad])
        if defaulted:
            log.info("ai_metadata_defaulted", function=spec.name)
        return _Attempt(data=data, repaired=v.repaired or defaulted)

    def _sentence_violations(
        self, released: list[str], sentence: str, sources: Sequence[SourceChunk]
    ) -> list[Violation]:
        texts = [*released, sentence]
        return self.checker.patterns([sentence]) + self.checker.overlap(["".join(texts)], sources)

    # --- results, fallbacks, logging ---------------------------------------------------------

    def _conclude(
        self,
        db: Session,
        spec: FunctionSpec,
        data: In,
        role: str,
        language: str,
        caller: str,
        actor_id: uuid.UUID | None,
        tpl: PromptTemplate,
        sha: str,
        ctx: dict[str, Any],
        attempt: _Attempt,
        *,
        attempts: int,
        started: float,
        use_cache: bool,
        tokens: tuple[int | None, int | None] = (None, None),
        variant: str = "standard",
    ) -> AIResult:
        sources: list[SourceChunk] = ctx["_sources"]
        by_label = {s.label: s for s in sources}
        failures = list(attempt.failures)
        out: dict[str, Any] | None
        if attempt.data is not None:
            out = dict(attempt.data)
            cited = [by_label[c] for c in out.get("source_chunk_ids", []) if c in by_label]
            out["source_chunk_ids"] = [c.chunk_id for c in cited]
            out["language"] = language
            grounding = str(out.get("grounding", "none"))
            source = (
                ContentSource.none
                if not spec.user_facing
                else ContentSource.ai_manual
                if grounding == "manual"
                else ContentSource.ai_general
            )
            outcome = (
                AIOutcome.retried
                if attempts > 1
                else AIOutcome.repaired
                if attempt.repaired
                else AIOutcome.ok
            )
            if spec.output is TeachingMessageOut and out.get("should_stop"):
                outcome = AIOutcome.stopped
            notice = None
        else:
            cited = []
            out, notice = self._fallback(spec, data, language)
            grounding = "none"
            source = ContentSource.authored if spec.user_facing else ContentSource.none
            outcome = AIOutcome.fallback
        llm_model = self.provider.model
        row = AIInteraction(
            function=spec.name,
            role=role,
            language=language,
            caller=caller[:40],
            actor_id=actor_id,
            skill_id=ctx["_skill"],
            prompt_id=f"{spec.name}/{role}/{language}",
            prompt_version=tpl.version,
            prompt_sha256=sha,
            provider=self.provider.name,
            model=llm_model,
            kb_version=ctx["_kb_version"],
            input_sha256=_input_hash(data),
            injection_suspected=bool(ctx["_injection"]),
            retrieved_chunk_ids=[s.chunk_id for s in sources],
            cited_chunk_ids=[c.chunk_id for c in cited],
            retrieval_sufficient=ctx["_sufficient"] if spec.retrieval else None,
            grounding=grounding,
            source=source,
            outcome=outcome,
            attempts=attempts,
            failures=failures[:20],
            cache_hit=False,
            output_text=json.dumps(out, ensure_ascii=False) if out is not None else None,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=tokens[0],
            output_tokens=tokens[1],
        )
        db.add(row)
        db.flush()
        if outcome is AIOutcome.fallback:
            log.warning("ai_fallback", function=spec.name, failures=failures[:5])
        if (
            spec.cacheable
            and use_cache
            and out is not None
            and outcome is not AIOutcome.fallback
            and ctx["_skill"]
        ):
            db.add(
                AICacheItem(
                    function=spec.name,
                    skill_id=ctx["_skill"],
                    role=role,
                    language=language,
                    variant=variant,
                    prompt_version=tpl.version,
                    prompt_sha256=sha,
                    kb_version=ctx["_kb_version"] or 0,
                    output=out,
                    source=source,
                    interaction_id=row.id,
                )
            )
            try:
                with db.begin_nested():
                    db.flush()
            except IntegrityError:  # a concurrent request cached the same key first
                log.info("ai_cache_race", function=spec.name)
        return AIResult(
            function=spec.name,
            role=role,
            language=language,
            output=out,
            notice=notice,
            source=source,
            outcome=outcome,
            grounding=grounding,
            sources=[SourceRef(c.chunk_id, c.handout_id, c.module) for c in cited],
            failures=failures,
            interaction_id=str(row.id),
        )

    def _fallback(
        self, spec: FunctionSpec, data: In, language: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        if spec.name == "assess_risk":
            return None, None  # keyword-only screening decides (Plan §5.7)
        skill = getattr(data, "skill_id", None)
        doc = self.content.fallback(spec.name, skill, language)
        if doc is None:
            return None, None
        if spec.name == "select_skill":
            return self._fallback_skill(data, language, doc.notice), doc.notice
        if spec.name == "personalize_feedback":  # the authored feedback itself, unchanged
            feedback = str(getattr(data, "authored_feedback", ""))
            return {
                "feedback": feedback,
                "source_chunk_ids": [],
                "grounding": "none",
                "confidence": "high",
                "language": language,
            }, doc.notice
        if doc.output is None:
            return None, doc.notice
        module = self.skill_module.get(skill or "", "")
        model = templating.fill_fallback(
            doc.output,
            spec.output,
            self.skill_name(skill, language)
            or ("这个技能" if language == "zh-CN" else "this skill"),
            self.module_name(module, language),
        )
        out = model.model_dump()
        out["language"] = language
        out["source_chunk_ids"] = []
        out["grounding"] = "none"
        return out, doc.notice

    def _fallback_skill(self, data: In, language: str, reason: str) -> dict[str, Any] | None:
        """Deterministic skill choice when the AI is unavailable: first skill not done lately."""
        if self.taxonomy is None:
            return None
        recent = set(getattr(data, "recent_skills", []) or [])
        order = [s.id for m in self.taxonomy.modules if m.id != "orientation" for s in m.skills]
        fresh = [s for s in order if s not in recent] or order
        pick = fresh[0]
        alts = [s for s in fresh[1:3]] or [s for s in order if s != pick][:2]
        return {
            "selected_module": self.skill_module[pick],
            "selected_skill": pick,
            "reason": reason,
            "skill_difficulty": "beginner",
            "alternative_skills": alts,
            "is_repeat": False,
            "repeat_justification": "",
            "source_chunk_ids": [],
            "grounding": "none",
            "confidence": "low",
            "language": language,
        }

    # --- cache (Plan §5.4 "Caching") ----------------------------------------------------------

    def _cache_get(
        self,
        db: Session,
        spec: FunctionSpec,
        ctx: dict[str, Any],
        role: str,
        language: str,
        variant: str,
        sha: str,
    ) -> AICacheItem | None:
        if not ctx["_skill"]:
            return None
        return db.scalar(
            select(AICacheItem).where(
                AICacheItem.function == spec.name,
                AICacheItem.skill_id == ctx["_skill"],
                AICacheItem.role == role,
                AICacheItem.language == language,
                AICacheItem.variant == variant,
                AICacheItem.prompt_sha256 == sha,
                AICacheItem.kb_version == (ctx["_kb_version"] or 0),
                AICacheItem.review != CacheReview.needs_change,
            )
        )

    def _log_cache_hit(
        self,
        db: Session,
        spec: FunctionSpec,
        data: In,
        role: str,
        language: str,
        caller: str,
        actor_id: uuid.UUID | None,
        tpl: PromptTemplate,
        sha: str,
        ctx: dict[str, Any],
        item: AICacheItem,
        started: float,
    ) -> AIResult:
        db.execute(
            update(AICacheItem).where(AICacheItem.id == item.id).values(hits=AICacheItem.hits + 1)
        )
        out = dict(item.output)
        by_id = {s.chunk_id: s for s in ctx["_sources"]}
        cited = [by_id[c] for c in out.get("source_chunk_ids", []) if c in by_id]
        row = AIInteraction(
            function=spec.name,
            role=role,
            language=language,
            caller=caller[:40],
            actor_id=actor_id,
            skill_id=ctx["_skill"],
            prompt_id=f"{spec.name}/{role}/{language}",
            prompt_version=tpl.version,
            prompt_sha256=sha,
            provider="cache",
            model=self.provider.model,
            kb_version=ctx["_kb_version"],
            input_sha256=_input_hash(data),
            retrieved_chunk_ids=[s.chunk_id for s in ctx["_sources"]],
            cited_chunk_ids=list(out.get("source_chunk_ids", [])),
            retrieval_sufficient=ctx["_sufficient"],
            grounding=str(out.get("grounding", "none")),
            source=item.source,
            outcome=AIOutcome.ok,
            attempts=0,
            failures=[],
            cache_hit=True,
            output_text=None,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        db.add(row)
        db.flush()
        return AIResult(
            function=spec.name,
            role=role,
            language=language,
            output=out,
            notice=None,
            source=item.source,
            outcome=AIOutcome.ok,
            grounding=str(out.get("grounding", "none")),
            sources=[SourceRef(c.chunk_id, c.handout_id, c.module) for c in cited],
            interaction_id=str(row.id),
            cache_hit=True,
        )


class _StreamAbortError(Exception):
    pass


def _relabel_unscoped(data: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Unscoped calls (no skill, e.g. select_skill) that claim manual grounding without sufficient
    retrieval are relabelled as general knowledge with no citations (D53). Skill-scoped calls are
    still rejected by the citation rule."""
    if ctx["_skill"] or data.get("grounding") != "manual":
        return False
    if ctx["_sources"] and ctx["_sufficient"]:
        return False
    data["grounding"] = "general"
    data["source_chunk_ids"] = []
    return True


# --- formatting helpers ------------------------------------------------------------------------

_SENTENCE = re.compile(r"(.+?(?:[。！？!?；;…]+[”」』）)]?|\.(?=\s)|\n+))", re.DOTALL)


def _split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences and the remainder. A trailing partial "<!--" (the META marker split
    across stream chunks) is held back so "<!" is never released as a sentence."""
    hold = ""
    cut = buffer.rfind("<")
    if cut >= 0 and len(buffer) - cut < 4 and "<!--".startswith(buffer[cut:]):
        buffer, hold = buffer[:cut], buffer[cut:]
    out: list[str] = []
    pos = 0
    for m in _SENTENCE.finditer(buffer):
        out.append(m.group(1))
        pos = m.end()
    return out, buffer[pos:] + hold


def _input_hash(data: In) -> str:
    return hashlib.sha256(data.model_dump_json().encode("utf-8")).hexdigest()


def _retry_note(failures: list[str], language: str) -> str:
    codes = ", ".join(
        sorted({f.split(":")[0] if f.startswith("provider") else f for f in failures})
    )
    if language == "zh-CN":
        return (
            f"【重新生成】上一次的输出没有通过系统检查（{codes}）。请重新生成：严格按照输出格式，"
            "只引用给出的来源编号，用自己的话改写手册内容（不要照抄），使用简体中文，并遵守所有规则。"
        )
    return (
        f"[Regenerate] The previous output failed the system checks ({codes}). Generate it again: "
        "follow the output format exactly, cite only the source labels you were given, paraphrase "
        "the manual in your own words (no copying), write in English, and follow every rule."
    )


def _risk_instruction(enabled: bool, language: str) -> str:
    if language == "zh-CN":
        if enabled:
            return (
                "请同时评估学生最新消息的风险：risk_level 取 none/low/medium/high；"
                "只有明确的自伤、自杀或伤害他人意图或计划才是 high，并设 should_stop=true；"
                "严重绝望或暗示性的自我伤害为 medium；一般的烦躁、觉得难为 low 或 none。"
                "risk_reasoning 简要说明理由。"
            )
        return '本轮无需评估风险：risk_level 填 "none"，should_stop 填 false，risk_reasoning 留空。'
    if enabled:
        return (
            "Also assess the risk in the student's latest message: risk_level "
            "none/low/medium/high. Only explicit self-harm, suicide or harm-to-others intent or "
            "plans are high, with should_stop=true; severe hopelessness or indirect self-harm "
            "hints are medium; ordinary frustration or finding the lesson hard is low or none. "
            "Give a short risk_reasoning."
        )
    return (
        'Risk is assessed separately this turn: use risk_level "none", should_stop false, '
        "empty risk_reasoning."
    )


def _format_profile(profile: Any, language: str) -> str:
    zh = language == "zh-CN"
    if profile is None:
        return "学生没有填写问卷。" if zh else "The student has not filled in the questionnaire."
    labels = (
        {
            "age": "年龄",
            "grade": "年级",
            "gender": "性别",
            "hobby_tags": "爱好",
            "concern_tags": "关心的事",
            "other_hobby_text": "其他爱好",
            "other_concern_text": "其他关心的事",
        }
        if zh
        else {
            "age": "age",
            "grade": "grade",
            "gender": "gender",
            "hobby_tags": "hobbies",
            "concern_tags": "concerns",
            "other_hobby_text": "other hobbies",
            "other_concern_text": "other concerns",
        }
    )
    lines = []
    for key, label in labels.items():
        value = getattr(profile, key, None)
        if not value:
            continue
        if isinstance(value, list):
            value = ("、" if zh else ", ").join(value)
        lines.append(f"- {label}: {value}")
    return "\n".join(lines) or ("（空）" if zh else "(empty)")


def _format_history(history: Sequence[Any], language: str) -> str:
    zh = language == "zh-CN"
    if not history:
        return "（还没有对话）" if zh else "(no conversation yet)"
    lines = []
    for t in history:
        if t.role == "student":
            lines.append(("学生：" if zh else "Student: ") + templating.as_data(t.content))
        else:
            lines.append(("教练：" if zh else "Coach: ") + t.content)
    return "\n".join(lines)


def _format_plan(steps: Sequence[Any], current: int, language: str) -> str:
    zh = language == "zh-CN"
    if not steps:
        return "（还没有教学计划）" if zh else "(no plan yet)"
    mark = " ← 当前步骤" if zh else " <- current step"
    return "\n".join(
        f"{s.step_number}. {s.title}{mark if s.step_number == current else ''}\n   {s.content}"
        for s in steps
    )


def _format_sources(chunks: Sequence[SourceChunk], language: str, svc: AIService) -> str:
    zh = language == "zh-CN"
    if not chunks:
        return (
            '（没有检索到足够的手册内容。只能使用通用的DBT知识，grounding 必须填 "general"，'
            "source_chunk_ids 为空。）"
            if zh
            else "(No sufficient manual material was found. Use general DBT knowledge only: "
            'grounding must be "general" and source_chunk_ids empty.)'
        )
    head = (
        "以下是手册内容（仅供你理解和改写，不要照抄原文，不要逐字引用）："
        if zh
        else "Manual material (Chinese; for your understanding only: paraphrase in English, "
        "never copy or quote it):"
    )
    parts = [head]
    for c in chunks:
        module = svc.module_name(c.module, language)
        parts.append(f"[{c.label}] {c.title} ({module})\n{c.text}")
    return "\n\n".join(parts)
