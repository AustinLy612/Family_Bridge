"""Content loader (Plan Phase 0 task 6).

Loads every file under `content/`, validates it against its Pydantic model, and
fails fast (raises ContentError listing *all* problems) on anything invalid or
unrecognised. Exposes per-file and aggregate SHA-256 version hashes, which later
phases record with every record that depends on content (Plan §3.2).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from app.content.models import (
    LANG_DIRS,
    AdversarialSet,
    ConsentDocument,
    DiaryTemplate,
    Episode,
    EpisodeCatalog,
    FallbackDoc,
    ForbiddenPhrases,
    GoldenEvalSet,
    HandoutIndex,
    HelpDocument,
    OutputRules,
    PromptBlock,
    PromptTemplate,
    RetrievalEvalSet,
    RiskKeywords,
    SkillTaxonomy,
)
from app.content.phrases import forbidden_hits, missing_required

# Files that document the content tree rather than being content.
IGNORED_NAMES = frozenset({"README.md", ".gitkeep"})


@dataclass(frozen=True)
class ContentKind:
    name: str
    pattern: str  # posix glob relative to content/
    parse: Callable[[bytes], BaseModel]


def _yaml_model(model: type[BaseModel]) -> Callable[[bytes], BaseModel]:
    def parse(raw: bytes) -> BaseModel:
        data: Any = yaml.safe_load(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level must be a mapping")
        return model.model_validate(data)

    return parse


def split_front_matter(raw: bytes) -> tuple[dict[str, Any], str]:
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML front-matter (file must start with '---')")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated YAML front-matter")
    meta: Any = yaml.safe_load(text[4:end])
    if not isinstance(meta, dict):
        raise ValueError("front-matter must be a mapping")
    return meta, text[end + 5 :]


def parse_restricted_markdown(body: str) -> list[dict[str, Any]]:
    """'## ' starts a section, '- ' lines form bullet lists, other lines join into paragraphs.

    Anything that looks like HTML is rejected so content can never inject markup.
    """
    if "<" in body or ">" in body:
        raise ValueError("HTML is not allowed in content text")
    sections: list[dict[str, Any]] = []
    para: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if not sections:
            if para or bullets:
                raise ValueError("text before the first '## ' heading")
            return
        blocks = sections[-1]["blocks"]
        if para:
            blocks.append({"type": "paragraph", "text": " ".join(para)})
            para.clear()
        if bullets:
            blocks.append({"type": "bullets", "items": list(bullets)})
            bullets.clear()

    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            sections.append({"heading": stripped[3:].strip(), "blocks": []})
        elif stripped.startswith("#"):
            raise ValueError("only '## ' headings are allowed")
        elif stripped.startswith("- "):
            if para:
                flush()
            bullets.append(stripped[2:].strip())
        elif not stripped:
            flush()
        else:
            if bullets:
                flush()
            para.append(stripped)
    flush()
    return sections


def _consent(raw: bytes) -> BaseModel:
    meta, body = split_front_matter(raw)
    return ConsentDocument.model_validate({**meta, "sections": parse_restricted_markdown(body)})


def _help(raw: bytes) -> BaseModel:
    meta, body = split_front_matter(raw)
    return HelpDocument.model_validate({**meta, "sections": parse_restricted_markdown(body)})


def _prompt(raw: bytes) -> BaseModel:
    """Front-matter, then exactly a '## system' and a '## user' section."""
    meta, body = split_front_matter(raw)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.split("\n"):
        # Only '## system' and '## user' delimit sections; other headings are prompt text.
        if line.strip() in ("## system", "## user"):
            current = line.strip()[3:]
            if current in sections or (current == "system" and "user" in sections):
                raise ValueError(f"repeated or misplaced section '## {current}'")
            sections[current] = []
        elif current is None:
            if line.strip():
                raise ValueError("text before '## system'")
        else:
            sections[current].append(line)
    texts = {k: "\n".join(v).strip() for k, v in sections.items()}
    return PromptTemplate.model_validate({**meta, **texts})


def _prompt_block(raw: bytes) -> BaseModel:
    meta, body = split_front_matter(raw)
    return PromptBlock.model_validate({**meta, "text": body.strip()})


# Registry of known content kinds. Later phases append to this list.
KINDS: list[ContentKind] = [
    ContentKind("skill_taxonomy", "skills/taxonomy.yaml", _yaml_model(SkillTaxonomy)),
    ContentKind("handout_index", "skills/handouts.yaml", _yaml_model(HandoutIndex)),
    ContentKind("retrieval_eval", "eval/retrieval/v*.yaml", _yaml_model(RetrievalEvalSet)),
    ContentKind("golden_eval", "eval/golden/v*.yaml", _yaml_model(GoldenEvalSet)),
    ContentKind("adversarial_eval", "eval/adversarial/*.yaml", _yaml_model(AdversarialSet)),
    ContentKind("prompt_block", "prompts/_shared/*/*.md", _prompt_block),
    ContentKind("prompt", "prompts/*/*/*/v*.md", _prompt),
    ContentKind("fallback", "fallbacks/*/*/*.yaml", _yaml_model(FallbackDoc)),
    ContentKind("output_rules", "safety/output_rules.yaml", _yaml_model(OutputRules)),
    ContentKind("consent", "consent/*/v*.md", _consent),
    ContentKind("help", "help/*.md", _help),
    ContentKind("diary_template", "diary/*/v*.yaml", _yaml_model(DiaryTemplate)),
    ContentKind("episode_catalog", "episodes/catalog.yaml", _yaml_model(EpisodeCatalog)),
    ContentKind("episode", "episodes/*/v*.yaml", _yaml_model(Episode)),
    ContentKind("risk_keywords", "safety/risk_keywords.yaml", _yaml_model(RiskKeywords)),
    ContentKind(
        "forbidden_phrases", "safety/forbidden_phrases.yaml", _yaml_model(ForbiddenPhrases)
    ),
]


class ContentError(Exception):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid content:\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True)
class LoadedFile:
    path: str  # posix, relative to content/
    kind: str
    sha256: str
    model: BaseModel


@dataclass(frozen=True)
class ContentBundle:
    root: Path
    files: dict[str, LoadedFile] = field(default_factory=dict)

    @property
    def hashes(self) -> dict[str, str]:
        return {p: f.sha256 for p, f in sorted(self.files.items())}

    @property
    def aggregate_hash(self) -> str:
        h = hashlib.sha256()
        for p, digest in self.hashes.items():
            h.update(f"{p}\0{digest}\n".encode())
        return h.hexdigest()

    @property
    def taxonomy(self) -> SkillTaxonomy | None:
        f = self.files.get("skills/taxonomy.yaml")
        return f.model if f is not None and isinstance(f.model, SkillTaxonomy) else None

    def consent(self, language: str, doc_id: str = "onboarding") -> ConsentDocument | None:
        """Latest version of a consent document in a language."""
        docs = [
            f.model
            for f in self.files.values()
            if isinstance(f.model, ConsentDocument)
            and f.model.id == doc_id
            and f.model.language == language
        ]
        return max(docs, key=lambda d: d.version, default=None)

    @property
    def retrieval_eval(self) -> RetrievalEvalSet | None:
        """Latest retrieval evaluation set (highest version)."""
        sets = [f.model for f in self.files.values() if isinstance(f.model, RetrievalEvalSet)]
        return max(sets, key=lambda m: m.version) if sets else None

    @property
    def handouts(self) -> HandoutIndex | None:
        f = self.files.get("skills/handouts.yaml")
        return f.model if f is not None and isinstance(f.model, HandoutIndex) else None

    def help(self, language: str) -> HelpDocument | None:
        f = self.files.get(f"help/{_lang_dir(language)}.md")
        return f.model if f is not None and isinstance(f.model, HelpDocument) else None

    def diary_template(self, role: str, version: int | None = None) -> DiaryTemplate | None:
        """The given version, or the latest version that is not retired."""
        found = [
            f.model
            for rel, f in self.files.items()
            if rel.startswith(f"diary/{role}/") and isinstance(f.model, DiaryTemplate)
        ]
        if version is not None:
            return next((t for t in found if t.version == version), None)
        live = [t for t in found if t.approval.status != "retired"]
        return max(live, key=lambda t: t.version, default=None)

    def diary_templates(self, role: str) -> list[DiaryTemplate]:
        """Every version of a role's diary template, oldest first (retired included)."""
        found = [
            f.model
            for rel, f in self.files.items()
            if rel.startswith(f"diary/{role}/") and isinstance(f.model, DiaryTemplate)
        ]
        return sorted(found, key=lambda t: t.version)

    @property
    def episodes(self) -> list[Episode]:
        """Every episode version (file approval status; the registry may override it)."""
        return sorted(
            (f.model for f in self.files.values() if isinstance(f.model, Episode)),
            key=lambda e: (e.id, e.version),
        )

    def episode(self, episode_id: str, version: int) -> Episode | None:
        return next((e for e in self.episodes if e.id == episode_id and e.version == version), None)

    @property
    def episode_catalog(self) -> EpisodeCatalog | None:
        f = self.files.get("episodes/catalog.yaml")
        return f.model if f is not None and isinstance(f.model, EpisodeCatalog) else None

    @property
    def risk_keywords(self) -> RiskKeywords | None:
        f = self.files.get("safety/risk_keywords.yaml")
        return f.model if f is not None and isinstance(f.model, RiskKeywords) else None

    @property
    def forbidden_phrases(self) -> ForbiddenPhrases | None:
        f = self.files.get("safety/forbidden_phrases.yaml")
        return f.model if f is not None and isinstance(f.model, ForbiddenPhrases) else None

    @property
    def output_rules(self) -> OutputRules | None:
        f = self.files.get("safety/output_rules.yaml")
        return f.model if f is not None and isinstance(f.model, OutputRules) else None

    def prompt(self, function: str, role: str, language: str) -> tuple[PromptTemplate, str] | None:
        """Latest prompt version for function x role x language, with its file SHA-256."""
        found = [
            (f.model, f.sha256)
            for f in self.files.values()
            if isinstance(f.model, PromptTemplate)
            and (f.model.function, f.model.role, f.model.language) == (function, role, language)
        ]
        return max(found, key=lambda t: t[0].version, default=None)

    def prompt_block(self, block_id: str, language: str) -> PromptBlock | None:
        f = self.files.get(f"prompts/_shared/{_lang_dir(language)}/{block_id}.md")
        return f.model if f is not None and isinstance(f.model, PromptBlock) else None

    def fallback(self, function: str, skill_id: str | None, language: str) -> FallbackDoc | None:
        """Skill-specific fallback if there is one, else the function's `_default`."""
        for skill in ([skill_id] if skill_id else []) + ["_default"]:
            f = self.files.get(f"fallbacks/{function}/{skill}/{_lang_dir(language)}.yaml")
            if f is not None and isinstance(f.model, FallbackDoc):
                return f.model
        return None

    @property
    def golden_eval(self) -> GoldenEvalSet | None:
        sets = [f.model for f in self.files.values() if isinstance(f.model, GoldenEvalSet)]
        return max(sets, key=lambda m: m.version) if sets else None

    @property
    def adversarial_sets(self) -> list[AdversarialSet]:
        return sorted(
            (f.model for f in self.files.values() if isinstance(f.model, AdversarialSet)),
            key=lambda m: m.category,
        )

    def consent_sha256(self, doc: ConsentDocument) -> str:
        lang_dir = next(k for k, v in LANG_DIRS.items() if v == doc.language)
        return self.files[f"consent/{lang_dir}/v{doc.version}.md"].sha256


def _lang_dir(language: str) -> str:
    return next((k for k, v in LANG_DIRS.items() if v == language), language)


def _help_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Help pages: one per language, file named after it, and no rescue promises (Plan §7.2)."""
    problems: list[str] = []
    helps = {rel: f.model for rel, f in files.items() if isinstance(f.model, HelpDocument)}
    rules_file = files.get("safety/forbidden_phrases.yaml")
    rules = (
        rules_file.model if rules_file and isinstance(rules_file.model, ForbiddenPhrases) else None
    )
    if helps and rules is None:
        problems.append("help pages need safety/forbidden_phrases.yaml")
    for rel, doc in helps.items():
        if rel != f"help/{_lang_dir(doc.language)}.md":
            problems.append(f"{rel}: language {doc.language!r} does not match the file name")
    if helps and {d.language for d in helps.values()} != set(LANG_DIRS.values()):
        problems.append("help pages must exist for every language")
    if len({d.version for d in helps.values()}) > 1:
        problems.append("help pages differ in version between languages")
    if rules is None:
        return problems
    for rel, doc in helps.items():
        texts = doc.all_text()
        problems += [
            f"{rel}: forbidden phrase {h}" for h in forbidden_hits(rules, doc.language, texts)
        ]
        problems += [f"{rel}: must say {m!r}" for m in missing_required(rules, doc.language, texts)]
    for rel, f in files.items():
        if isinstance(f.model, ConsentDocument):
            texts = consent_texts(f.model)
            problems += [
                f"{rel}: forbidden phrase {h}"
                for h in forbidden_hits(rules, f.model.language, texts)
            ]
    return problems


def _handout_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Taxonomy <-> handout index: skill ids exist, modules agree, handout_refs match exactly."""
    tax_f, idx_f = files.get("skills/taxonomy.yaml"), files.get("skills/handouts.yaml")
    if idx_f is None or not isinstance(idx_f.model, HandoutIndex):
        return []
    if tax_f is None or not isinstance(tax_f.model, SkillTaxonomy):
        return ["skills/handouts.yaml needs skills/taxonomy.yaml"]
    tax, idx = tax_f.model, idx_f.model
    problems: list[str] = []
    module_of = {s.id: m.id for m in tax.modules for s in m.skills}
    expected: dict[str, set[str]] = {sid: set() for sid in module_of}
    for h in idx.handouts:
        for sid in h.skill_ids:
            if sid not in module_of:
                problems.append(f"handouts.yaml: {h.id}: unknown skill {sid}")
            elif module_of[sid] != h.module:
                problems.append(f"handouts.yaml: {h.id}: skill {sid} is not in module {h.module}")
            else:
                expected[sid].add(h.id)
    for m in tax.modules:
        for s in m.skills:
            if set(s.handout_refs) != expected[s.id]:
                problems.append(
                    f"taxonomy.yaml: {s.id}: handout_refs {sorted(s.handout_refs)} do not match "
                    f"handouts.yaml {sorted(expected[s.id])}"
                )
    return problems


def _eval_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Eval queries point at real handouts and skills, and cover every module."""
    idx_f = files.get("skills/handouts.yaml")
    sets = [(r, f.model) for r, f in files.items() if isinstance(f.model, RetrievalEvalSet)]
    if not sets:
        return []
    if idx_f is None or not isinstance(idx_f.model, HandoutIndex):
        return ["eval/retrieval needs skills/handouts.yaml"]
    by_id = {h.id: h for h in idx_f.model.handouts}
    skills = {s for h in idx_f.model.handouts for s in h.skill_ids}
    modules = {h.module for h in idx_f.model.handouts}
    problems: list[str] = []
    for rel, ev in sets:
        covered: set[str] = set()
        for q in ev.queries:
            for hid in q.expected:
                if hid not in by_id:
                    problems.append(f"{rel}: {q.id}: unknown handout {hid}")
                else:
                    covered.add(by_id[hid].module)
            problems += [
                f"{rel}: {q.id}: unknown skill {s}" for s in q.skill_ids if s not in skills
            ]
            if q.module is not None and q.module not in modules:
                problems.append(f"{rel}: {q.id}: unknown module {q.module}")
        problems += [f"{rel}: no query covers module {m}" for m in sorted(modules - covered)]
    return problems


def _ai_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Prompts, blocks, fallbacks and AI eval sets (Plan §5.4, §7.2, §7.3)."""
    from app.ai.schemas import COMMON_VARS, FUNCTIONS, PROMPT_VARS
    from app.ai.templating import fill_fallback

    problems: list[str] = []
    rules_f = files.get("safety/forbidden_phrases.yaml")
    phrases = rules_f.model if rules_f and isinstance(rules_f.model, ForbiddenPhrases) else None
    tax_f = files.get("skills/taxonomy.yaml")
    tax = tax_f.model if tax_f and isinstance(tax_f.model, SkillTaxonomy) else None
    skill_ids = set(tax.skill_ids()) if tax else set()
    blocks = {
        (f.model.id, f.model.language) for f in files.values() if isinstance(f.model, PromptBlock)
    }
    prompts: set[tuple[str, str, str]] = set()
    for rel, f in files.items():
        m = f.model
        if isinstance(m, PromptBlock):
            if rel != f"prompts/_shared/{_lang_dir(m.language)}/{m.id}.md":
                problems.append(f"{rel}: path does not match id/language")
            if phrases:
                problems += [
                    f"{rel}: forbidden phrase {h}"
                    for h in forbidden_hits(phrases, m.language, [m.text])
                ]
        elif isinstance(m, PromptTemplate):
            expected = f"prompts/{m.function}/{m.role}/{_lang_dir(m.language)}/v{m.version}.md"
            if rel != expected:
                problems.append(f"{rel}: path should be {expected}")
            spec = FUNCTIONS.get(m.function)
            if spec is None:
                problems.append(f"{rel}: unknown AI function {m.function!r}")
                continue
            if m.role not in spec.roles:
                problems.append(f"{rel}: role {m.role} not used by {m.function}")
            unknown = m.placeholders() - PROMPT_VARS[m.function] - COMMON_VARS
            if unknown:
                problems.append(f"{rel}: unknown placeholders {sorted(unknown)}")
            problems += [
                f"{rel}: unknown block {b!r}" for b in m.blocks if (b, m.language) not in blocks
            ]
            if phrases:
                problems += [
                    f"{rel}: forbidden phrase {h}"
                    for h in forbidden_hits(phrases, m.language, [m.system, m.user])
                ]
            prompts.add((m.function, m.role, m.language))
        elif isinstance(m, FallbackDoc):
            expected = f"fallbacks/{m.function}/{m.skill}/{_lang_dir(m.language)}.yaml"
            if rel != expected:
                problems.append(f"{rel}: path should be {expected}")
            spec = FUNCTIONS.get(m.function)
            if spec is None:
                problems.append(f"{rel}: unknown AI function {m.function!r}")
                continue
            if m.skill != "_default" and m.skill not in skill_ids:
                problems.append(f"{rel}: unknown skill {m.skill}")
            texts = [m.notice]
            if m.output is not None:
                try:
                    out = fill_fallback(m.output, spec.output, "Skill", "Module")
                    texts += prose(out.model_dump())
                except ValueError as exc:
                    problems.append(f"{rel}: output does not fit {m.function}: {exc}")
            if phrases:
                problems += [
                    f"{rel}: forbidden phrase {h}"
                    for h in forbidden_hits(phrases, m.language, texts)
                ]
        elif isinstance(m, AdversarialSet):
            if rel != f"eval/adversarial/{m.category}.yaml":
                problems.append(f"{rel}: file name should be {m.category}.yaml")
            for c in m.cases:
                if c.function and c.function not in FUNCTIONS:
                    problems.append(f"{rel}: {c.id}: unknown function {c.function}")
                if c.skill_id and skill_ids and c.skill_id not in skill_ids:
                    problems.append(f"{rel}: {c.id}: unknown skill {c.skill_id}")
        elif isinstance(m, GoldenEvalSet):
            problems += [
                f"{rel}: unknown skill {g.skill_id}"
                for g in m.skills
                if skill_ids and g.skill_id not in skill_ids
            ]
    if prompts:
        for spec in FUNCTIONS.values():
            for role in spec.roles:
                for lang in LANG_DIRS.values():
                    if (spec.name, role, lang) not in prompts:
                        problems.append(f"prompts: missing {spec.name}/{role}/{_lang_dir(lang)}")
    fallback_keys = {
        (f.model.function, f.model.skill, f.model.language)
        for f in files.values()
        if isinstance(f.model, FallbackDoc)
    }
    if fallback_keys:
        for spec in FUNCTIONS.values():
            if spec.name == "assess_risk":  # degrades to keyword-only screening, no text
                continue
            for lang in LANG_DIRS.values():
                if (spec.name, "_default", lang) not in fallback_keys:
                    problems.append(f"fallbacks: missing {spec.name}/_default/{_lang_dir(lang)}")
    return problems


def prose(data: object) -> list[str]:
    from app.ai.schemas import prose as _prose

    return _prose(data)


def consent_texts(doc: ConsentDocument) -> list[str]:
    out = [t for c in doc.categories for t in (c.title, c.summary)]
    for s in doc.sections:
        out.append(s.heading)
        for b in s.blocks:
            out.extend([b.text] if b.text else b.items)
    return out


def _diary_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Diary templates: folder = role, file = version, taxonomy present, no negative copy."""
    problems: list[str] = []
    rules_file = files.get("safety/forbidden_phrases.yaml")
    rules = (
        rules_file.model if rules_file and isinstance(rules_file.model, ForbiddenPhrases) else None
    )
    templates = {rel: f.model for rel, f in files.items() if isinstance(f.model, DiaryTemplate)}
    for rel, t in templates.items():
        _, role, name = rel.split("/")
        if role != t.role:
            problems.append(f"{rel}: role {t.role!r} does not match folder {role!r}")
        if name != f"v{t.version}.yaml":
            problems.append(f"{rel}: file name does not match version {t.version}")
        if any(f.type == "skills" for f in t.fields) and "skills/taxonomy.yaml" not in files:
            problems.append(f"{rel}: a skills field needs skills/taxonomy.yaml")
        if rules is not None:
            for lang, texts in t.all_text().items():
                problems += [
                    f"{rel}: forbidden phrase {h}" for h in forbidden_hits(rules, lang, texts)
                ]
    return problems


def _episode_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Episodes: folder = id, file = version, skills exist, no forbidden phrases."""
    problems: list[str] = []
    rules_file = files.get("safety/forbidden_phrases.yaml")
    rules = (
        rules_file.model if rules_file and isinstance(rules_file.model, ForbiddenPhrases) else None
    )
    tax_file = files.get("skills/taxonomy.yaml")
    skills = (
        set(tax_file.model.skill_ids())
        if tax_file and isinstance(tax_file.model, SkillTaxonomy)
        else None
    )
    for rel, f in files.items():
        m = f.model
        if isinstance(m, Episode):
            _, folder, name = rel.split("/")
            if folder != m.id:
                problems.append(f"{rel}: id {m.id!r} does not match folder {folder!r}")
            if name != f"v{m.version}.yaml":
                problems.append(f"{rel}: file name does not match version {m.version}")
            texts = m.all_text()
            ids = m.skill_ids
        elif isinstance(m, EpisodeCatalog):
            texts = {"zh-CN": [], "en": []}
            ids = [s for w in m.worlds for lv in w.levels for s in lv.skill_ids]
            for w in m.worlds:
                for b in [w.name] + [lv.focus for lv in w.levels]:
                    texts["zh-CN"].append(b.zh_CN)
                    texts["en"].append(b.en)
        else:
            continue
        if skills is None:
            problems.append(f"{rel}: episodes need skills/taxonomy.yaml")
        else:
            problems += [f"{rel}: unknown skill {s!r}" for s in ids if s not in skills]
        if rules is not None:
            for lang, items in texts.items():
                problems += [
                    f"{rel}: forbidden phrase {h}" for h in forbidden_hits(rules, lang, items)
                ]
    return problems


def _cross_checks(files: dict[str, LoadedFile]) -> list[str]:
    """Checks that span files: consent language folders, zh/en parity, help-page phrase rules."""
    problems: list[str] = (
        _help_checks(files)
        + _handout_checks(files)
        + _eval_checks(files)
        + _ai_checks(files)
        + _diary_checks(files)
        + _episode_checks(files)
    )
    by_version: dict[tuple[str, int], dict[str, ConsentDocument]] = {}
    for rel, f in files.items():
        if not isinstance(f.model, ConsentDocument):
            continue
        doc = f.model
        lang_dir = rel.split("/")[1]
        if LANG_DIRS.get(lang_dir) != doc.language:
            problems.append(f"{rel}: language {doc.language!r} does not match folder {lang_dir!r}")
        if rel.rsplit("/", 1)[1] != f"v{doc.version}.md":
            problems.append(f"{rel}: file name does not match version {doc.version}")
        by_version.setdefault((doc.id, doc.version), {})[doc.language] = doc
    for (doc_id, version), langs in by_version.items():
        missing = set(LANG_DIRS.values()) - set(langs)
        if missing:
            problems.append(f"consent {doc_id} v{version}: missing language(s) {sorted(missing)}")
            continue
        shapes = {
            tuple((c.id, c.required, c.default, c.grantee) for c in d.categories)
            for d in langs.values()
        }
        if len(shapes) != 1:
            problems.append(f"consent {doc_id} v{version}: categories differ between languages")
        if len({tuple(d.roles) for d in langs.values()}) != 1:
            problems.append(f"consent {doc_id} v{version}: roles differ between languages")
    return problems


def _kind_for(rel: str, kinds: list[ContentKind]) -> ContentKind | None:
    return next((k for k in kinds if fnmatch(rel, k.pattern)), None)


def load_content(root: Path, kinds: list[ContentKind] | None = None) -> ContentBundle:
    kinds = KINDS if kinds is None else kinds
    if not root.is_dir():
        raise ContentError([f"content directory not found: {root}"])

    problems: list[str] = []
    files: dict[str, LoadedFile] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name in IGNORED_NAMES:
            continue
        rel = path.relative_to(root).as_posix()
        kind = _kind_for(rel, kinds)
        if kind is None:
            problems.append(f"{rel}: no schema registered for this file (unrecognised content)")
            continue
        raw = path.read_bytes()
        try:
            model = kind.parse(raw)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(x) for x in err["loc"]) or "<root>"
                problems.append(f"{rel}: {loc}: {err['msg']}")
            continue
        except yaml.YAMLError as exc:
            problems.append(f"{rel}: invalid YAML: {exc}")
            continue
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        files[rel] = LoadedFile(rel, kind.name, hashlib.sha256(raw).hexdigest(), model)

    if not problems:
        problems.extend(_cross_checks(files))
    if problems:
        raise ContentError(problems)
    return ContentBundle(root=root, files=files)
