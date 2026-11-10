"""Safety events (Plan §4.1 SafetyEvent, §5.7; Phase 2 task 1).

Trigger excerpts, detection details, clinician notes and follow-up actions are encrypted.
Status workflow: new -> acknowledged -> in_review -> resolved (acknowledged may go straight to
resolved). Every change is audited (app/safety/events.py). No SLA escalation job (D38).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedText
from app.core.db import Base
from app.models.entities import _enum, _now, _uuid_pk


class SafetyCategory(StrEnum):
    discomfort_or_trauma_cue = "discomfort_or_trauma_cue"
    risk_disclosure = "risk_disclosure"
    urge_threshold = "urge_threshold"
    suspected_abuse = "suspected_abuse"
    parental_coercion = "parental_coercion"
    privacy_breach = "privacy_breach"
    delayed_clinician_response = "delayed_clinician_response"


# Automated detection covers only risk disclosures and urge thresholds (Plan §5.7); urge
# thresholds come only from Diary Cards, so clinicians file everything else by hand.
MANUAL_CATEGORIES = frozenset(set(SafetyCategory) - {SafetyCategory.urge_threshold})


class SafetySeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


SEVERITY_RANK = {SafetySeverity.low: 1, SafetySeverity.medium: 2, SafetySeverity.high: 3}


class SafetySource(StrEnum):
    lesson = "lesson"
    diary = "diary"
    joint = "joint"
    manual = "manual"


class DetectionChannel(StrEnum):
    keyword = "keyword"
    llm = "llm"
    threshold = "threshold"
    manual = "manual"
    participant = "participant"  # participant pressed "I need to stop" (joint sessions)


class SafetyStatus(StrEnum):
    new = "new"
    acknowledged = "acknowledged"
    in_review = "in_review"
    resolved = "resolved"


TRANSITIONS: dict[SafetyStatus, frozenset[SafetyStatus]] = {
    SafetyStatus.new: frozenset({SafetyStatus.acknowledged}),
    SafetyStatus.acknowledged: frozenset({SafetyStatus.in_review, SafetyStatus.resolved}),
    SafetyStatus.in_review: frozenset({SafetyStatus.resolved}),
    SafetyStatus.resolved: frozenset(),
}


class SafetyEvent(Base):
    __tablename__ = "safety_event"
    id: Mapped[uuid.UUID] = _uuid_pk()
    category: Mapped[SafetyCategory] = mapped_column(_enum(SafetyCategory, "safety_category"))
    severity: Mapped[SafetySeverity] = mapped_column(_enum(SafetySeverity, "safety_severity"))
    source: Mapped[SafetySource] = mapped_column(_enum(SafetySource, "safety_source"))
    channel: Mapped[DetectionChannel] = mapped_column(_enum(DetectionChannel, "detection_channel"))
    status: Mapped[SafetyStatus] = mapped_column(
        _enum(SafetyStatus, "safety_status"), default=SafetyStatus.new
    )
    subject_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family.id"), index=True)
    # Id of the lesson / diary entry / joint session the event came from, when there is one.
    source_ref: Mapped[str | None] = mapped_column(String(64))
    trigger_excerpt: Mapped[str | None] = mapped_column(EncryptedText)
    detection_detail: Mapped[str | None] = mapped_column(EncryptedText)  # JSON: terms, levels
    activity_stopped: Mapped[bool] = mapped_column(default=False)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    follow_up: Mapped[str | None] = mapped_column(EncryptedText)

    notes: Mapped[list[SafetyEventNote]] = relationship(
        order_by="SafetyEventNote.created_at", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_safety_event_status_created", "status", "created_at"),)


class SafetyEventNote(Base):
    """Clinician note on an event. Notes are append-only: there is no edit or delete route."""

    __tablename__ = "safety_event_note"
    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("safety_event.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    body: Mapped[str] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = _now()
