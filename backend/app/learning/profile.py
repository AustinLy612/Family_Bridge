"""Adolescent profile questionnaire (Plan §5.5.1 step 0).

Tag ids are stable internal ids; their zh-CN / en labels live in the frontend i18n files. The
lists start from DBT_Revised `questionnaire/forms.py` and need clinical review (O20).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Gender, LearnerProfile

HOBBY_TAGS: tuple[str, ...] = (
    "sports",
    "music",
    "art_craft",
    "reading",
    "writing",
    "anime_film",
    "games",
    "coding_tech",
    "science",
    "pets",
    "food_cooking",
    "travel_outdoors",
    "chatting_friends",
    "quiet_time",
)

CONCERN_TAGS: tuple[str, ...] = (
    "study_pressure",
    "exam_anxiety",
    "focus",
    "procrastination",
    "peer_relations",
    "lonely_left_out",
    "family_talk",
    "parent_conflict",
    "low_mood",
    "anger",
    "worry",
    "self_esteem",
    "sleep",
    "body_image",
    "phone_internet",
    "future_pressure",
    "teacher_talk",
    "bullying",
    "prefer_not_to_say",
)

GRADES: tuple[str, ...] = ("grade_7", "grade_8", "grade_9", "grade_10", "grade_11", "grade_12")
MAX_TAGS = 5
AGE_MIN, AGE_MAX = 10, 19  # matches the AI input schema (adolescents)
OTHER_MAX = 100


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gender: Gender | None = None
    age: int = Field(ge=AGE_MIN, le=AGE_MAX)
    grade: str
    hobby_tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    concern_tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    other_hobby_text: str | None = Field(default=None, max_length=OTHER_MAX)
    other_concern_text: str | None = Field(default=None, max_length=OTHER_MAX)

    @field_validator("grade")
    @classmethod
    def _grade(cls, v: str) -> str:
        if v not in GRADES:
            raise ValueError("unknown grade")
        return v

    @field_validator("hobby_tags")
    @classmethod
    def _hobbies(cls, v: list[str]) -> list[str]:
        return _tags(v, HOBBY_TAGS)

    @field_validator("concern_tags")
    @classmethod
    def _concerns(cls, v: list[str]) -> list[str]:
        out = _tags(v, CONCERN_TAGS)
        if "prefer_not_to_say" in out and len(out) > 1:
            raise ValueError("prefer_not_to_say cannot be combined with other concerns")
        return out

    @field_validator("other_hobby_text", "other_concern_text")
    @classmethod
    def _other(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


def _tags(values: list[str], allowed: tuple[str, ...]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v not in allowed:
            raise ValueError(f"unknown tag {v!r}")
        if v not in seen:
            seen.append(v)
    return seen


class ProfileOut(BaseModel):
    gender: Gender | None
    age: int
    grade: str
    hobby_tags: list[str]
    concern_tags: list[str]
    other_hobby_text: str | None
    other_concern_text: str | None

    @classmethod
    def of(cls, p: LearnerProfile) -> ProfileOut:
        return cls(
            gender=p.gender,
            age=p.age,
            grade=p.grade,
            hobby_tags=list(p.hobby_tags or []),
            concern_tags=list(p.concern_tags or []),
            other_hobby_text=p.other_hobby_text,
            other_concern_text=p.other_concern_text,
        )


class ProfileOptions(BaseModel):
    hobby_tags: list[str] = list(HOBBY_TAGS)
    concern_tags: list[str] = list(CONCERN_TAGS)
    grades: list[str] = list(GRADES)
    genders: list[str] = [g.value for g in Gender]
    max_tags: int = MAX_TAGS
    age_min: int = AGE_MIN
    age_max: int = AGE_MAX


def for_ai(p: LearnerProfile | None) -> dict[str, Any] | None:
    """The profile as the AI input schema expects it (ids only, plus the optional free text,
    which the AI service screens for injection like any other participant text)."""
    if p is None:
        return None
    return {
        "age": p.age,
        "grade": p.grade,
        "gender": p.gender.value if p.gender else None,
        "hobby_tags": list(p.hobby_tags or []),
        "concern_tags": [t for t in (p.concern_tags or []) if t != "prefer_not_to_say"],
        "other_hobby_text": p.other_hobby_text,
        "other_concern_text": p.other_concern_text,
    }
