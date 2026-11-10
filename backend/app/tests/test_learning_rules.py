"""Pure Phase 5 rules ported from DBT_Revised (Plan §5.5.1; Phase 5 task 9).

- plan step and auto-complete (`teaching/views.py` `_calc_current_step`, `_should_auto_complete`);
- repeat guard (`teaching/services.py` `_apply_repeat_guard`), with FamilyBridge's deterministic
  fallback instead of "keep the original";
- mastery at >= 4/5 and the five-question budget of a skill test;
- profile questionnaire validation.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.schemas import SkillTestOut
from app.learning.profile import ProfileIn
from app.learning.selection import SelectionContext, apply_repeat_guard
from app.learning.teaching import current_step, has_farewell, should_auto_complete
from app.learning.testing import is_mastered

# --- plan step and auto-complete ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("messages", "steps", "expected"),
    [(0, 3, 1), (1, 3, 1), (2, 3, 2), (4, 3, 3), (9, 3, 3), (5, 0, 1)],
)
def test_current_step(messages: int, steps: int, expected: int) -> None:
    assert current_step(messages, steps) == expected


def test_auto_complete_needs_two_exchanges() -> None:
    assert not should_auto_complete("summary", "", 3, 1)
    assert should_auto_complete("summary", "", 4, 1)


def test_auto_complete_needs_every_plan_step_covered() -> None:
    assert not should_auto_complete("summary", "", 4, 4)  # step 4 not reached
    assert should_auto_complete("summary", "", 4, 2)
    assert should_auto_complete("feedback", "", 6, 3)


def test_auto_complete_needs_a_closing_signal() -> None:
    assert not should_auto_complete("practice", "Try it once more.", 8, 3)
    assert should_auto_complete("practice", "That's all for today. See you next time!", 8, 3)
    assert should_auto_complete("question", "今天就到这里，下次见！", 8, 3)


def test_farewell_needs_two_patterns() -> None:
    assert not has_farewell("加油")
    assert has_farewell("加油，下次见")
    assert not has_farewell("")


# --- repeat guard ---

SKILLS = {
    "mf.what_skills": "mindfulness",
    "mf.how_skills": "mindfulness",
    "dt.stop": "distress_tolerance",
    "dt.tipp": "distress_tolerance",
    "er.check_the_facts": "emotion_regulation",
}


def _out(skill: str, **kw: Any) -> dict[str, Any]:
    return {
        "selected_module": SKILLS[skill],
        "selected_skill": skill,
        "reason": "A good fit for today.",
        "skill_difficulty": "beginner",
        "alternative_skills": ["dt.stop", "er.check_the_facts"],
        "is_repeat": False,
        "repeat_justification": "",
        **kw,
    }


def _guard(out: dict[str, Any], ctx: SelectionContext, lang: str = "en") -> Any:
    return apply_repeat_guard(
        out, ctx, language=lang, skill_module=SKILLS, fallback=lambda avoid: "dt.tipp"
    )


def test_guard_keeps_a_fresh_skill() -> None:
    g = _guard(_out("mf.what_skills"), SelectionContext(recent_skills=["dt.tipp"]))
    assert g.action == "kept" and g.output["selected_skill"] == "mf.what_skills"


def test_guard_swaps_an_unjustified_recent_skill_for_the_first_fresh_alternative() -> None:
    ctx = SelectionContext(recent_skills=["mf.what_skills", "dt.stop"])
    g = _guard(_out("mf.what_skills"), ctx)
    assert g.action == "swapped_alternative"
    out = g.output
    assert out["selected_skill"] == "er.check_the_facts"  # dt.stop is recent too
    assert out["selected_module"] == "emotion_regulation"
    assert out["is_repeat"] is False and out["repeat_justification"] == ""
    assert "mf.what_skills" not in out["alternative_skills"]
    assert "practised lately" in out["reason"]  # authored, never about the old skill


def test_guard_without_safe_alternative_uses_the_fallback_not_the_repeat() -> None:
    ctx = SelectionContext(recent_skills=["mf.what_skills", "dt.stop", "er.check_the_facts"])
    g = _guard(_out("mf.what_skills"), ctx, lang="zh-CN")
    assert g.action == "swapped_fallback"
    assert g.output["selected_skill"] == "dt.tipp"
    assert "最近还没练过" in g.output["reason"]


def test_guard_allows_a_repeat_with_a_justification() -> None:
    ctx = SelectionContext(recent_skills=["mf.what_skills"])
    g = _guard(
        _out("mf.what_skills", is_repeat=True, repeat_justification="Worth another look."), ctx
    )
    assert g.action == "allowed_repeat" and g.output["selected_skill"] == "mf.what_skills"


def test_guard_rejects_is_repeat_without_a_justification() -> None:
    ctx = SelectionContext(recent_skills=["mf.what_skills"])
    g = _guard(_out("mf.what_skills", is_repeat=True, repeat_justification="  "), ctx)
    assert g.action == "swapped_alternative"


def test_guard_allows_a_below_mastery_skill_when_the_reason_reinforces_it() -> None:
    ctx = SelectionContext(recent_skills=["mf.what_skills"], weak_skills=["mf.what_skills"])
    g = _guard(_out("mf.what_skills", reason="Let's reinforce this one."), ctx)
    assert g.action == "allowed_repeat"
    assert g.output["is_repeat"] is True and g.output["repeat_justification"]


def test_guard_does_not_allow_reinforce_wording_for_a_mastered_skill() -> None:
    ctx = SelectionContext(recent_skills=["mf.what_skills"], weak_skills=[])
    g = _guard(_out("mf.what_skills", reason="Let's reinforce this one."), ctx)
    assert g.action == "swapped_alternative"


# --- tests: mastery and five-question budget ---------------------------------------------------


@pytest.mark.parametrize(("correct", "mastered"), [(5, True), (4, True), (3, False), (0, False)])
def test_mastery_at_four_of_five(correct: int, mastered: bool) -> None:
    assert is_mastered(correct) is mastered


def _q(n: int) -> dict[str, Any]:
    return {
        "scenario_text": f"Scenario {n}",
        "question_text": "Which fits?",
        "options": [f"a{n}", f"b{n}", f"c{n}", f"d{n}"],
        "correct_option": 0,
        "explanation": "Because.",
    }


@pytest.mark.parametrize("n", [4, 6])
def test_skill_test_must_have_exactly_five_questions(n: int) -> None:
    with pytest.raises(ValidationError):
        SkillTestOut.model_validate({"questions": [_q(i) for i in range(n)]})
    SkillTestOut.model_validate({"questions": [_q(i) for i in range(5)]})


# --- profile questionnaire ---


def _profile(**kw: Any) -> dict[str, Any]:
    return {"age": 15, "grade": "grade_9", **kw}


def test_profile_minimum_is_age_and_grade() -> None:
    p = ProfileIn.model_validate(_profile())
    assert p.gender is None and p.hobby_tags == [] and p.other_hobby_text is None


@pytest.mark.parametrize(
    "bad",
    [
        {"age": 9},
        {"age": 20},
        {"grade": "grade_6"},
        {"hobby_tags": ["skydiving"]},
        {"concern_tags": ["low_mood", "sleep", "worry", "anger", "focus", "exam_anxiety"]},
        {"concern_tags": ["prefer_not_to_say", "sleep"]},
        {"gender": "unknown"},
        {"other_hobby_text": "x" * 101},
        {"nickname": "Sam"},
    ],
)
def test_profile_rejects_bad_values(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProfileIn.model_validate(_profile(**bad))


def test_profile_dedupes_tags_and_trims_other_text() -> None:
    p = ProfileIn.model_validate(
        _profile(hobby_tags=["music", "music"], other_concern_text="   ", gender="other")
    )
    assert p.hobby_tags == ["music"] and p.other_concern_text is None
