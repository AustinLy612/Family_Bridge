"""Input and output schemas for every AI function (Plan §5.4 table; Phase 4 task 3).

Inputs are strict (`extra="forbid"`): they are the complete list of what may reach the model.
No real names, no Diary Card data and no other participant's data have a field here, so they
cannot be sent (Plan §5.4 "Never sent to the LLM"). Free-text fields are capped.

Outputs are what the model must return. Every output carries `source_chunk_ids` (labels of the
retrieved chunks it used, mapped to chunk ids by the service), `grounding` and `confidence`;
`language` is set by the server after the language check. Field length limits are rule check 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Language = Literal["zh-CN", "en"]
Role = Literal["adolescent", "caregiver", "any"]
Grounding = Literal["manual", "general", "none"]
Confidence = Literal["high", "medium", "low"]
RiskLevel = Literal["none", "low", "medium", "high"]

FREE_TEXT_MAX = 500  # matches LESSON_MESSAGE_MAX_CHARS default; the service enforces settings


# T<n>: required text up to n characters; O<n>: may be empty.
O200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=0, max_length=200)]
O300 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=0, max_length=300)]
O400 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=0, max_length=400)]
OFree = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=0, max_length=FREE_TEXT_MAX)
]
T100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
T12 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)]
T120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
T160 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
T20 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
T200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
T2000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
T300 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
T40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
T400 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
T60 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
T600 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
T900 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=900)]
TFree = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=FREE_TEXT_MAX)
]

SkillIdStr = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}\.[a-z0-9_]+$")]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Out(BaseModel):
    model_config = ConfigDict(extra="ignore")  # unknown keys from the model are dropped

    source_chunk_ids: list[T12] = Field(default_factory=list, max_length=8)
    grounding: Grounding = "none"
    confidence: Confidence = "medium"
    language: str = ""  # set by the server, never asked of the model


SERVER_FIELDS = frozenset({"language"})


# --- shared input pieces ---------------------------------------------------------------------


class LearnerProfileIn(In):
    """DBT_Revised profile questionnaire (Plan §4.1 LearnerProfile). No names."""

    age: int | None = Field(default=None, ge=10, le=19)
    grade: T12 | None = None
    gender: Literal["female", "male", "other", "prefer_not_to_say"] | None = None
    hobby_tags: list[T20] = Field(default_factory=list, max_length=10)
    concern_tags: list[T20] = Field(default_factory=list, max_length=5)
    other_hobby_text: T100 | None = None
    other_concern_text: T100 | None = None


class Turn(In):
    role: Literal["student", "coach"]
    content: T2000


class PlanStepOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_number: int = Field(ge=1, le=10)
    title: T60
    content: T300
    estimated_minutes: int = Field(ge=1, le=15)


# --- adolescent lesson (D21) -----------------------------------------------------------------


class PersonalInquiryIn(In):
    profile: LearnerProfileIn | None = None
    mood: int = Field(ge=1, le=5)
    mood_note: OFree = ""


class PersonalInquiryOut(Out):
    greeting: T300
    question: T200
    inquiry_focus: T60


class SelectSkillIn(In):
    profile: LearnerProfileIn | None = None
    mood: int | None = Field(default=None, ge=1, le=5)
    checkin_answer: OFree = ""
    history_skills: list[SkillIdStr] = Field(default_factory=list, max_length=60)
    recent_skills: list[SkillIdStr] = Field(default_factory=list, max_length=10)
    weak_skills: list[SkillIdStr] = Field(default_factory=list, max_length=20)


class SelectSkillOut(Out):
    selected_module: T40
    selected_skill: T60
    reason: T300
    skill_difficulty: Literal["beginner", "intermediate", "advanced"]
    alternative_skills: list[T60] = Field(min_length=2, max_length=3)
    is_repeat: bool = False
    repeat_justification: O300 = ""

    @model_validator(mode="after")
    def _repeat(self) -> Self:
        if self.is_repeat and not self.repeat_justification:
            raise ValueError("is_repeat=true needs repeat_justification")
        return self


class TeachingPlanIn(In):
    profile: LearnerProfileIn | None = None
    skill_id: SkillIdStr


class TeachingPlanOut(Out):
    module: T40
    skill: T60
    plan_steps: list[PlanStepOut] = Field(min_length=2, max_length=8)


class TeachingOpeningIn(In):
    profile: LearnerProfileIn | None = None
    skill_id: SkillIdStr
    selection_reason: O300 = ""
    checkin_answer: OFree = ""
    plan_steps: list[PlanStepOut] = Field(default_factory=list, max_length=8)


MessageType = Literal["practice", "example", "question", "feedback", "explanation", "summary"]


class TeachingMessageOut(Out):
    """`teaching_opening` and `teaching_turn` (streamed: content first, metadata at the end)."""

    message_type: MessageType
    content: T900  # about one screen
    question: O200 = ""
    risk_level: RiskLevel = "none"
    should_stop: bool = False
    risk_reasoning: O300 = ""


class TeachingTurnIn(In):
    profile: LearnerProfileIn | None = None
    skill_id: SkillIdStr
    plan_steps: list[PlanStepOut] = Field(default_factory=list, max_length=8)
    current_step: int = Field(default=1, ge=1, le=10)
    history: list[Turn] = Field(default_factory=list, max_length=12)
    message: TFree
    assess_risk: bool = False
    last_message_type: MessageType | None = None


class TeachingSummaryIn(In):
    profile: LearnerProfileIn | None = None
    skill_id: SkillIdStr
    history: list[Turn] = Field(default_factory=list, max_length=80)


class TeachingSummaryOut(Out):
    skill_covered: T60
    key_points: list[T120] = Field(min_length=3, max_length=5)
    understanding: Literal["good", "fair", "needs_review"]
    recommendations: list[T160] = Field(min_length=2, max_length=4)
    summary_text: T600


class SkillTestIn(In):
    profile: LearnerProfileIn | None = None
    skill_id: SkillIdStr
    key_points: list[T120] = Field(default_factory=list, max_length=5)
    attempt: int = Field(default=1, ge=1, le=20)
    previous_scores: list[int] = Field(default_factory=list, max_length=20)  # correct of 5
    previous_questions: list[T200] = Field(default_factory=list, max_length=25)


def _distinct_options(options: list[str]) -> None:
    if len({o.strip().casefold() for o in options}) != len(options):
        raise ValueError("options must be distinct")


class TestQuestionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenario_text: T300
    question_text: T200
    options: list[T120] = Field(min_length=4, max_length=4)
    correct_option: int = Field(ge=0, le=3)
    explanation: T400

    @model_validator(mode="after")
    def _opts(self) -> Self:
        _distinct_options(self.options)
        return self


class SkillTestOut(Out):
    questions: list[TestQuestionOut] = Field(min_length=5, max_length=5)
    test_difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"


# --- caregiver structured lessons (D8/D23) -----------------------------------------------------


class ExplainSkillIn(In):
    skill_id: SkillIdStr
    variant: Literal["standard", "simpler", "another_example"] = "standard"


class ExplainSkillOut(Out):
    title: T60
    summary: T600
    key_points: list[T160] = Field(min_length=3, max_length=5)
    everyday_example: T400
    check_question: T200


RubricTag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,39}$")]


class PracticeOption(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: T160
    rubric_tag: RubricTag


class PracticeItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenario: T300
    prompt: T200
    answer_mode: Literal["choice", "short_text"]
    options: list[PracticeOption] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _mode(self) -> Self:
        if self.answer_mode == "choice":
            if len(self.options) < 3:
                raise ValueError("choice items need 3-4 options")
            _distinct_options([o.text for o in self.options])
        elif self.options:
            raise ValueError("short_text items have no options")
        return self


class PracticeItemsIn(In):
    skill_id: SkillIdStr


class PracticeItemsOut(Out):
    items: list[PracticeItemOut] = Field(min_length=2, max_length=3)


class PracticeItemIn(In):
    scenario: T300
    prompt: T200
    answer_mode: Literal["choice", "short_text"]
    options: list[T160] = Field(default_factory=list, max_length=4)


class EvaluatePracticeIn(In):
    skill_id: SkillIdStr
    item: PracticeItemIn
    answer: TFree  # option text or the caregiver's words
    rubric_tag: RubricTag | None = None  # known for choice answers


class EvaluatePracticeOut(Out):
    category: RubricTag
    what_worked: T300
    why: T400
    try_next: T300
    allow_retry: bool = True


class QuizIn(In):
    skill_id: SkillIdStr


class QuizQuestionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    stem: T300
    options: list[T120] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: T400

    @model_validator(mode="after")
    def _opts(self) -> Self:
        _distinct_options(self.options)
        return self


class QuizOut(Out):
    questions: list[QuizQuestionOut] = Field(min_length=3, max_length=5)


# --- episodes (placeholders, D12) ---------------------------------------------------------------


class HintIn(In):
    skill_id: SkillIdStr | None = None
    step_prompt: T300
    hint_scope: T300  # authored: what a hint may talk about
    attempts: int = Field(default=1, ge=1, le=10)


class HintOut(Out):
    hint: T200


class PersonalizeFeedbackIn(In):
    skill_id: SkillIdStr | None = None
    rubric_tag: RubricTag
    authored_feedback: T400


class PersonalizeFeedbackOut(Out):
    feedback: T400


# --- safety ---------------------------------------------------------------------------------------


class AssessRiskIn(In):
    message: T2000
    recent: list[T2000] = Field(default_factory=list, max_length=3)
    keyword_terms: list[T60] = Field(default_factory=list, max_length=20)


class AssessRiskOut(Out):
    risk_level: RiskLevel
    categories: list[T40] = Field(default_factory=list, max_length=5)
    should_stop: bool
    reasoning: O400 = ""


# --- function registry ----------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    input: type[In]
    output: type[Out]
    roles: tuple[Role, ...]
    retrieval: bool  # skill-scoped knowledge-base retrieval before the call
    streamed: bool = False
    cacheable: bool = False  # caregiver items cached per skill/lang/prompt/KB version
    max_tokens: int = 2048
    user_facing: bool = True  # output shown to participants (output-pattern rules apply)


FUNCTIONS: dict[str, FunctionSpec] = {
    s.name: s
    for s in (
        FunctionSpec(
            "personal_inquiry", PersonalInquiryIn, PersonalInquiryOut, ("adolescent",), False
        ),
        FunctionSpec("select_skill", SelectSkillIn, SelectSkillOut, ("adolescent",), True),
        FunctionSpec("teaching_plan", TeachingPlanIn, TeachingPlanOut, ("adolescent",), True),
        FunctionSpec(
            "teaching_opening", TeachingOpeningIn, TeachingMessageOut, ("adolescent",), True
        ),
        FunctionSpec(
            "teaching_turn",
            TeachingTurnIn,
            TeachingMessageOut,
            ("adolescent",),
            True,
            streamed=True,
        ),
        FunctionSpec(
            "teaching_summary", TeachingSummaryIn, TeachingSummaryOut, ("adolescent",), True
        ),
        FunctionSpec(
            "generate_skill_test", SkillTestIn, SkillTestOut, ("adolescent",), True, max_tokens=4096
        ),
        FunctionSpec(
            "explain_skill", ExplainSkillIn, ExplainSkillOut, ("caregiver",), True, cacheable=True
        ),
        FunctionSpec(
            "generate_practice_items",
            PracticeItemsIn,
            PracticeItemsOut,
            ("caregiver",),
            True,
            cacheable=True,
        ),
        FunctionSpec(
            "evaluate_practice_answer",
            EvaluatePracticeIn,
            EvaluatePracticeOut,
            ("caregiver",),
            True,
        ),
        FunctionSpec(
            "generate_quiz", QuizIn, QuizOut, ("caregiver",), True, cacheable=True, max_tokens=3072
        ),
        FunctionSpec("generate_hint", HintIn, HintOut, ("adolescent", "caregiver"), False),
        FunctionSpec(
            "personalize_feedback",
            PersonalizeFeedbackIn,
            PersonalizeFeedbackOut,
            ("adolescent", "caregiver"),
            False,
        ),
        FunctionSpec(
            "assess_risk",
            AssessRiskIn,
            AssessRiskOut,
            ("any",),
            False,
            max_tokens=512,
            user_facing=False,
        ),
    )
}

# Keys whose values are labels/ids/internal notes, not participant-facing prose.
NON_PROSE_KEYS = frozenset(
    {
        "source_chunk_ids",
        "grounding",
        "confidence",
        "language",
        "message_type",
        "selected_module",
        "selected_skill",
        "alternative_skills",
        "skill_difficulty",
        "understanding",
        "answer_mode",
        "rubric_tag",
        "category",
        "categories",
        "risk_level",
        "risk_reasoning",
        "reasoning",
        "inquiry_focus",
        "test_difficulty",
        "module",
        "skill",
    }
)


def prose(data: Any, key: str | None = None) -> list[str]:
    """All participant-facing strings in an output, in order."""
    if key in NON_PROSE_KEYS:
        return []
    if isinstance(data, str):
        return [data] if data.strip() else []
    if isinstance(data, dict):
        return [s for k, v in data.items() for s in prose(v, k)]
    if isinstance(data, list):
        return [s for v in data for s in prose(v, key)]
    return []


# Template variables each prompt may use (checked when content loads). Free-text values are
# wrapped as delimited data by the prompt builder before they are inserted.
COMMON_VARS = frozenset({"language_name"})
PROMPT_VARS: dict[str, frozenset[str]] = {
    "personal_inquiry": frozenset({"profile", "mood", "mood_note"}),
    "select_skill": frozenset(
        {
            "profile",
            "mood",
            "checkin_answer",
            "history_skills",
            "recent_skills",
            "weak_skills",
            "skill_catalogue",
            "sources",
        }
    ),
    "teaching_plan": frozenset({"profile", "skill_name", "module_name", "sources"}),
    "teaching_opening": frozenset(
        {
            "profile",
            "skill_name",
            "module_name",
            "selection_reason",
            "checkin_answer",
            "first_step",
            "sources",
        }
    ),
    "teaching_turn": frozenset(
        {
            "profile",
            "skill_name",
            "module_name",
            "plan",
            "current_step",
            "history",
            "message",
            "last_message_type",
            "risk_instruction",
            "sources",
        }
    ),
    "teaching_summary": frozenset({"profile", "skill_name", "history", "sources"}),
    "generate_skill_test": frozenset(
        {
            "profile",
            "skill_name",
            "module_name",
            "key_points",
            "attempt",
            "previous_scores",
            "previous_questions",
            "sources",
        }
    ),
    "explain_skill": frozenset({"skill_name", "module_name", "variant", "sources"}),
    "generate_practice_items": frozenset({"skill_name", "module_name", "sources"}),
    "evaluate_practice_answer": frozenset(
        {"skill_name", "item", "answer", "rubric_tag", "sources"}
    ),
    "generate_quiz": frozenset({"skill_name", "module_name", "sources"}),
    "generate_hint": frozenset({"skill_name", "step_prompt", "hint_scope", "attempts"}),
    "personalize_feedback": frozenset({"skill_name", "rubric_tag", "authored_feedback"}),
    "assess_risk": frozenset({"message", "recent", "keyword_terms"}),
}
