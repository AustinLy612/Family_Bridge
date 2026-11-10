"""Non-competitive progress (Plan §5.13) and the participant's own lesson history (D57).

`SkillProgress` only ever grows. Participants see which skills they have practised, how often
and when; for adolescents' tests and caregivers' quick checks they see "understood" or "worth
revisiting", never a score, rank, streak or badge. Nothing here is compared across people.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.sessions import utcnow
from app.models import CaregiverLesson, LessonStatus, SkillProgress, TeachingSession


def _row(db: Session, user_id: uuid.UUID, skill_id: str) -> SkillProgress:
    now = utcnow()
    db.execute(
        insert(SkillProgress)
        .values(
            user_id=user_id,
            skill_id=skill_id,
            lessons_completed=0,
            practice_categories={},
            first_practised_at=now,
            last_practised_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "skill_id"])
    )
    row = db.get(SkillProgress, (user_id, skill_id), populate_existing=True)
    assert row is not None
    return row


def record_lesson_completed(db: Session, user_id: uuid.UUID, skill_id: str) -> None:
    row = _row(db, user_id, skill_id)
    row.lessons_completed += 1
    row.last_practised_at = utcnow()


def record_test(db: Session, user_id: uuid.UUID, skill_id: str, mastered: bool) -> None:
    row = _row(db, user_id, skill_id)
    row.mastered = mastered
    row.last_practised_at = utcnow()


def record_caregiver_lesson(
    db: Session,
    user_id: uuid.UUID,
    skill_id: str,
    *,
    quiz_outcome: str,
    categories: list[str],
) -> None:
    row = _row(db, user_id, skill_id)
    row.lessons_completed += 1
    row.quiz_outcome = quiz_outcome
    counts = dict(row.practice_categories or {})
    for c in categories:
        counts[c] = counts.get(c, 0) + 1
    row.practice_categories = counts
    row.last_practised_at = utcnow()


def outcome_label(p: SkillProgress) -> str:
    """practised | understood | worth_revisiting (the only wording participants see)."""
    if p.quiz_outcome in ("understood", "worth_revisiting"):
        return p.quiz_outcome
    if p.mastered is True:
        return "understood"
    if p.mastered is False:
        return "worth_revisiting"
    return "practised"


def progress_view(db: Session, user_id: uuid.UUID, names: Any) -> list[dict[str, Any]]:
    """`names(skill_id) -> (skill name, module id, module name)`."""
    rows = db.scalars(
        select(SkillProgress)
        .where(SkillProgress.user_id == user_id)
        .order_by(SkillProgress.last_practised_at.desc())
    )
    out = []
    for p in rows:
        name, module_id, module_name = names(p.skill_id)
        out.append(
            {
                "skill": {"id": p.skill_id, "name": name, "module": module_name},
                "module_id": module_id,
                "lessons_completed": p.lessons_completed,
                "outcome": outcome_label(p),
                "first_practised_at": p.first_practised_at.isoformat(),
                "last_practised_at": p.last_practised_at.isoformat(),
            }
        )
    return out


def history_view(db: Session, user_id: uuid.UUID, names: Any) -> list[dict[str, Any]]:
    """The participant's own finished and stopped lessons (D57). Both engines; newest first."""
    items: list[dict[str, Any]] = []
    for s in db.scalars(
        select(TeachingSession)
        .where(TeachingSession.user_id == user_id, TeachingSession.status != LessonStatus.ongoing)
        .order_by(TeachingSession.started_at.desc())
        .limit(100)
    ):
        if not s.selected_skill:
            continue
        name, _, module_name = names(s.selected_skill)
        items.append(
            {
                "kind": "teaching",
                "id": str(s.id),
                "skill": {"id": s.selected_skill, "name": name, "module": module_name},
                "status": s.status.value,
                "source": s.source.value if s.source else None,
                "started_at": s.started_at.isoformat(),
            }
        )
    for c in db.scalars(
        select(CaregiverLesson)
        .where(CaregiverLesson.user_id == user_id, CaregiverLesson.status != LessonStatus.ongoing)
        .order_by(CaregiverLesson.started_at.desc())
        .limit(100)
    ):
        name, _, module_name = names(c.skill_id)
        items.append(
            {
                "kind": "caregiver",
                "id": str(c.id),
                "skill": {"id": c.skill_id, "name": name, "module": module_name},
                "status": c.status.value,
                "source": c.source.value,
                "started_at": c.started_at.isoformat(),
            }
        )
    items.sort(key=lambda i: i["started_at"], reverse=True)
    return items
