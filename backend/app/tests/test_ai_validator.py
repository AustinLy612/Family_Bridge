"""OutputValidator (Plan §5.4): JSON repair, alias remap, value normalisation, schema errors."""

from __future__ import annotations

import json

import pytest

from app.ai.schemas import (
    FUNCTIONS,
    SERVER_FIELDS,
    AssessRiskOut,
    HintOut,
    SelectSkillOut,
    SkillTestOut,
    TeachingMessageOut,
)
from app.ai.validator import OutputInvalidError, parse_json, validate

HINT = {"hint": "Try naming the feeling first.", "source_chunk_ids": [], "grounding": "general"}


def test_clean_json_is_not_marked_repaired() -> None:
    v = validate(json.dumps(HINT), HintOut)
    assert not v.repaired and v.model.hint.startswith("Try")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n" + json.dumps(HINT) + "\n```",
        "Here you go: " + json.dumps(HINT) + " hope it helps",
        json.dumps(HINT)[:-1] + ",}",
        '{"hint": "x", "grounding":# "general"}',
        json.dumps(HINT)[:-1],  # missing closing brace
    ],
)
def test_repairs_common_json_damage(raw: str) -> None:
    data, repaired = parse_json(raw)
    assert repaired and "hint" in data


def test_unparseable_output_raises_without_echoing_text() -> None:
    with pytest.raises(OutputInvalidError) as e:
        validate("SECRET-MODEL-TEXT no json here", HintOut)
    assert e.value.code == "unparseable" and "SECRET" not in str(e.value)


def test_aliases_and_chinese_enum_values_are_normalised() -> None:
    raw = {
        "type": "练习",
        "response": "先慢慢呼吸三次。",
        "question": "你注意到了什么？",
        "sources": ["S1"],
        "grounding": "手册",
        "confidence": "中",
        "risk_level": "无",
        "should_stop": False,
    }
    v = validate(raw, TeachingMessageOut)
    m = v.model
    assert v.repaired
    assert m.message_type == "practice" and m.content.startswith("先")  # type: ignore[attr-defined]
    assert m.source_chunk_ids == ["S1"] and m.grounding == "manual"  # type: ignore[attr-defined]


def test_risk_type_string_becomes_categories() -> None:
    v = validate(
        {"level": "高", "risk_type": "self_harm", "should_stop": True, "reasoning": "r"},
        AssessRiskOut,
    )
    assert v.model.risk_level == "high" and v.model.categories == ["self_harm"]  # type: ignore[attr-defined]


def test_schema_errors_list_fields_not_values() -> None:
    with pytest.raises(OutputInvalidError) as e:
        validate({"hint": "PRIVATE " * 80, "grounding": "manual"}, HintOut)
    assert e.value.code == "schema" and "hint" in e.value.summary
    assert "PRIVATE" not in e.value.summary


def test_select_skill_repeat_needs_justification() -> None:
    base = {
        "selected_module": "distress_tolerance",
        "selected_skill": "dt.tipp",
        "reason": "r",
        "skill_difficulty": "beginner",
        "alternative_skills": ["dt.stop", "dt.accepts"],
        "grounding": "general",
    }
    with pytest.raises(OutputInvalidError):
        validate({**base, "is_repeat": True}, SelectSkillOut)
    assert validate({**base, "is_repeat": True, "repeat_justification": "j"}, SelectSkillOut)


def test_skill_test_needs_exactly_five_questions() -> None:
    q = {
        "scenario_text": "s",
        "question_text": "q",
        "options": ["apple", "river", "cloud", "stone"],
        "correct_option": 0,
        "explanation": "e",
    }
    with pytest.raises(OutputInvalidError):
        validate({"questions": [q] * 4, "grounding": "general"}, SkillTestOut)
    assert validate({"questions": [q] * 5, "grounding": "general"}, SkillTestOut)


def test_length_limits_reject_overlong_fields() -> None:
    with pytest.raises(OutputInvalidError):
        validate({**HINT, "hint": "x" * 201}, HintOut)


def test_language_is_server_set_and_every_function_has_specs() -> None:
    assert {"language"} == SERVER_FIELDS
    for spec in FUNCTIONS.values():
        assert spec.roles and spec.max_tokens > 0
        assert "language" not in spec.input.model_fields
