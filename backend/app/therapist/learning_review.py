"""Therapist learning review and skill-mastery summaries (Plan §5.8; D15, D61).

The overview is built for low burden: per lesson it shows the skill, why it was chosen, the
AI summary, the internal understanding code, test attempts and mood before/after. It never
includes the participant's own words. Transcripts, check-in answers, practice answers and
reflections open only on demand, one lesson at a time, and every such read is audited.

The group coverage map shows which skills each participant has practised. It is not a ranking:
columns keep a fixed order (family, then alias) and there are no per-person totals.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.core.policy import audit_read
from app.learning.caregiver import quiz_outcome
from app.learning.progress import outcome_label
from app.learning.testing import outcome as test_outcome
from app.models import (
    CaregiverLesson,
    ChatMessage,
    Family,
    FamilyMember,
    Group,
    GroupSkillRecord,
    LessonStatus,
    MoodRecord,
    PracticeAttempt,
    QuizAttempt,
    Role,
    SkillProgress,
    SkillTest,
    TeachingSession,
    User,
)

Names = Callable[[str], tuple[str, str, str]]  # skill id -> (name, module id, module name)
LESSON_LIMIT = 50


def _json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        v = json.loads(text)
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _skill(names: Names, sid: str | None) -> dict[str, str] | None:
    if not sid:
        return None
    name, module_id, module_name = names(sid)
    return {"id": sid, "name": name, "module_id": module_id, "module": module_name}


def _moods(db: Session, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, int]:
    real = [i for i in ids if i is not None]
    if not real:
        return {}
    return {m.id: m.value for m in db.scalars(select(MoodRecord).where(MoodRecord.id.in_(real)))}


def mastery_rows(db: Session, user_id: uuid.UUID, names: Names) -> list[dict[str, Any]]:
    """Per skill: practised, test/quiz outcome and the practice rubric distribution."""
    out = []
    for p in db.scalars(
        select(SkillProgress)
        .where(SkillProgress.user_id == user_id)
        .order_by(SkillProgress.skill_id)
    ):
        out.append(
            {
                "skill": _skill(names, p.skill_id),
                "lessons_completed": p.lessons_completed,
                "outcome": outcome_label(p),
                "practice_categories": dict(p.practice_categories or {}),
                "last_practised_at": p.last_practised_at.isoformat(),
            }
        )
    return out


def _teaching_rows(db: Session, user: User, names: Names) -> list[dict[str, Any]]:
    sessions = list(
        db.scalars(
            select(TeachingSession)
            .where(TeachingSession.user_id == user.id)
            .order_by(TeachingSession.started_at.desc())
            .limit(LESSON_LIMIT)
        )
    )
    tests: dict[uuid.UUID, list[SkillTest]] = {}
    for t in db.scalars(
        select(SkillTest)
        .where(SkillTest.session_id.in_([s.id for s in sessions] or [uuid.UUID(int=0)]))
        .order_by(SkillTest.attempt_no)
    ):
        tests.setdefault(t.session_id, []).append(t)
    moods = _moods(
        db,
        [s.pre_mood_id for s in sessions]
        + [s.post_mood_id for s in sessions]
        + [t.post_mood_id for ts in tests.values() for t in ts],
    )
    rows = []
    for s in sessions:
        rec = _json(s.recommendation)
        summary = _json(s.summary)
        checkin = (
            "skipped" if s.checkin_skipped else "answered" if s.personal_context else "not_reached"
        )
        rows.append(
            {
                "id": str(s.id),
                "kind": "teaching",
                "skill": _skill(names, s.selected_skill),
                "source": s.source.value if s.source else None,
                "status": s.status.value,
                "started_at": s.started_at.isoformat(),
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "recommendation_reason": rec.get("reason") or None,
                "summary": {
                    "summary_text": summary.get("summary_text", ""),
                    "key_points": summary.get("key_points", []),
                }
                if summary
                else None,
                "understanding": s.understanding,
                "checkin": checkin,
                "turns": s.turns,
                "mood_before": moods.get(s.pre_mood_id) if s.pre_mood_id else None,
                "mood_after": moods.get(s.post_mood_id) if s.post_mood_id else None,
                "tests": [
                    {
                        "attempt_no": t.attempt_no,
                        "status": t.status.value,
                        "outcome": test_outcome(t),
                        "correct": t.correct_count,
                        "total": t.total_questions,
                        "mood_after": moods.get(t.post_mood_id) if t.post_mood_id else None,
                    }
                    for t in tests.get(s.id, [])
                ],
            }
        )
    return rows


def _caregiver_rows(db: Session, user: User, names: Names) -> list[dict[str, Any]]:
    lessons = list(
        db.scalars(
            select(CaregiverLesson)
            .where(CaregiverLesson.user_id == user.id)
            .order_by(CaregiverLesson.started_at.desc())
            .limit(LESSON_LIMIT)
        )
    )
    rows = []
    for c in lessons:
        categories: dict[str, int] = {}
        for cat in db.scalars(
            select(PracticeAttempt.category).where(PracticeAttempt.lesson_id == c.id)
        ):
            categories[cat] = categories.get(cat, 0) + 1
        quiz = list(db.scalars(select(QuizAttempt).where(QuizAttempt.lesson_id == c.id)))
        rows.append(
            {
                "id": str(c.id),
                "kind": "caregiver",
                "skill": _skill(names, c.skill_id),
                "source": c.source.value,
                "status": c.status.value,
                "step": c.step.value,
                "started_at": c.started_at.isoformat(),
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                "variant": c.variant,
                "practice_categories": categories,
                "quiz": {
                    "correct": sum(1 for q in quiz if q.is_correct),
                    "answered": len(quiz),
                    "outcome": quiz_outcome(db, c) if c.status is LessonStatus.completed else None,
                },
                "reflection": "skipped"
                if c.reflection_skipped
                else "written"
                if c.reflection
                else "not_reached",
            }
        )
    return rows


def _members(db: Session, family: Family) -> list[FamilyMember]:
    members = [
        m
        for m in db.scalars(select(FamilyMember).where(FamilyMember.family_id == family.id))
        if m.member_role in (Role.adolescent, Role.caregiver)
    ]
    members.sort(key=lambda m: (m.member_role is not Role.adolescent, m.user.display_alias))
    return members


def family_learning(db: Session, therapist: User, family: Family, names: Names) -> dict[str, Any]:
    panels = []
    for m in _members(db, family):
        u = m.user
        lessons = (
            _teaching_rows(db, u, names)
            if m.member_role is Role.adolescent
            else _caregiver_rows(db, u, names)
        )
        panels.append(
            {
                "user_id": str(u.id),
                "alias": u.display_alias,
                "role": m.member_role.value,
                "lessons": lessons,
                "mastery": mastery_rows(db, u.id, names),
            }
        )
        audit_read(db, therapist, "learning.review", target_type="user", target_id=u.id)
    return {"participants": panels}


def _lesson_in_family(
    db: Session, family: Family, lesson_id: uuid.UUID
) -> TeachingSession | CaregiverLesson:
    member_ids = {m.user_id for m in _members(db, family)}
    lesson: TeachingSession | CaregiverLesson | None = db.get(TeachingSession, lesson_id)
    if lesson is None:
        lesson = db.get(CaregiverLesson, lesson_id)
    if lesson is None or lesson.user_id not in member_ids:
        raise not_found()
    return lesson


def lesson_detail(
    db: Session, therapist: User, family: Family, lesson_id: uuid.UUID
) -> dict[str, Any]:
    """The participant's own words for one lesson, on demand (audited)."""
    lesson = _lesson_in_family(db, family, lesson_id)
    if isinstance(lesson, TeachingSession):
        inquiry = _json(lesson.inquiry)
        out: dict[str, Any] = {
            "kind": "teaching",
            "checkin": {
                "question": inquiry.get("question", ""),
                "answer": lesson.personal_context,
                "skipped": lesson.checkin_skipped,
            }
            if inquiry
            else None,
            "messages": [
                {"role": m.role.value, "content": m.content, "at": m.created_at.isoformat()}
                for m in db.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == lesson.id)
                    .order_by(ChatMessage.seq)
                )
            ],
            "mood_notes": [
                {"kind": r.kind.value, "value": r.value, "note": r.note}
                for r in db.scalars(
                    select(MoodRecord)
                    .where(MoodRecord.session_id == lesson.id)
                    .order_by(MoodRecord.created_at)
                )
                if r.note
            ],
        }
    else:
        out = {
            "kind": "caregiver",
            "practice": [
                {
                    "item": a.item_index + 1,
                    "attempt_no": a.attempt_no,
                    "answer": a.answer,
                    "category": a.category,
                }
                for a in db.scalars(
                    select(PracticeAttempt)
                    .where(PracticeAttempt.lesson_id == lesson.id)
                    .order_by(PracticeAttempt.item_index, PracticeAttempt.attempt_no)
                )
            ],
            "reflection": lesson.reflection,
        }
    audit_read(
        db,
        therapist,
        "learning.transcript.read",
        target_type="lesson",
        target_id=lesson.id,
        subject=str(lesson.user_id),
    )
    return out


def group_coverage(db: Session, therapist: User, group: Group, names: Names) -> dict[str, Any]:
    """Skill x participant map of practice (not a ranking; no totals per person)."""
    members = list(
        db.execute(
            select(FamilyMember, Family.label, User)
            .join(Family, Family.id == FamilyMember.family_id)
            .join(User, User.id == FamilyMember.user_id)
            .where(Family.group_id == group.id)
            .order_by(Family.created_at, FamilyMember.member_role, User.display_alias)
        ).all()
    )
    people = [
        {
            "user_id": str(u.id),
            "family_id": str(m.family_id),
            "family": label,
            "alias": u.display_alias,
            "role": m.member_role.value,
        }
        for m, label, u in members
        if m.member_role in (Role.adolescent, Role.caregiver)
    ]
    ids = [uuid.UUID(p["user_id"]) for p in people]
    cells: dict[str, dict[str, dict[str, Any]]] = {}
    for p in db.scalars(
        select(SkillProgress).where(SkillProgress.user_id.in_(ids or [uuid.UUID(int=0)]))
    ):
        cells.setdefault(p.skill_id, {})[str(p.user_id)] = {
            "lessons": p.lessons_completed,
            "outcome": outcome_label(p),
        }
    covered = sorted(
        {
            sid
            for r in db.scalars(
                select(GroupSkillRecord).where(GroupSkillRecord.group_id == group.id)
            )
            for sid in r.skill_ids
        }
    )
    audit_read(db, therapist, "learning.coverage", target_type="group", target_id=group.id)
    return {
        "participants": people,
        "cells": cells,
        "group_session_skills": covered,
    }
