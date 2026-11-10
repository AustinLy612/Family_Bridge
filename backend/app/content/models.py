"""Pydantic models for files under `content/` (Plan Phase 0 task 6).

Every clinical content file carries an approval block (prompt §5 "Safety & clinical
governance"). Unapproved content may only be used for demo/test families; that rule
is enforced where content is *used* (from Phase 1 on), not here.

Schemas for later content kinds (diary templates, fallbacks, episodes, help, consent,
safety lists, eval sets) are added in the phase that introduces them. Until then the
loader rejects files it has no schema for, so nothing unvalidated can slip in.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SUPPORTED_LANGS: tuple[str, ...] = ("zh-CN", "en")

SkillId = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}\.[a-z0-9_]+$")]
ModuleId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApprovalStatus(StrEnum):
    demo = "demo"
    draft = "draft"
    approved = "approved"
    retired = "retired"


class Approval(Strict):
    status: ApprovalStatus
    approved_by: str | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def _approved_needs_signoff(self) -> Self:
        if self.status is ApprovalStatus.approved and not (self.approved_by and self.approved_at):
            raise ValueError("approval.status=approved requires approved_by and approved_at")
        return self


class BilingualText(Strict):
    zh_CN: str = Field(alias="zh-CN", min_length=1)  # noqa: N815 (mirrors the locale code)
    en: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# --- skills/taxonomy.yaml (Appendix B) -------------------------------------------------


class Skill(Strict):
    id: SkillId
    # Bilingual names and handout refs are filled in Phase 3 (task 1) from the manual.
    name: BilingualText | None = None
    handout_refs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class Module(Strict):
    id: ModuleId
    name: BilingualText | None = None
    skills: list[Skill] = Field(min_length=1)


class SkillTaxonomy(Strict):
    kind: str = Field(pattern=r"^skill_taxonomy$")
    version: int = Field(ge=1)
    approval: Approval
    modules: list[Module] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        seen: set[str] = set()
        mods: set[str] = set()
        for m in self.modules:
            if m.id in mods:
                raise ValueError(f"duplicate module id: {m.id}")
            mods.add(m.id)
            for s in m.skills:
                if s.id in seen:
                    raise ValueError(f"duplicate skill id: {s.id}")
                seen.add(s.id)
        return self

    def skill_ids(self) -> list[str]:
        return [s.id for m in self.modules for s in m.skills]


# --- consent/{zh,en}/vN.md (Plan §5.2; D31, D32) ----------------------------------------

LANG_DIRS: dict[str, str] = {"zh": "zh-CN", "en": "en"}

ConsentCategoryId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,47}$")]


class ConsentCategory(Strict):
    id: ConsentCategoryId
    required: bool
    # Initial switch position shown to the participant (D32: research_export starts ON).
    default: bool = True
    grantee: str = Field(pattern=r"^[a-z][a-z0-9_]{2,47}$")
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class ConsentBlock(Strict):
    type: str = Field(pattern=r"^(paragraph|bullets)$")
    text: str | None = None
    items: list[str] = Field(default_factory=list)


class ConsentSection(Strict):
    heading: str = Field(min_length=1)
    blocks: list[ConsentBlock]


class ConsentDocument(Strict):
    """Front-matter + a restricted Markdown body (## headings, paragraphs, '- ' bullets).

    The body is parsed into structured sections so the UI never renders raw HTML.
    """

    kind: str = Field(pattern=r"^consent$")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    language: str
    approval: Approval
    roles: list[str] = Field(min_length=1)
    categories: list[ConsentCategory] = Field(min_length=1)
    sections: list[ConsentSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.language not in SUPPORTED_LANGS:
            raise ValueError(f"unsupported language: {self.language}")
        bad = set(self.roles) - {"adolescent", "caregiver"}
        if bad:
            raise ValueError(f"consent roles must be participant roles, got {sorted(bad)}")
        ids = [c.id for c in self.categories]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate consent category id")
        return self

    def category(self, cid: str) -> ConsentCategory | None:
        return next((c for c in self.categories if c.id == cid), None)


# --- help/{zh,en}.md (Plan §5.7; O4) ---------------------------------------------------------


class Notice(Strict):
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=400)


class HelpDocument(Strict):
    """Static help screen text. Contacts and staffed hours come from `Site`, not from here."""

    kind: str = Field(pattern=r"^help$")
    id: str = Field(pattern=r"^help$")
    version: int = Field(ge=1)
    language: str
    approval: Approval
    stop_notice: Notice  # shown when an activity is stopped by the safety flow
    care_card: Notice  # shown on medium risk (Plan §5.7)
    sections: list[ConsentSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.language not in SUPPORTED_LANGS:
            raise ValueError(f"unsupported language: {self.language}")
        return self

    def all_text(self) -> list[str]:
        out = [
            self.stop_notice.title,
            self.stop_notice.body,
            self.care_card.title,
            self.care_card.body,
        ]
        for s in self.sections:
            out.append(s.heading)
            for b in s.blocks:
                out.extend([b.text] if b.text else b.items)
        return out


# --- safety/risk_keywords.yaml, safety/forbidden_phrases.yaml (Plan §5.7, §7.2) ------------


def _clean_terms(terms: list[str], where: str) -> None:
    if any(not t.strip() or t != t.strip() for t in terms):
        raise ValueError(f"{where}: empty term or surrounding whitespace")
    lowered = [t.casefold() for t in terms]
    if len(lowered) != len(set(lowered)):
        raise ValueError(f"{where}: duplicate term")


class RiskTerms(Strict):
    high: list[str] = Field(min_length=1)
    moderate: list[str] = Field(default_factory=list)
    concern: list[str] = Field(default_factory=list)
    # Ordinary phrases removed before matching (e.g. "想死你了" = "miss you so much").
    benign: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Self:
        for name in ("high", "moderate", "concern", "benign"):
            _clean_terms(getattr(self, name), name)
        risky = {t.casefold() for t in [*self.high, *self.moderate, *self.concern]}
        clash = risky & {t.casefold() for t in self.benign}
        if clash:
            raise ValueError(f"terms listed as both risky and benign: {sorted(clash)}")
        return self


class RiskKeywords(Strict):
    kind: str = Field(pattern=r"^risk_keywords$")
    version: int = Field(ge=1)
    approval: Approval
    languages: dict[str, RiskTerms]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if set(self.languages) != set(SUPPORTED_LANGS):
            raise ValueError(f"languages must be exactly {list(SUPPORTED_LANGS)}")
        return self


class PhraseRules(Strict):
    forbidden: list[str] = Field(min_length=1)  # Python regular expressions
    required_in_help: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _compiles(self) -> Self:
        import re

        for pattern in self.forbidden:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid pattern {pattern!r}: {exc}") from exc
        return self


class ForbiddenPhrases(Strict):
    kind: str = Field(pattern=r"^forbidden_phrases$")
    version: int = Field(ge=1)
    approval: Approval
    languages: dict[str, PhraseRules]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if set(self.languages) != set(SUPPORTED_LANGS):
            raise ValueError(f"languages must be exactly {list(SUPPORTED_LANGS)}")
        return self


# --- skills/handouts.yaml (Plan §5.3 step 3, Appendix A; D44) -----------------------------------

HandoutId = Annotated[str, StringConstraints(pattern=r"^(ori|mf|dt|wmp|er|ie)\.h\d{1,2}[ab]?$")]


class Handout(Strict):
    id: HandoutId
    module: ModuleId
    number: str = Field(pattern=r"^\d{1,2}[ab]?$")
    title_en: str = Field(min_length=1, max_length=120)
    pages: list[int] = Field(min_length=1)
    skill_ids: list[SkillId] = Field(min_length=1)
    is_worksheet: bool = False
    diagram_pages: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.pages != sorted(set(self.pages)):
            raise ValueError(f"{self.id}: pages must be ascending and unique")
        if not set(self.diagram_pages) <= set(self.pages):
            raise ValueError(f"{self.id}: diagram_pages must be among pages")
        if self.id.split(".")[1] != f"h{self.number}":
            raise ValueError(f"{self.id}: id does not match number {self.number}")
        return self


class HandoutSource(Strict):
    pdf_pages: int = Field(ge=1)
    index_pages: list[int]
    divider_pages: list[int]


class HandoutIndex(Strict):
    kind: str = Field(pattern=r"^handout_index$")
    version: int = Field(ge=1)
    approval: Approval
    source: HandoutSource
    handouts: list[Handout] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [h.id for h in self.handouts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate handout id")
        seen: dict[int, str] = {}
        for h in self.handouts:
            for p in h.pages:
                if p in seen:
                    raise ValueError(f"page {p} is in both {seen[p]} and {h.id}")
                if (
                    p > self.source.pdf_pages
                    or p in self.source.index_pages + self.source.divider_pages
                ):
                    raise ValueError(f"{h.id}: page {p} is not a content page")
                seen[p] = h.id
        return self

    def get(self, handout_id: str) -> Handout | None:
        return next((h for h in self.handouts if h.id == handout_id), None)


# --- eval/retrieval/v*.yaml (Plan §5.3 step 8) -------------------------------------------

EVAL_MIN_QUERIES = 60
EVAL_MIN_PER_LANGUAGE = 25


class EvalQuery(Strict):
    id: str = Field(pattern=r"^q\d{3}$")
    language: Literal["zh-CN", "en"]
    # Written by the developer in their own words (never copied from the manual).
    query: str = Field(min_length=2, max_length=200)
    expected: list[HandoutId] = Field(min_length=1)  # any of these in the top k counts as a hit
    skill_ids: list[SkillId] = Field(default_factory=list)  # optional search filter
    module: ModuleId | None = None  # optional search filter


class RetrievalEvalSet(Strict):
    kind: str = Field(pattern=r"^retrieval_eval$")
    version: int = Field(ge=1)
    approval: Approval
    k: int = Field(default=5, ge=1, le=20)
    target_recall: float = Field(default=0.85, gt=0, le=1)
    queries: list[EvalQuery] = Field(min_length=EVAL_MIN_QUERIES)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [q.id for q in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate query id")
        for lang in ("zh-CN", "en"):
            n = sum(q.language == lang for q in self.queries)
            if n < EVAL_MIN_PER_LANGUAGE:
                raise ValueError(f"{lang}: {n} queries, need at least {EVAL_MIN_PER_LANGUAGE}")
        return self


# --- AI layer (Plan §5.4, §7.3; Phase 4) ------------------------------------------------------

Lang = Literal["zh-CN", "en"]
_PLACEHOLDER = r"\{\{([a-z_]+)\}\}"


def _compiles(patterns: list[str], where: str) -> None:
    import re

    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{where}: invalid pattern {pattern!r}: {exc}") from exc


class PromptTemplate(Strict):
    """content/prompts/{function}/{role}/{zh|en}/vN.md: front-matter + '## system' + '## user'."""

    kind: str = Field(pattern=r"^prompt$")
    function: str = Field(pattern=r"^[a-z_]+$")
    role: Literal["adolescent", "caregiver", "any"]
    language: Lang
    version: int = Field(ge=1)
    approval: Approval
    derived_from: str | None = None  # e.g. the DBT_Revised prompt it was ported from
    changelog: list[str] = Field(min_length=1)
    blocks: list[str] = Field(default_factory=list)  # shared blocks appended to the system text
    system: str = Field(min_length=20)
    user: str = Field(min_length=5)

    def placeholders(self) -> set[str]:
        import re

        return set(re.findall(_PLACEHOLDER, self.system + "\n" + self.user))


class PromptBlock(Strict):
    """content/prompts/_shared/{zh|en}/<id>.md: a shared rule block (Plan §5.4)."""

    kind: str = Field(pattern=r"^prompt_block$")
    id: str = Field(pattern=r"^[a-z_]+$")
    language: Lang
    version: int = Field(ge=1)
    approval: Approval
    text: str = Field(min_length=10)


class LangPatterns(Strict):
    en: list[str] = Field(default_factory=list)
    zh_CN: list[str] = Field(default_factory=list, alias="zh-CN")  # noqa: N815

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    def all(self) -> list[str]:
        return [*self.en, *self.zh_CN]


class OverlapLimits(Strict):
    max_shared_chars: int = Field(ge=8, le=60)
    max_shared_en_words: int = Field(ge=4, le=40)


class LanguageLimits(Strict):
    zh_min_cjk_ratio: float = Field(gt=0, le=1)
    en_max_cjk_ratio: float = Field(ge=0, lt=1)


class MedicalCaution(Strict):
    triggers: LangPatterns
    required_any: LangPatterns


class OutputRules(Strict):
    kind: str = Field(pattern=r"^output_rules$")
    version: int = Field(ge=1)
    approval: Approval
    overlap: OverlapLimits
    language: LanguageLimits
    categories: dict[str, LangPatterns] = Field(min_length=1)
    # Categories whose matches inside quotation marks are allowed: quoting what not to say is a
    # normal teaching device (e.g. an invalidating remark as the wrong practice option).
    quoted_examples_allowed: list[str] = Field(default_factory=list)
    medical_caution: MedicalCaution

    @model_validator(mode="after")
    def _check(self) -> Self:
        unknown = set(self.quoted_examples_allowed) - set(self.categories)
        if unknown:
            raise ValueError(f"quoted_examples_allowed names unknown categories: {sorted(unknown)}")
        for name, pats in self.categories.items():
            if not pats.all():
                raise ValueError(f"category {name} has no patterns")
            _compiles(pats.all(), name)
        _compiles(self.medical_caution.triggers.all(), "medical_caution.triggers")
        _compiles(self.medical_caution.required_any.all(), "medical_caution.required_any")
        return self


class FallbackDoc(Strict):
    """content/fallbacks/{function}/{skill_id|_default}/{zh|en}.yaml (Plan §5.4).

    `notice` is always shown when the AI output is unavailable. `output` is an optional authored
    answer in the function's output schema ({skill_name} and {module_name} are filled in).
    """

    kind: str = Field(pattern=r"^fallback$")
    function: str = Field(pattern=r"^[a-z_]+$")
    skill: str = Field(pattern=r"^(_default|[a-z]{2,3}\.[a-z0-9_]+)$")
    language: Lang
    version: int = Field(ge=1)
    approval: Approval
    notice: str = Field(min_length=5, max_length=300)
    output: dict[str, object] | None = None


class GoldenSkill(Strict):
    skill_id: SkillId
    roles: list[Literal["adolescent", "caregiver"]] = Field(min_length=1)
    # Developer paraphrase of what a correct explanation must cover (never manual wording, D7).
    key_points: dict[Lang, list[str]]

    @model_validator(mode="after")
    def _check(self) -> Self:
        for lang in ("zh-CN", "en"):
            pts = self.key_points.get(lang)
            if not pts or not 2 <= len(pts) <= 5:
                raise ValueError(f"{self.skill_id}: {lang} needs 2-5 key points")
        return self


class RubricItem(Strict):
    id: str = Field(pattern=r"^[a-z_]+$")
    label: BilingualText
    scale: str = Field(min_length=3)


class GoldenEvalSet(Strict):
    kind: str = Field(pattern=r"^golden_eval$")
    version: int = Field(ge=1)
    approval: Approval
    rubric: list[RubricItem] = Field(min_length=3)
    skills: list[GoldenSkill] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [s.skill_id for s in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate skill in golden set")
        return self


class AdversarialCase(Strict):
    id: str = Field(pattern=r"^[a-z]+-\d{2}$")
    severity: Literal["high", "medium", "low"]
    language: Lang
    variant: Literal["direct", "indirect", "multi_turn"]
    target: Literal["safety", "function", "output"]
    function: str | None = None
    role: Literal["adolescent", "caregiver"] = "adolescent"
    skill_id: SkillId | None = None
    turns: list[str] = Field(default_factory=list, max_length=3)  # earlier messages, same user
    input: str | None = Field(default=None, max_length=500)
    output: dict[str, object] | None = None  # canned model output (target=output)
    expected: Literal["stop", "flag", "no_flag", "safe_output", "blocked"]
    must_not: list[str] = Field(default_factory=list)  # regexes on the final participant text
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> Self:
        ok = {
            "safety": {"stop", "flag", "no_flag"},
            "function": {"safe_output"},
            "output": {"blocked"},
        }[self.target]
        if self.expected not in ok:
            raise ValueError(f"{self.id}: expected {self.expected} does not fit {self.target}")
        if self.target in ("safety", "function") and not self.input:
            raise ValueError(f"{self.id}: input is required")
        if self.target in ("function", "output") and not (self.function and self.skill_id):
            raise ValueError(f"{self.id}: function and skill_id are required")
        if self.target == "output" and not self.output:
            raise ValueError(f"{self.id}: output is required")
        if self.variant == "multi_turn" and not self.turns:
            raise ValueError(f"{self.id}: multi_turn cases need earlier turns")
        _compiles(self.must_not, self.id)
        return self


ADVERSARIAL_CATEGORIES: tuple[str, ...] = (
    "inaccurate_dbt_advice",
    "invalidating_or_blaming",
    "coercive_parent_instructions",
    "boundary_violations",
    "adult_disclosures",
    "stereotyped_family_roles",
    "partner_diary_requests",
    "self_harm_statements",
    "prompt_injection",
    "fabricated_authorisation",
    "fantasy_to_trauma",
    "self_disclosure_requests",
    "shame_inducing_feedback",
)


class AdversarialSet(Strict):
    kind: str = Field(pattern=r"^adversarial_eval$")
    category: str
    version: int = Field(ge=1)
    approval: Approval
    cases: list[AdversarialCase] = Field(min_length=5)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.category not in ADVERSARIAL_CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")
        ids = [c.id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case id")
        if {c.language for c in self.cases} != {"zh-CN", "en"}:
            raise ValueError("cases must cover zh-CN and en")
        if not any(c.variant != "direct" for c in self.cases):
            raise ValueError("include indirect or multi-turn variants")
        return self


# --- diary/{role}/v*.yaml (Plan §5.6; D9, D17, D63–D66) -------------------------------------

DiaryFieldId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,39}$")]
DIARY_URGE_FIELDS: tuple[str, ...] = ("self_harm_urge", "suicide_urge")  # D14, safety/service.py
DIARY_NOTE_MAX = 1000
SCALE_MIN, SCALE_MAX = 1, 10


class DiaryFieldType(StrEnum):
    scale = "scale"  # integer 1–10
    boolean = "boolean"
    skills = "skills"  # multi-select from the skill taxonomy
    frequency = "frequency"  # one of the template's options
    note = "note"  # free text, encrypted and risk-screened


class DiaryOption(Strict):
    id: DiaryFieldId
    label: BilingualText


class DiaryField(Strict):
    id: DiaryFieldId
    type: DiaryFieldType
    label: BilingualText
    hint: BilingualText | None = None
    low: BilingualText | None = None  # scale anchors
    high: BilingualText | None = None
    options: list[DiaryOption] = Field(default_factory=list)  # frequency only
    show_if: DiaryFieldId | None = None  # a boolean field earlier in the card that must be yes
    urge: bool = False  # the D14 urge threshold applies

    @model_validator(mode="after")
    def _check(self) -> Self:
        t = self.type
        if (self.low is None) != (self.high is None):
            raise ValueError(f"{self.id}: give both low and high anchors or neither")
        if self.low is not None and t is not DiaryFieldType.scale:
            raise ValueError(f"{self.id}: anchors only apply to scales")
        if t is DiaryFieldType.frequency:
            if len(self.options) < 2:
                raise ValueError(f"{self.id}: a frequency field needs at least two options")
            if len({o.id for o in self.options}) != len(self.options):
                raise ValueError(f"{self.id}: duplicate option id")
        elif self.options:
            raise ValueError(f"{self.id}: options only apply to frequency fields")
        if self.urge and (t is not DiaryFieldType.scale or self.id not in DIARY_URGE_FIELDS):
            raise ValueError(f"{self.id}: urge fields must be scales named {DIARY_URGE_FIELDS}")
        if self.id in DIARY_URGE_FIELDS and not self.urge:
            raise ValueError(f"{self.id}: must be marked urge: true")
        return self


class DiaryGroup(Strict):
    id: DiaryFieldId
    label: BilingualText
    fields: list[DiaryField] = Field(min_length=1)


class DiaryTemplate(Strict):
    kind: str = Field(pattern=r"^diary_template$")
    role: Literal["adolescent", "caregiver"]
    version: int = Field(ge=1)
    approval: Approval
    title: BilingualText
    intro: BilingualText
    groups: list[DiaryGroup] = Field(min_length=1)

    @property
    def fields(self) -> list[DiaryField]:
        return [f for g in self.groups for f in g.fields]

    def field(self, field_id: str) -> DiaryField | None:
        return next((f for f in self.fields if f.id == field_id), None)

    def all_text(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"zh-CN": [], "en": []}

        def add(b: BilingualText | None) -> None:
            if b is not None:
                out["zh-CN"].append(b.zh_CN)
                out["en"].append(b.en)

        add(self.title)
        add(self.intro)
        for g in self.groups:
            add(g.label)
            for f in g.fields:
                for b in (f.label, f.hint, f.low, f.high):
                    add(b)
                for o in f.options:
                    add(o.label)
        return out

    @model_validator(mode="after")
    def _check(self) -> Self:
        seen: dict[str, DiaryField] = {}
        for f in self.fields:
            if f.id in seen:
                raise ValueError(f"duplicate field id {f.id!r}")
            if f.show_if is not None:
                dep = seen.get(f.show_if)
                if dep is None or dep.type is not DiaryFieldType.boolean:
                    raise ValueError(f"{f.id}: show_if must name an earlier yes/no field")
            seen[f.id] = f
        if len({g.id for g in self.groups}) != len(self.groups):
            raise ValueError("duplicate group id")
        if sum(f.type is DiaryFieldType.note for f in self.fields) > 1:
            raise ValueError("at most one note field")
        return self


# --- episodes/<id>/vN.yaml and episodes/catalog.yaml (Plan §5.9; D12, O1) ---------------
#
# Schema v0 is a draft to be validated against the real flow scripts (O1). Step types are
# modular: each has an engine module in `app/joint/steps.py`. All text is authored; AI may only
# reword feedback later (`personalize_feedback`), never change tags or outcomes.

EPISODE_SCHEMA_VERSION = 0
EpisodeId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,62}$")]
StepId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,24}$")]
OptionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,32}$")]
RubricTag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,31}$")]
EpisodeRole = Literal["adolescent", "caregiver"]


class EpisodeMode(StrEnum):
    joint = "joint"
    solo = "solo"


class EpisodeOption(Strict):
    id: OptionId
    text: BilingualText
    rubric_tag: RubricTag
    feedback: BilingualText | None = None  # transfer_probe: shown to the chooser only


class StepBase(Strict):
    id: StepId
    title: BilingualText | None = None
    text: BilingualText
    hints: list[BilingualText] = Field(default_factory=list, max_length=5)  # authored only
    skippable: bool = True
    # "both": never completes on one participant's action (Plan §5.9). "either": first act wins.
    requires: Literal["both", "either"] = "both"

    def texts(self) -> list[BilingualText]:
        return [t for t in (self.title, self.text, *self.hints) if t is not None]


class NarrationStep(StepBase):
    type: Literal["narration"]


class DistressCheckStep(StepBase):
    type: Literal["distress_check"]


class RoleChoice(Strict):
    prompt: BilingualText | None = None
    options: list[EpisodeOption] = Field(min_length=2, max_length=8)


class Reveal(Strict):
    fields: list[Literal["rubric_tag_summary", "choice_text"]] = Field(min_length=1)
    when: Literal["both_submitted"] = "both_submitted"


class PrivateChoiceStep(StepBase):
    type: Literal["private_choice"]
    roles: dict[EpisodeRole, RoleChoice]
    reveal: Reveal | None = None  # None: never shown to the partner

    @model_validator(mode="after")
    def _both_roles(self) -> Self:
        if set(self.roles) != {"adolescent", "caregiver"}:
            raise ValueError(f"{self.id}: private_choice needs options for both roles")
        for rc in self.roles.values():
            if len({o.id for o in rc.options}) != len(rc.options):
                raise ValueError(f"{self.id}: duplicate option id")
        return self

    def texts(self) -> list[BilingualText]:
        out = super().texts()
        for rc in self.roles.values():
            out += [rc.prompt] if rc.prompt else []
            out += [o.text for o in rc.options]
        return out


class ComposeRules(Strict):
    min_per_role: int = Field(default=1, ge=0, le=5)
    max_per_role: int = Field(default=3, ge=1, le=5)


class CooperativeComposeStep(StepBase):
    type: Literal["cooperative_compose"]
    fragments: list[EpisodeOption] = Field(min_length=2, max_length=12)
    rules: ComposeRules = ComposeRules()

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len({f.id for f in self.fragments}) != len(self.fragments):
            raise ValueError(f"{self.id}: duplicate fragment id")
        if self.rules.min_per_role > self.rules.max_per_role:
            raise ValueError(f"{self.id}: min_per_role > max_per_role")
        return self

    def texts(self) -> list[BilingualText]:
        return super().texts() + [f.text for f in self.fragments]


class FeedbackRule(Strict):
    all: list[RubricTag] = Field(default_factory=list)
    any: list[RubricTag] = Field(default_factory=list)
    none: list[RubricTag] = Field(default_factory=list)
    title: BilingualText
    text: BilingualText

    def matches(self, tags: set[str]) -> bool:
        return (
            set(self.all) <= tags
            and (not self.any or bool(tags & set(self.any)))
            and not (tags & set(self.none))
        )


class FeedbackDefault(Strict):
    title: BilingualText
    text: BilingualText


class FeedbackStep(StepBase):
    """Authored rubric -> feedback for a cooperative_compose step (first matching rule wins)."""

    type: Literal["feedback"]
    source: StepId
    rules: list[FeedbackRule] = Field(default_factory=list)
    default: FeedbackDefault
    tag_notes: dict[RubricTag, BilingualText] = Field(default_factory=dict)

    def texts(self) -> list[BilingualText]:
        out = [*super().texts(), self.default.title, self.default.text]
        for r in self.rules:
            out += [r.title, r.text]
        return out + list(self.tag_notes.values())


class RetryStep(StepBase):
    """A second opportunity (§6.3): compose again with the same fragments, then see feedback."""

    type: Literal["retry"]
    of: StepId
    feedback: StepId


class TransferProbeStep(StepBase):
    type: Literal["transfer_probe"]
    options: list[EpisodeOption] = Field(min_length=2, max_length=6)

    def texts(self) -> list[BilingualText]:
        out = super().texts()
        for o in self.options:
            out += [o.text] + ([o.feedback] if o.feedback else [])
        return out


class PrivateReflectionStep(StepBase):
    type: Literal["private_reflection"]
    max_chars: int = Field(default=500, ge=50, le=2000)


EpisodeStep = Annotated[
    NarrationStep
    | DistressCheckStep
    | PrivateChoiceStep
    | CooperativeComposeStep
    | FeedbackStep
    | RetryStep
    | TransferProbeStep
    | PrivateReflectionStep,
    Field(discriminator="type"),
]


class Sensory(Strict):
    motion: Literal["none", "low", "medium"] = "low"
    sound: Literal["none", "optional"] = "optional"


class Episode(Strict):
    kind: str = Field(pattern=r"^episode$")
    id: EpisodeId
    schema_version: int
    version: int = Field(ge=1)
    approval: Approval
    world: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    level: int = Field(ge=1, le=9)
    modes: list[EpisodeMode] = Field(default_factory=lambda: [EpisodeMode.joint], min_length=1)
    title: BilingualText
    skill_ids: list[SkillId] = Field(min_length=1)
    objective: BilingualText
    behavioral_criterion: BilingualText
    estimated_minutes: int = Field(ge=1, le=60)
    sensory: Sensory = Sensory()
    steps: list[EpisodeStep] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.schema_version != EPISODE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate step id")
        seen: dict[str, str] = {}
        for s in self.steps:
            if isinstance(s, FeedbackStep) and seen.get(s.source) != "cooperative_compose":
                raise ValueError(f"{s.id}: source must name an earlier cooperative_compose step")
            if isinstance(s, RetryStep):
                if seen.get(s.of) != "cooperative_compose":
                    raise ValueError(f"{s.id}: of must name an earlier cooperative_compose step")
                if seen.get(s.feedback) != "feedback":
                    raise ValueError(f"{s.id}: feedback must name an earlier feedback step")
            seen[s.id] = s.type
        return self

    def step(self, step_id: str) -> EpisodeStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def all_text(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"zh-CN": [], "en": []}
        for b in [self.title, self.objective, self.behavioral_criterion] + [
            t for s in self.steps for t in s.texts()
        ]:
            out["zh-CN"].append(b.zh_CN)
            out["en"].append(b.en)
        return out


class CatalogLevel(Strict):
    level: int = Field(ge=1, le=9)
    focus: BilingualText
    skill_ids: list[SkillId] = Field(min_length=1)
    target_minutes: tuple[int, int]


class CatalogWorld(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    name: BilingualText
    levels: list[CatalogLevel] = Field(min_length=1)


class EpisodeCatalog(Strict):
    """Placeholder worlds and levels shown to therapists as "coming soon" (§6.5)."""

    kind: str = Field(pattern=r"^episode_catalog$")
    version: int = Field(ge=1)
    approval: Approval
    worlds: list[CatalogWorld] = Field(min_length=1)
