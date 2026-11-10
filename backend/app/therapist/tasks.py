"""Group homework and diary expectations (Plan §5.8 "Tasks & scheduling", §5.6; D69, D70).

Homework is a `Task` for one or both participant roles with a due window. Participants tick it
in the diary card's Homework checklist; Home lists this week's items read-only. There is no
overdue state and no negative copy: an item is either "done" or simply still listed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import bad_request, not_found
from app.core.policy import ensure_group
from app.core.sessions import utcnow
from app.models import (
    DiaryEntry,
    Family,
    FamilyMember,
    Group,
    Role,
    Task,
    TaskCompletion,
    User,
)

TASK_ROLES = (Role.adolescent.value, Role.caregiver.value)
MAX_WINDOW_DAYS = 62


def group_of(db: Session, user: User) -> Group | None:
    return db.execute(
        select(Group)
        .join(Family, Family.group_id == Group.id)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .where(FamilyMember.user_id == user.id)
    ).scalar_one_or_none()


def _clean(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text.strip()[:limit] or None


def _check_window(starts_on: date, due_on: date) -> None:
    if due_on < starts_on or (due_on - starts_on).days > MAX_WINDOW_DAYS:
        raise bad_request("task.invalid_window")


def _check_roles(roles: list[str]) -> list[str]:
    clean = [r for r in TASK_ROLES if r in roles]
    if not clean or len(set(roles)) != len(clean):
        raise bad_request("task.invalid_roles")
    return clean


def _check_skills(skill_ids: list[str], known: set[str]) -> list[str]:
    if any(s not in known for s in skill_ids):
        raise bad_request("task.unknown_skill")
    return list(dict.fromkeys(skill_ids))


def _apply(task: Task, body: dict[str, Any], known_skills: set[str]) -> None:
    title = _clean(body["title"], 200)
    if not title:
        raise bad_request("task.title_required")
    _check_window(body["starts_on"], body["due_on"])
    task.title = title
    task.details = _clean(body.get("details"), 1000)
    task.for_roles = _check_roles(body["for_roles"])
    task.skill_ids = _check_skills(body.get("skill_ids") or [], known_skills)
    task.starts_on = body["starts_on"]
    task.due_on = body["due_on"]


# --- therapist ---


def create_task(
    db: Session, therapist: User, group: Group, body: dict[str, Any], known_skills: set[str]
) -> Task:
    task = Task(group_id=group.id, kind="homework", created_by=therapist.id)
    _apply(task, body, known_skills)
    db.add(task)
    db.flush()
    audit.record(
        db,
        "task.created",
        actor=therapist,
        target_type="task",
        target_id=task.id,
        details={"group_id": str(group.id), "roles": list(task.for_roles)},
    )
    return task


def get_task(db: Session, actor: User, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise not_found()
    ensure_group(db, actor, task.group_id)
    return task


def update_task(
    db: Session, therapist: User, task: Task, body: dict[str, Any], known_skills: set[str]
) -> Task:
    if task.archived_at is not None:
        raise bad_request("task.archived")
    _apply(task, body, known_skills)
    db.flush()
    audit.record(db, "task.updated", actor=therapist, target_type="task", target_id=task.id)
    return task


def archive_task(db: Session, therapist: User, task: Task) -> None:
    """Removes the item from participants' lists; completions already recorded are kept."""
    if task.archived_at is None:
        task.archived_at = utcnow()
        audit.record(db, "task.archived", actor=therapist, target_type="task", target_id=task.id)


def set_diary_expectation(db: Session, therapist: User, group: Group, days: int) -> None:
    if not 1 <= days <= 7:
        raise bad_request("group.invalid_diary_days")
    if group.diary_days_per_week != days:
        group.diary_days_per_week = days
        audit.record(
            db,
            "group.diary_expectation_set",
            actor=therapist,
            target_type="group",
            target_id=group.id,
            details={"days_per_week": days},
        )


def _completed_by(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[uuid.UUID]]:
    out: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    if task_ids:
        for tid, uid in db.execute(
            select(TaskCompletion.task_id, TaskCompletion.user_id).where(
                TaskCompletion.task_id.in_(task_ids)
            )
        ).all():
            out[tid].add(uid)
    return out


def group_tasks(db: Session, group: Group) -> list[dict[str, Any]]:
    """Open tasks with a per-assignee status (done / not yet), by family. Aliases only."""
    tasks = list(
        db.execute(
            select(Task)
            .where(Task.group_id == group.id, Task.archived_at.is_(None))
            .order_by(Task.due_on.desc(), Task.created_at.desc())
        ).scalars()
    )
    done = _completed_by(db, [t.id for t in tasks])
    members = list(
        db.execute(
            select(FamilyMember, Family.label, User)
            .join(Family, Family.id == FamilyMember.family_id)
            .join(User, User.id == FamilyMember.user_id)
            .where(Family.group_id == group.id)
            .order_by(Family.created_at, User.display_alias)
        ).all()
    )
    out = []
    for t in tasks:
        status = [
            {
                "family_id": str(m.family_id),
                "family": label,
                "alias": u.display_alias,
                "role": m.member_role.value,
                "done": u.id in done.get(t.id, set()),
            }
            for m, label, u in members
            if m.member_role.value in t.for_roles
        ]
        out.append({**task_view(t), "assignees": status})
    return out


def task_view(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "details": t.details,
        "for_roles": list(t.for_roles),
        "skill_ids": list(t.skill_ids),
        "starts_on": t.starts_on.isoformat(),
        "due_on": t.due_on.isoformat(),
        "archived": t.archived_at is not None,
    }


# --- participants ---


def _open_tasks(db: Session, user: User, first: date, last: date) -> list[Task]:
    """This person's open homework overlapping [first, last]."""
    group = group_of(db, user)
    if group is None:
        return []
    rows = db.execute(
        select(Task)
        .where(
            Task.group_id == group.id,
            Task.archived_at.is_(None),
            Task.starts_on <= last,
            Task.due_on >= first,
        )
        .order_by(Task.due_on, Task.created_at)
    ).scalars()
    return [t for t in rows if user.role.value in t.for_roles]


def tasks_for(db: Session, user: User, day: date) -> list[Task]:
    return _open_tasks(db, user, day, day)


def participant_view(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "details": t.details,
        "skill_ids": list(t.skill_ids),
        "due_on": t.due_on.isoformat(),
    }


def my_homework(db: Session, user: User, today: date) -> list[dict[str, Any]]:
    """This week's homework: items open today or starting within the next 6 days."""
    rows = _open_tasks(db, user, today, today + timedelta(days=6))
    done = (
        set(
            db.execute(
                select(TaskCompletion.task_id).where(
                    TaskCompletion.user_id == user.id,
                    TaskCompletion.task_id.in_([t.id for t in rows]),
                )
            ).scalars()
        )
        if rows
        else set()
    )
    return [{**participant_view(t), "done": t.id in done} for t in rows]


def homework_of_entries(db: Session, entry_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Task]]:
    out: dict[uuid.UUID, list[Task]] = defaultdict(list)
    if entry_ids:
        for eid, task in db.execute(
            select(TaskCompletion.entry_id, Task)
            .join(Task, Task.id == TaskCompletion.task_id)
            .where(TaskCompletion.entry_id.in_(entry_ids))
            .order_by(Task.due_on, Task.created_at)
        ).all():
            out[eid].append(task)
    return out


def validate_homework(
    db: Session,
    user: User,
    day: date,
    task_ids: list[uuid.UUID],
    entry: DiaryEntry | None = None,
) -> list[Task]:
    """Ticked items must be this person's open homework on the entry's day, or items already
    ticked on this entry (editing an entry never loses a tick after an item closes)."""
    allowed = {t.id: t for t in tasks_for(db, user, day)}
    if entry is not None:
        allowed.update({t.id: t for t in homework_of_entries(db, [entry.id]).get(entry.id, [])})
    picked = list(dict.fromkeys(task_ids))
    if any(tid not in allowed for tid in picked):
        raise bad_request("diary.unknown_homework")
    return [allowed[tid] for tid in picked]


def sync_completions(db: Session, user: User, entry: DiaryEntry, tasks: list[Task]) -> bool:
    """Make the entry's ticked homework equal `tasks`. Returns True if anything changed."""
    current = {
        c.task_id: c
        for c in db.execute(
            select(TaskCompletion).where(TaskCompletion.entry_id == entry.id)
        ).scalars()
    }
    wanted = {t.id for t in tasks}
    changed = False
    for tid, c in current.items():
        if tid not in wanted:
            db.delete(c)
            changed = True
    for tid in wanted - current.keys():
        db.add(
            TaskCompletion(
                task_id=tid, user_id=user.id, entry_id=entry.id, completed_on=entry.entry_date
            )
        )
        changed = True
    if changed:
        db.flush()
        audit.record(
            db,
            "diary.homework_marked",
            actor=user,
            target_type="diary_entry",
            target_id=entry.id,
            details={"count": len(wanted)},
        )
    return changed
