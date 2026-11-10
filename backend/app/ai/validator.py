"""OutputValidator: repair -> alias remap -> value normalisation -> Pydantic validation
(Plan §5.4 pipeline; Phase 4 task 3). Adapted from DBT_Revised `knowledge_base/rag/validator.py`.

Changes from DBT_Revised: no regex field extraction as a last resort (a half-parsed answer is
worse than a fallback here); enum values the model writes in Chinese or in variant spellings
are normalised to the schema's English values; validation errors are summarised without echoing
model text. The caller decides about the single retry (Plan §5.4: retry <= 1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

# Canonical field -> names the model has been seen to use instead (from DBT_Revised, extended).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "content": ("response", "reply", "text", "answer", "body", "message"),
    "message_type": ("type", "msg_type", "kind"),
    "question": ("query", "ask", "follow_up_question"),
    "source_chunk_ids": ("sources", "chunk_ids", "references", "citations", "source_ids"),
    "selected_skill": ("skill", "skill_id", "skill_name", "recommended_skill"),
    "selected_module": ("module", "module_id"),
    "reason": ("rationale", "justification", "explanation"),
    "skill_difficulty": ("difficulty", "level", "difficulty_level"),
    "alternative_skills": ("alternatives", "backup_skills", "other_skills"),
    "is_repeat": ("repeat", "is_repeated"),
    "repeat_justification": ("repeat_reason", "why_repeat"),
    "understanding": ("student_understanding", "understanding_level"),
    "should_stop": ("should_stop_session", "stop_session", "halt_session"),
    "risk_level": ("level", "severity", "risk"),
    "categories": ("risk_type", "risk_types", "risk_categories"),
    "reasoning": ("risk_reasoning", "rationale"),
    "risk_reasoning": ("reasoning",),
    "scenario_text": ("scenario", "situation"),
    "question_text": ("question", "stem"),
    "correct_option": ("correct_index", "answer_index", "correct"),
    "correct_index": ("correct_option", "answer_index", "correct"),
    "stem": ("question_text", "question"),
    "everyday_example": ("example",),
    "check_question": ("question",),
    "plan_steps": ("steps",),
    "key_points": ("points", "keypoints"),
    "items": ("practice_items",),
    "questions": ("quiz", "test_questions"),
}

# Value normalisation for enum fields (DBT_Revised prompts used Chinese labels).
VALUE_MAP: dict[str, dict[str, str]] = {
    "message_type": {
        "练习": "practice",
        "示例": "example",
        "例子": "example",
        "提问": "question",
        "问题": "question",
        "反馈": "feedback",
        "讲解": "explanation",
        "解释": "explanation",
        "总结": "summary",
        "exercise": "practice",
    },
    "skill_difficulty": {"初级": "beginner", "中级": "intermediate", "高级": "advanced"},
    "test_difficulty": {"初级": "beginner", "中级": "intermediate", "高级": "advanced"},
    "understanding": {
        "良好": "good",
        "一般": "fair",
        "需要复习": "needs_review",
        "needs review": "needs_review",
    },
    "risk_level": {"无": "none", "低": "low", "中": "medium", "高": "high"},
    "confidence": {"高": "high", "中": "medium", "低": "low"},
    "grounding": {
        "手册": "manual",
        "manual-first": "manual",
        "通用": "general",
        "general knowledge": "general",
        "无": "none",
    },
    "answer_mode": {"选择": "choice", "multiple_choice": "choice", "text": "short_text"},
}

_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
# DeepSeek JSON mode occasionally emits a stray '#' before a value: {"ok":# true}
_STRAY_HASH = re.compile(r"(:\s*)#\s*")


class OutputInvalidError(ValueError):
    """The model's output could not be turned into a valid instance of the schema."""

    def __init__(self, code: str, summary: str) -> None:
        self.code = code  # "unparseable" | "schema"
        self.summary = summary[:500]
        super().__init__(f"{code}: {self.summary}")


@dataclass(frozen=True)
class Validated:
    model: BaseModel
    repaired: bool  # JSON repair or field/value remapping was needed


def parse_json(raw: str) -> tuple[dict[str, Any], bool]:
    """Parse a JSON object from model text; second value says whether repair was needed."""
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, False
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    elif start >= 0:
        text = text[start:] + "}"
    for candidate in (
        _TRAILING_COMMA.sub(r"\1", text),
        _TRAILING_COMMA.sub(r"\1", _STRAY_HASH.sub(r"\1", text)),
    ):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data, True
    raise OutputInvalidError("unparseable", "no JSON object could be parsed")


def _field_names(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields)


def remap(data: dict[str, Any], model: type[BaseModel]) -> tuple[dict[str, Any], bool]:
    """Rename alias keys to canonical names (only when the alias is not itself a field)."""
    fields = _field_names(model)
    out = dict(data)
    changed = False
    for name in fields:
        if name in out:
            continue
        for alias in FIELD_ALIASES.get(name, ()):
            if alias in out and alias not in fields:
                out[name] = out.pop(alias)
                changed = True
                break
    # Recurse into nested models (lists of objects).
    for name, info in model.model_fields.items():
        sub = _nested_model(info.annotation)
        if sub is not None and isinstance(out.get(name), list):
            items = []
            for item in out[name]:
                if isinstance(item, dict):
                    item, c = remap(item, sub)
                    changed |= c
                items.append(item)
            out[name] = items
    return out, changed


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    args = getattr(annotation, "__args__", ())
    for a in args:
        if isinstance(a, type) and issubclass(a, BaseModel):
            return a
    return None


def normalise_values(data: Any) -> tuple[Any, bool]:
    changed = False
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            if k in VALUE_MAP and isinstance(v, str):
                key = v.strip()
                mapped = VALUE_MAP[k].get(key) or VALUE_MAP[k].get(key.casefold())
                if mapped is None and key != key.casefold():
                    mapped = key.casefold() if key.casefold() in VALUE_MAP[k].values() else None
                if mapped is not None and mapped != v:
                    v, changed = mapped, True
            elif k == "categories" and isinstance(v, str):
                v, changed = ([v] if v else []), True
            else:
                v, c = normalise_values(v)
                changed |= c
            out[k] = v
        return out, changed
    if isinstance(data, list):
        items = []
        for v in data:
            v, c = normalise_values(v)
            changed |= c
            items.append(v)
        return items, changed
    return data, False


def summarise(exc: ValidationError) -> str:
    """Field paths and error types only; never the model's text."""
    parts = []
    for err in exc.errors()[:8]:
        loc = ".".join(str(x) for x in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['type']}")
    return "; ".join(parts)


def validate(raw: str | dict[str, Any], model: type[BaseModel]) -> Validated:
    if isinstance(raw, str):
        data, repaired = parse_json(raw)
    else:
        data, repaired = dict(raw), False
    try:
        return Validated(model.model_validate(data), repaired)
    except ValidationError:
        pass
    data, _ = remap(data, model)
    data, _ = normalise_values(data)
    try:
        return Validated(model.model_validate(data), True)
    except ValidationError as exc:
        raise OutputInvalidError("schema", summarise(exc)) from exc
