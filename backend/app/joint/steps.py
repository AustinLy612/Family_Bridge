"""Step-type modules for the episode engine (Plan §5.9 "Engine rules").

Each module handles one `type` from the episode schema:
- `act(step, ss, role, kind, value, ctx)` validates and applies a participant's submit or skip
  (raises `EngineError`);
- `role_done(step, ss, role, ctx)` says whether that role has finished the step;
- `project(step, ss, role, ctx)` returns the step fields this role may see.

`ss` is the step's own JSON state inside the room snapshot. The snapshot never holds free text
or distress values: those are stored privately by the service (D76, D77), and the step keeps
only "submitted" / "skipped".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.content.models import (
    CooperativeComposeStep,
    DistressCheckStep,
    Episode,
    EpisodeOption,
    FeedbackStep,
    NarrationStep,
    PrivateChoiceStep,
    PrivateReflectionStep,
    RetryStep,
    TransferProbeStep,
)

SUBMITTED = "submitted"
SKIPPED = "skipped"


class EngineError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Ctx:
    episode: Episode
    roles: tuple[str, ...]
    steps_state: dict[str, Any]  # the whole snapshot["steps"], for steps that read earlier ones

    @property
    def solo(self) -> bool:
        return len(self.roles) == 1


def _opt(o: EpisodeOption, *, with_tag: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"id": o.id, "text": o.text.model_dump(by_alias=True)}
    if with_tag:
        out["rubric_tag"] = o.rubric_tag
    return out


def _bi(b: Any) -> Any:
    return b.model_dump(by_alias=True) if b is not None else None


def _acts(ss: dict[str, Any], key: str = "acts") -> dict[str, str]:
    acts: dict[str, str] = ss.setdefault(key, {})
    return acts


def _ensure_open(ss: dict[str, Any], role: str, key: str = "acts") -> None:
    if role in ss.get(key, {}):
        raise EngineError("room.already_acted")


def _partner_acted(ss: dict[str, Any], role: str, ctx: Ctx, key: str = "acts") -> bool | None:
    others = [r for r in ctx.roles if r != role]
    return None if not others else others[0] in ss.get(key, {})


class StepModule(Protocol):
    def act(
        self, step: Any, ss: dict[str, Any], role: str, kind: str, value: Any, ctx: Ctx
    ) -> None: ...

    def role_done(self, step: Any, ss: dict[str, Any], role: str, ctx: Ctx) -> bool: ...

    def all_skipped(self, step: Any, ss: dict[str, Any], ctx: Ctx) -> bool: ...

    def project(self, step: Any, ss: dict[str, Any], role: str, ctx: Ctx) -> dict[str, Any]: ...


class Simple:
    """One act per role: submit (acknowledge) or skip."""

    def validate(self, step: Any, role: str, value: Any, ctx: Ctx) -> Any:
        return None

    def act(
        self, step: Any, ss: dict[str, Any], role: str, kind: str, value: Any, ctx: Ctx
    ) -> None:
        _ensure_open(ss, role)
        if kind == "skip":
            _acts(ss)[role] = SKIPPED
            return
        data = self.validate(step, role, value, ctx)
        _acts(ss)[role] = SUBMITTED
        if data is not None:
            ss.setdefault("data", {})[role] = data

    def role_done(self, step: Any, ss: dict[str, Any], role: str, ctx: Ctx) -> bool:
        return role in ss.get("acts", {})

    def all_skipped(self, step: Any, ss: dict[str, Any], ctx: Ctx) -> bool:
        acts = ss.get("acts", {})
        return bool(acts) and all(v == SKIPPED for v in acts.values())

    def project(self, step: Any, ss: dict[str, Any], role: str, ctx: Ctx) -> dict[str, Any]:
        return {
            "my_act": ss.get("acts", {}).get(role),
            "partner_acted": _partner_acted(ss, role, ctx),
        }


class Narration(Simple):
    pass


class DistressCheck(Simple):
    """0-10 or skipped. The value goes to `DistressRating` only (D76), never into the snapshot."""

    def validate(self, step: Any, role: str, value: Any, ctx: Ctx) -> Any:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10:
            raise EngineError("room.invalid_value")
        return None


class TransferProbe(Simple):
    def validate(self, step: TransferProbeStep, role: str, value: Any, ctx: Ctx) -> Any:
        if not any(o.id == value for o in step.options):
            raise EngineError("room.invalid_value")
        return value

    def project(
        self, step: TransferProbeStep, ss: dict[str, Any], role: str, ctx: Ctx
    ) -> dict[str, Any]:
        out = super().project(step, ss, role, ctx)
        out["options"] = [_opt(o) for o in step.options]
        mine = ss.get("data", {}).get(role)
        chosen = next((o for o in step.options if o.id == mine), None)
        out["my_choice"] = mine
        out["my_feedback"] = _bi(chosen.feedback) if chosen else None
        return out


class PrivateReflection(Simple):
    """Free text is screened and stored encrypted by the service (D77); here only the act."""

    def validate(self, step: PrivateReflectionStep, role: str, value: Any, ctx: Ctx) -> Any:
        if not isinstance(value, str) or not value.strip() or len(value) > step.max_chars:
            raise EngineError("room.invalid_value")
        return None

    def project(
        self, step: PrivateReflectionStep, ss: dict[str, Any], role: str, ctx: Ctx
    ) -> dict[str, Any]:
        out = super().project(step, ss, role, ctx)
        out["max_chars"] = step.max_chars
        return out


class _Reviewed:
    """A step with an input phase, then (when there is something to show) a review phase that
    every role acknowledges. `key` holds input acts, "acks" holds review acknowledgements."""

    key = "acts"

    def has_review(self, step: Any, ss: dict[str, Any], ctx: Ctx) -> bool:
        raise NotImplementedError

    def validate(self, step: Any, role: str, value: Any, ctx: Ctx) -> Any:
        raise NotImplementedError

    def inputs_done(self, ss: dict[str, Any], ctx: Ctx) -> bool:
        return all(r in ss.get(self.key, {}) for r in ctx.roles)

    def act(
        self, step: Any, ss: dict[str, Any], role: str, kind: str, value: Any, ctx: Ctx
    ) -> None:
        if not self.inputs_done(ss, ctx):
            _ensure_open(ss, role, self.key)
            if kind == "skip":
                _acts(ss, self.key)[role] = SKIPPED
                return
            data = self.validate(step, role, value, ctx)
            _acts(ss, self.key)[role] = SUBMITTED
            ss.setdefault("data", {})[role] = data
            return
        # review phase: submit or skip both acknowledge
        _ensure_open(ss, role, "acks")
        _acts(ss, "acks")[role] = SUBMITTED if kind == "submit" else SKIPPED

    def role_done(self, step: Any, ss: dict[str, Any], role: str, ctx: Ctx) -> bool:
        if not self.inputs_done(ss, ctx):
            return False
        if not self.has_review(step, ss, ctx):
            return True
        return role in ss.get("acks", {})

    def all_skipped(self, step: Any, ss: dict[str, Any], ctx: Ctx) -> bool:
        acts = ss.get(self.key, {})
        return bool(acts) and all(v == SKIPPED for v in acts.values())

    def base_projection(self, ss: dict[str, Any], role: str, ctx: Ctx) -> dict[str, Any]:
        reviewing = self.inputs_done(ss, ctx)
        return {
            "phase": "review" if reviewing else "input",
            "my_act": ss.get("acks" if reviewing else self.key, {}).get(role),
            "partner_acted": _partner_acted(ss, role, ctx, "acks" if reviewing else self.key),
        }


class PrivateChoice(_Reviewed):
    def validate(self, step: PrivateChoiceStep, role: str, value: Any, ctx: Ctx) -> Any:
        if not any(o.id == value for o in step.roles[role].options):  # type: ignore[index]
            raise EngineError("room.invalid_value")
        return value

    def has_review(self, step: PrivateChoiceStep, ss: dict[str, Any], ctx: Ctx) -> bool:
        acts = ss.get(self.key, {})
        # Reveal only when every role submitted (Plan §5.9 `both_submitted`); never in solo.
        return (
            step.reveal is not None
            and not ctx.solo
            and all(acts.get(r) == SUBMITTED for r in ctx.roles)
        )

    def project(
        self, step: PrivateChoiceStep, ss: dict[str, Any], role: str, ctx: Ctx
    ) -> dict[str, Any]:
        out = self.base_projection(ss, role, ctx)
        own = step.roles[role]  # type: ignore[index]
        out["prompt"] = _bi(own.prompt)
        out["options"] = [_opt(o) for o in own.options]  # own role's options only
        out["my_choice"] = ss.get("data", {}).get(role)
        if out["phase"] == "review" and self.has_review(step, ss, ctx):
            out["revealed"] = self.reveal(step, ss, ctx)
        return out

    def reveal(self, step: PrivateChoiceStep, ss: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        assert step.reveal is not None
        shown: dict[str, Any] = {}
        for r in ctx.roles:
            choice = ss["data"][r]
            opt = next(o for o in step.roles[r].options if o.id == choice)  # type: ignore[index]
            item: dict[str, Any] = {}
            if "choice_text" in step.reveal.fields:
                item["text"] = _bi(opt.text)
            if "rubric_tag_summary" in step.reveal.fields:
                item["rubric_tag"] = opt.rubric_tag
            shown[r] = item
        return shown

    def rubric(self, step: PrivateChoiceStep, ss: dict[str, Any], role: str) -> list[str]:
        choice = ss.get("data", {}).get(role)
        opts = step.roles[role].options if role in step.roles else []
        return [o.rubric_tag for o in opts if o.id == choice]


def _fragments(step: CooperativeComposeStep, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise EngineError("room.invalid_value")
    ids = list(dict.fromkeys(value))
    known = {f.id for f in step.fragments}
    if any(i not in known for i in ids):
        raise EngineError("room.invalid_value")
    if not step.rules.min_per_role <= len(ids) <= step.rules.max_per_role:
        raise EngineError("room.invalid_value")
    return ids


def composition(step: CooperativeComposeStep, data: dict[str, list[str]]) -> list[dict[str, Any]]:
    """The shared reply in authored order, with who contributed each piece (no scores)."""
    out = []
    for f in step.fragments:
        by = [r for r, ids in data.items() if f.id in ids]
        if by:
            out.append({**_opt(f, with_tag=True), "by": by})
    return out


def feedback_for(step: FeedbackStep, tags: set[str]) -> dict[str, Any]:
    rule = next((r for r in step.rules if r.matches(tags)), None)
    title, text = (rule.title, rule.text) if rule else (step.default.title, step.default.text)
    notes = [_bi(n) for t, n in step.tag_notes.items() if t in tags]
    return {"title": _bi(title), "text": _bi(text), "notes": notes}


class CooperativeCompose:
    """Each role submits its pieces once; neither leads. The step completes when all acted."""

    def act(
        self,
        step: CooperativeComposeStep,
        ss: dict[str, Any],
        role: str,
        kind: str,
        value: Any,
        ctx: Ctx,
    ) -> None:
        _ensure_open(ss, role)
        if kind == "skip":
            _acts(ss)[role] = SKIPPED
            return
        ss.setdefault("data", {})[role] = _fragments(step, value)
        _acts(ss)[role] = SUBMITTED

    def role_done(self, step: Any, ss: dict[str, Any], role: str, ctx: Ctx) -> bool:
        return role in ss.get("acts", {})

    def all_skipped(self, step: Any, ss: dict[str, Any], ctx: Ctx) -> bool:
        acts = ss.get("acts", {})
        return bool(acts) and all(v == SKIPPED for v in acts.values())

    def project(
        self, step: CooperativeComposeStep, ss: dict[str, Any], role: str, ctx: Ctx
    ) -> dict[str, Any]:
        mine = ss.get("data", {}).get(role)
        partner = [r for r in ctx.roles if r != role]
        return {
            "fragments": [_opt(f) for f in step.fragments],
            "rules": step.rules.model_dump(),
            "my_act": ss.get("acts", {}).get(role),
            "my_fragments": mine,
            "partner_acted": _partner_acted(ss, role, ctx),
            # contribution indicator: how many pieces the partner added, never which ones yet
            "partner_count": len(ss.get("data", {}).get(partner[0], [])) if partner else None,
        }

    @staticmethod
    def tags(step: CooperativeComposeStep, data: dict[str, list[str]]) -> set[str]:
        return {f["rubric_tag"] for f in composition(step, data)}


class Feedback(Simple):
    def project(
        self, step: FeedbackStep, ss: dict[str, Any], role: str, ctx: Ctx
    ) -> dict[str, Any]:
        out = super().project(step, ss, role, ctx)
        src = ctx.episode.step(step.source)
        data = ctx.steps_state.get(step.source, {}).get("data", {})
        assert isinstance(src, CooperativeComposeStep)
        out["composition"] = composition(src, data)
        out["feedback"] = feedback_for(step, CooperativeCompose.tags(src, data))
        return out


class Retry(_Reviewed):
    """Second opportunity (§6.3): compose again with the same pieces, then review feedback."""

    def validate(self, step: RetryStep, role: str, value: Any, ctx: Ctx) -> Any:
        src = ctx.episode.step(step.of)
        assert isinstance(src, CooperativeComposeStep)
        return _fragments(src, value)

    def has_review(self, step: RetryStep, ss: dict[str, Any], ctx: Ctx) -> bool:
        return any(v == SUBMITTED for v in ss.get(self.key, {}).values())

    def project(self, step: RetryStep, ss: dict[str, Any], role: str, ctx: Ctx) -> dict[str, Any]:
        out = self.base_projection(ss, role, ctx)
        src = ctx.episode.step(step.of)
        fb = ctx.episode.step(step.feedback)
        assert isinstance(src, CooperativeComposeStep) and isinstance(fb, FeedbackStep)
        data = ss.get("data", {})
        partner = [r for r in ctx.roles if r != role]
        out["fragments"] = [_opt(f) for f in src.fragments]
        out["rules"] = src.rules.model_dump()
        out["my_fragments"] = data.get(role)
        out["partner_count"] = len(data.get(partner[0], [])) if partner else None
        if out["phase"] == "review":
            out["composition"] = composition(src, data)
            out["feedback"] = feedback_for(fb, CooperativeCompose.tags(src, data))
        return out


MODULES: dict[str, Any] = {
    "narration": Narration(),
    "distress_check": DistressCheck(),
    "private_choice": PrivateChoice(),
    "cooperative_compose": CooperativeCompose(),
    "feedback": Feedback(),
    "retry": Retry(),
    "transfer_probe": TransferProbe(),
    "private_reflection": PrivateReflection(),
}

_ = (NarrationStep, DistressCheckStep)  # imported for type references in docs
