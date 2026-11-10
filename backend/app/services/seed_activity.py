"""Phase 7 and 8 demo activity for the usability walkthrough (Plan §7.4): a diary expectation, group
homework, a group-session skill record and a few fictional diary entries, so a therapist can
review a family straight after seeding. Fictional values only. Idempotent: does nothing if the
demo group already has homework.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.diary.entries import site_today
from app.joint.engine import new_state
from app.models import (
    DiaryEntry,
    DiaryRevision,
    DyadSuitability,
    FamilyMember,
    Group,
    GroupSkillRecord,
    JointSession,
    Role,
    SessionStatus,
    Suitability,
    Task,
    TaskCompletion,
    User,
)

# (days ago, values) - fictional
TEEN_A_DAYS: list[tuple[int, dict[str, object]]] = [
    (3, {"sad": 6, "anxious": 7, "calm": 3, "self_harm_urge": 2, "suicide_urge": 1}),
    (2, {"sad": 5, "anxious": 6, "calm": 4, "self_harm_urge": 2, "suicide_urge": 1}),
    (
        1,
        {
            "sad": 4,
            "anxious": 4,
            "calm": 6,
            "self_harm_urge": 1,
            "suicide_urge": 1,
            "skill_used": True,
            "skills_used": ["dt.tipp"],
            "skill_helpful": 7,
        },
    ),
]
CARER_A_DAYS: list[tuple[int, dict[str, object]]] = [
    (2, {"sad": 4, "anxious": 6, "validating": "sometimes"})
]


def _entry(db: Session, user: User, day_offset: int, values: dict[str, object]) -> DiaryEntry:
    day = site_today(db) - timedelta(days=day_offset)
    e = DiaryEntry(
        id=uuid.uuid4(),
        user_id=user.id,
        role=user.role,
        template_version=1,
        entry_date=day,
        values_json=json.dumps(values, sort_keys=True),
        note=None,
        is_late=False,
        revision_no=1,
    )
    db.add(e)
    db.flush()
    db.add(
        DiaryRevision(
            entry_id=e.id,
            revision_no=1,
            entry_date=day,
            values_json=e.values_json,
            note=None,
            saved_by=user.id,
        )
    )
    return e


def seed_joint(db: Session) -> bool:
    """Phase 8: Family A's pair is suitable for joint work and has one open demo invitation for
    the stub episode (fictional; `demo` episodes are for demo families only). Idempotent."""
    users = {
        u.username: u
        for u in db.scalars(
            select(User).where(User.username.in_(["demo-therapist", "demo-teen-a", "demo-carer-a"]))
        )
    }
    teen, carer = users["demo-teen-a"], users["demo-carer-a"]
    if db.execute(
        select(DyadSuitability.id).where(
            DyadSuitability.adolescent_id == teen.id, DyadSuitability.caregiver_id == carer.id
        )
    ).first():
        return False
    member = db.execute(select(FamilyMember).where(FamilyMember.user_id == teen.id)).scalar_one()
    therapist = users["demo-therapist"]
    now = datetime.now(UTC)
    db.add(
        DyadSuitability(
            family_id=member.family_id,
            adolescent_id=teen.id,
            caregiver_id=carer.id,
            decision=Suitability.suitable,
            note="(demo) Fictional suitability for the walkthrough.",
            decided_by=therapist.id,
            decided_at=now,
        )
    )
    db.add(
        JointSession(
            family_id=member.family_id,
            mode="joint",
            adolescent_id=teen.id,
            caregiver_id=carer.id,
            episode_id="demo-stub-episode",
            episode_version=1,
            opens_at=now - timedelta(hours=1),
            closes_at=now + timedelta(days=7),
            status=SessionStatus.invited,
            snapshot=new_state(["adolescent", "caregiver"]),
            created_by=therapist.id,
        )
    )
    db.flush()
    audit.record(
        db, "seed.demo_joint", actor=therapist, target_type="family", target_id=member.family_id
    )
    return True


def seed_activity(db: Session) -> bool:
    group = db.execute(select(Group).where(Group.name == "Demo DBT-A group")).scalar_one_or_none()
    if group is None:
        raise RuntimeError("run seed-demo first (no demo group)")
    joint_added = seed_joint(db)
    if db.execute(select(Task.id).where(Task.group_id == group.id)).first():
        return joint_added
    users = {
        u.username: u
        for u in db.scalars(
            select(User).where(User.username.in_(["demo-therapist", "demo-teen-a", "demo-carer-a"]))
        )
    }
    therapist = users["demo-therapist"]
    today = site_today(db)
    group.diary_days_per_week = 5
    db.add(
        GroupSkillRecord(
            group_id=group.id,
            session_date=today - timedelta(days=4),
            skill_ids=["dt.tipp", "ie.dear_man"],
            note="(demo) First distress-tolerance session.",
            created_by=therapist.id,
        )
    )
    tipp = Task(
        group_id=group.id,
        kind="homework",
        for_roles=[Role.adolescent.value],
        title="Try TIPP once when stress is high (demo)",
        details="Notice how your body feels before and after.",
        skill_ids=["dt.tipp"],
        starts_on=today - timedelta(days=4),
        due_on=today + timedelta(days=3),
        created_by=therapist.id,
    )
    validate = Task(
        group_id=group.id,
        kind="homework",
        for_roles=[Role.adolescent.value, Role.caregiver.value],
        title="Notice one moment of validation at home (demo)",
        details=None,
        skill_ids=["wmp.validating_others"],
        starts_on=today - timedelta(days=4),
        due_on=today + timedelta(days=3),
        created_by=therapist.id,
    )
    db.add_all([tipp, validate])
    db.flush()
    teen, carer = users["demo-teen-a"], users["demo-carer-a"]
    last = None
    for offset, values in TEEN_A_DAYS:
        last = _entry(db, teen, offset, values)
    for offset, values in CARER_A_DAYS:
        _entry(db, carer, offset, values)
    assert last is not None
    db.add(
        TaskCompletion(
            task_id=tipp.id, user_id=teen.id, entry_id=last.id, completed_on=last.entry_date
        )
    )
    db.flush()
    audit.record(db, "seed.demo_activity", actor=therapist, target_type="group", target_id=group.id)
    return True
