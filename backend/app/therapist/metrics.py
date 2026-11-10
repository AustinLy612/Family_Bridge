"""Feasibility indicators for a therapist's own group (Plan §5.8 "Metrics", §5.10).

Counts and rates only: no free text, no per-person ranking. Joint-mode indicators arrive with
Phase 8 and the full research event stream with Phase 9.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.diary.entries import site_today
from app.diary.sharing import expected_days
from app.models import (
    CaregiverLesson,
    CodePurpose,
    DiaryEntry,
    Family,
    FamilyMember,
    Group,
    Invitation,
    LessonStatus,
    MoodRecord,
    Role,
    SafetyEvent,
    Site,
    SkillTest,
    SkillTestStatus,
    Task,
    TaskCompletion,
    TeachingSession,
    TherapistTime,
    User,
)
from app.models.learning import QuizAttempt

WINDOWS = (7, 28, 90)


def _start_utc(db: Session, first: date) -> datetime:
    site = db.execute(select(Site).limit(1)).scalar_one_or_none()
    tz = ZoneInfo(site.timezone if site else "UTC")
    return datetime.combine(first, time.min, tzinfo=tz)


def _round(v: float | None, n: int = 1) -> float | None:
    return round(v, n) if v is not None else None


def group_metrics(db: Session, group: Group, days: int, sla_hours: int) -> dict[str, Any]:
    if days not in WINDOWS:
        raise bad_request("metrics.invalid_range")
    today = site_today(db)
    first = today - timedelta(days=days - 1)
    since = _start_utc(db, first)

    families = list(db.scalars(select(Family).where(Family.group_id == group.id)))
    family_ids = [f.id for f in families] or [uuid.UUID(int=0)]
    members = list(
        db.execute(
            select(FamilyMember, User)
            .join(User, User.id == FamilyMember.user_id)
            .where(FamilyMember.family_id.in_(family_ids))
        ).all()
    )
    by_role: dict[Role, list[User]] = {Role.adolescent: [], Role.caregiver: []}
    for m, u in members:
        if m.member_role in by_role:
            by_role[m.member_role].append(u)
    all_ids = [u.id for us in by_role.values() for u in us] or [uuid.UUID(int=0)]

    # --- enrolment ---
    invites = list(
        db.scalars(
            select(Invitation).where(
                Invitation.family_id.in_(family_ids), Invitation.purpose == CodePurpose.invite
            )
        )
    )
    enrolment = {
        "families": len(families),
        "invitations_issued": len(invites),
        "invitations_redeemed": sum(1 for i in invites if i.used_at is not None),
        "by_role": {
            r.value: {
                "members": len(us),
                "onboarded": sum(1 for u in us if u.onboarded_at is not None),
            }
            for r, us in by_role.items()
        },
    }

    # --- diary (D70 expectation) ---
    per_week = group.diary_days_per_week
    diary: dict[str, Any] = {"days_per_week": per_week}
    for r, us in by_role.items():
        ids = [u.id for u in us if u.onboarded_at is not None]
        rows = (
            list(
                db.scalars(
                    select(DiaryEntry).where(
                        DiaryEntry.user_id.in_(ids), DiaryEntry.entry_date >= first
                    )
                )
            )
            if ids
            else []
        )
        diary[r.value] = {
            "participants": len(ids),
            "expected_days": expected_days(days, per_week) * len(ids),
            "days_with_entries": len({(e.user_id, e.entry_date) for e in rows}),
            "entries": len(rows),
            "added_later": sum(1 for e in rows if e.is_late),
            "corrected": sum(1 for e in rows if e.revision_no > 1),
        }

    # --- homework ---
    tasks = list(
        db.scalars(
            select(Task).where(
                Task.group_id == group.id,
                Task.archived_at.is_(None),
                Task.starts_on <= today,
                Task.due_on >= first,
            )
        )
    )
    done = set(
        db.execute(
            select(TaskCompletion.task_id, TaskCompletion.user_id).where(
                TaskCompletion.task_id.in_([t.id for t in tasks] or [uuid.UUID(int=0)])
            )
        ).all()
    )
    pairs = [
        (t.id, u.id)
        for t in tasks
        for r, us in by_role.items()
        if r.value in t.for_roles
        for u in us
        if u.onboarded_at is not None
    ]
    homework = {
        "tasks": len(tasks),
        "assigned": len(pairs),
        "done": sum(1 for p in pairs if p in done),
    }

    # --- learning ---
    sessions = list(
        db.scalars(
            select(TeachingSession).where(
                TeachingSession.user_id.in_(all_ids), TeachingSession.started_at >= since
            )
        )
    )
    mood_ids = [s.pre_mood_id for s in sessions if s.pre_mood_id] + [
        s.post_mood_id for s in sessions if s.post_mood_id
    ]
    moods = (
        dict(
            db.execute(
                select(MoodRecord.id, MoodRecord.value).where(MoodRecord.id.in_(mood_ids))
            ).all()
        )
        if mood_ids
        else {}
    )
    pre = [moods[s.pre_mood_id] for s in sessions if s.pre_mood_id in moods]
    post = [moods[s.post_mood_id] for s in sessions if s.post_mood_id in moods]
    tests = list(
        db.scalars(
            select(SkillTest).where(SkillTest.user_id.in_(all_ids), SkillTest.created_at >= since)
        )
    )
    lessons = list(
        db.scalars(
            select(CaregiverLesson).where(
                CaregiverLesson.user_id.in_(all_ids), CaregiverLesson.started_at >= since
            )
        )
    )
    quiz_rows = (
        list(
            db.scalars(
                select(QuizAttempt).where(QuizAttempt.lesson_id.in_([c.id for c in lessons]))
            )
        )
        if lessons
        else []
    )
    adolescent = {
        "started": len(sessions),
        "completed": sum(1 for s in sessions if s.status is LessonStatus.completed),
        "stopped": sum(1 for s in sessions if s.status is LessonStatus.user_terminated),
        "stopped_by_safety": sum(1 for s in sessions if s.status is LessonStatus.stopped_by_safety),
        "by_source": dict(Counter(s.source.value for s in sessions if s.source)),
        "checkin_answered": sum(1 for s in sessions if s.personal_context),
        "checkin_skipped": sum(1 for s in sessions if s.checkin_skipped),
        "test_attempts": sum(1 for t in tests if t.status is SkillTestStatus.completed),
        "tests_mastered": sum(
            1 for t in tests if t.status is SkillTestStatus.completed and t.mastered
        ),
        "mood_before_mean": _round(mean(pre) if pre else None),
        "mood_after_mean": _round(mean(post) if post else None),
    }
    caregiver = {
        "started": len(lessons),
        "completed": sum(1 for c in lessons if c.status is LessonStatus.completed),
        "stopped": sum(1 for c in lessons if c.status is LessonStatus.user_terminated),
        "by_source": dict(Counter(c.source.value for c in lessons)),
        "quiz_answers": len(quiz_rows),
        "quiz_correct": sum(1 for q in quiz_rows if q.is_correct),
    }

    # --- safety ---
    events = list(
        db.scalars(
            select(SafetyEvent).where(
                SafetyEvent.family_id.in_(family_ids), SafetyEvent.created_at >= since
            )
        )
    )
    ack_delays = [e.acknowledged_at - e.created_at for e in events if e.acknowledged_at]
    sla = timedelta(hours=sla_hours)
    open_now = db.scalar(
        select(func.count())
        .select_from(SafetyEvent)
        .where(SafetyEvent.family_id.in_(family_ids), SafetyEvent.resolved_at.is_(None))
    )
    safety = {
        "events": len(events),
        "by_category": dict(Counter(e.category.value for e in events)),
        "acknowledged_within_sla": sum(1 for d in ack_delays if d <= sla),
        "acknowledged": len(ack_delays),
        "open_now": int(open_now or 0),
        "sla_hours": sla_hours,
    }

    # --- therapist time per family (§8.4) ---
    seconds = dict(
        db.execute(
            select(TherapistTime.family_id, func.sum(TherapistTime.seconds))
            .where(TherapistTime.family_id.in_(family_ids), TherapistTime.day >= first)
            .group_by(TherapistTime.family_id)
        ).all()
    )
    per_family = [
        {
            "family_id": str(f.id),
            "family": f.label,
            "minutes": round((seconds.get(f.id) or 0) / 60, 1),
        }
        for f in sorted(families, key=lambda f: f.created_at)
    ]
    minutes = [round((seconds.get(f.id) or 0) / 60, 1) for f in families]
    therapist_time = {
        "families": per_family,
        "median_minutes": _round(median(minutes) if minutes else None),
    }

    return {
        "group": {"id": str(group.id), "name": group.name},
        "from": first.isoformat(),
        "to": today.isoformat(),
        "days": days,
        "enrolment": enrolment,
        "diary": diary,
        "homework": homework,
        "learning": {"adolescent": adolescent, "caregiver": caregiver},
        "safety": safety,
        "therapist_time": therapist_time,
    }
