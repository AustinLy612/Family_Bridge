"""Skill selection context and the repeat guard (Plan §5.5.1 step 3; ported from DBT_Revised
`teaching/services.py` `_build_selection_context` / `_apply_repeat_guard`).

FamilyBridge differences:
- skills are taxonomy ids (the AI service already rejects ids outside the taxonomy);
- with no safe alternative the guard uses the deterministic fallback choice instead of keeping
  the unjustified repeat (DBT_Revised kept the original);
- the participant-facing reason is replaced with authored text when the skill is swapped, so it
  never describes a different skill.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LessonStatus, SkillTest, SkillTestStatus, TeachingSession
from app.settings import get_settings

HISTORY_LIMIT = 20  # last 20 lessons and last 20 tests (DBT_Revised)
REINFORCE_TOKENS = (
    "未通过",
    "薄弱",
    "巩固",
    "复训",
    "未掌握",
    "再练",
    "failed",
    "not mastered",
    "needs practice",
    "repeat",
    "reinforce",
    "revisit",
)

SWAPPED_REASON = {
    "zh-CN": "这是一个你最近还没练过的技能，换个角度练一练也很有帮助。",
    "en": "This is a skill you haven't practised lately; a fresh angle can help too.",
}
REPEAT_REASON = {
    "zh-CN": "上次的练习还可以再巩固一下，我们换个方式再练一次。",
    "en": "Last time's practice is worth another look, so we'll try it again a different way.",
}


@dataclass
class SelectionContext:
    history_skills: list[str] = field(default_factory=list)  # newest first, may repeat
    recent_skills: list[str] = field(default_factory=list)  # last 3 taught, newest first
    weak_skills: list[str] = field(default_factory=list)  # latest test below mastery


def counts_as_taught(s: TeachingSession) -> bool:
    """A lesson counts once teaching actually happened (DBT_Revised `counts_as_taught`)."""
    return bool(s.selected_skill) and (s.status is LessonStatus.completed or s.turns > 0)


def build_context(
    db: Session, user_id: uuid.UUID, *, exclude: uuid.UUID | None = None
) -> SelectionContext:
    sessions = list(
        db.scalars(
            select(TeachingSession)
            .where(TeachingSession.user_id == user_id)
            .order_by(TeachingSession.started_at.desc())
            .limit(HISTORY_LIMIT + 1)
        )
    )
    taught = [s for s in sessions if s.id != exclude and counts_as_taught(s)][:HISTORY_LIMIT]
    history = [str(s.selected_skill) for s in taught]
    recent: list[str] = []
    for sid in history:
        if sid not in recent:
            recent.append(sid)
        if len(recent) == get_settings().skill_repeat_window:
            break
    tests = list(
        db.execute(
            select(SkillTest, TeachingSession.selected_skill)
            .join(TeachingSession, TeachingSession.id == SkillTest.session_id)
            .where(SkillTest.user_id == user_id, SkillTest.status == SkillTestStatus.completed)
            .order_by(SkillTest.completed_at.desc())
            .limit(HISTORY_LIMIT)
        ).all()
    )
    latest: dict[str, bool] = {}
    for test, skill in tests:
        if skill and skill not in latest:
            latest[skill] = bool(test.mastered)
    weak = [s for s, mastered in latest.items() if not mastered]
    return SelectionContext(history, recent, weak)


@dataclass(frozen=True)
class GuardResult:
    output: dict[str, Any]
    action: str  # "kept" | "allowed_repeat" | "swapped_alternative" | "swapped_fallback"


def apply_repeat_guard(
    output: dict[str, Any],
    ctx: SelectionContext,
    *,
    language: str,
    skill_module: dict[str, str],
    fallback: Callable[[Sequence[str]], str],
) -> GuardResult:
    """Block unjustified repeats of the last 3 taught skills.

    Allowed: `is_repeat` with a non-empty justification, or a below-mastery skill whose reason
    asks to reinforce it. Otherwise: first alternative that is not recent; else the
    deterministic fallback (`fallback(avoid)` returns a taxonomy id).
    """
    out = dict(output)
    selected = str(out.get("selected_skill") or "")
    avoid = set(ctx.recent_skills)
    if not selected or selected not in avoid:
        return GuardResult(out, "kept")

    justification = str(out.get("repeat_justification") or "").strip()
    valid = bool(out.get("is_repeat")) and bool(justification)
    if not valid and selected in ctx.weak_skills:
        reason = str(out.get("reason") or "").casefold()
        if any(tok in reason for tok in REINFORCE_TOKENS):
            justification = justification or REPEAT_REASON.get(language, REPEAT_REASON["en"])
            valid = True
    if valid:
        out["is_repeat"] = True
        out["repeat_justification"] = justification
        return GuardResult(out, "allowed_repeat")

    alternatives = [
        str(a)
        for a in out.get("alternative_skills") or []
        if str(a) not in avoid and str(a) != selected and str(a) in skill_module
    ]
    if alternatives:
        pick, action = alternatives[0], "swapped_alternative"
    else:
        pick, action = fallback(sorted(avoid)), "swapped_fallback"
    # The recent skill is not offered again as an alternative.
    rest = [a for a in out.get("alternative_skills") or [] if a != pick and a not in avoid]
    out.update(
        selected_skill=pick,
        selected_module=skill_module.get(pick, out.get("selected_module")),
        reason=SWAPPED_REASON.get(language, SWAPPED_REASON["en"]),
        is_repeat=False,
        repeat_justification="",
        alternative_skills=rest[:3],
    )
    return GuardResult(out, action)
