"""Phase 7 therapist dashboard records (Plan §4.1 `Task`, §5.8, §8.4).

- `Task`: therapist-set group homework for one or both participant roles, with a due window
  (D69). Lessons are never tasks (D24). Joint-session assignments arrive with Phase 8.
- `TaskCompletion`: a participant ticked a homework item in a diary entry (Plan §5.6 checklist).
  Status per assignee is "done" once any completion exists; there is no overdue state.
- `TherapistTime`: seconds a therapist spent with a family's screens in focus, per day
  (§8.4 "therapist time per family"). Counts only, no content.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.entities import _now, _uuid_pk

USER_FK = "app_user.id"
TASK_KINDS = ("homework",)
TASK_TITLE_MAX = 200
TASK_DETAILS_MAX = 1000


class Task(Base):
    __tablename__ = "task"
    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dbt_group.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="homework")
    for_roles: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    title: Mapped[str] = mapped_column(String(TASK_TITLE_MAX))
    details: Mapped[str | None] = mapped_column(String(TASK_DETAILS_MAX), nullable=True)
    skill_ids: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    starts_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(USER_FK, ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _now()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def active_on(self, day: date) -> bool:
        return self.archived_at is None and self.starts_on <= day <= self.due_on


class TaskCompletion(Base):
    __tablename__ = "task_completion"
    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"), index=True)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("diary_entry.id", ondelete="CASCADE"), index=True
    )
    completed_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("task_id", "entry_id"),)


class TherapistTime(Base):
    __tablename__ = "therapist_time"
    id: Mapped[uuid.UUID] = _uuid_pk()
    therapist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("family.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("therapist_id", "family_id", "day"),)


class RecruitmentCount(Base):
    """Enrolment-funnel denominators entered by a therapist (Plan §5.10, §8.4).

    Counts of families for one group over a period; no identities. Each save is a new row, so
    the latest row per (group, period) is the current figure and earlier ones stay as history.
    """

    __tablename__ = "recruitment_count"
    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dbt_group.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    screened: Mapped[int] = mapped_column(Integer)
    eligible: Mapped[int] = mapped_column(Integer)
    approached: Mapped[int] = mapped_column(Integer)
    consented: Mapped[int] = mapped_column(Integer)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(USER_FK, ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = _now()
