"""Creating and updating safety events (Plan §5.7; Phase 2 tasks 1, 5, 6).

Every change writes an audit entry. Audit details carry ids and category names only, never the
trigger excerpt, notes or follow-up text (those are encrypted on the event).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import bad_request
from app.models import (
    SEVERITY_RANK,
    TRANSITIONS,
    DetectionChannel,
    FamilyMember,
    SafetyCategory,
    SafetyEvent,
    SafetyEventNote,
    SafetySeverity,
    SafetySource,
    SafetyStatus,
    User,
)

EXCERPT_MAX = 2000
NOTE_MAX = 4000


def _now() -> datetime:
    return datetime.now(UTC)


def _trim(text: str | None, limit: int = EXCERPT_MAX) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def family_of(db: Session, user: User) -> FamilyMember | None:
    return db.execute(
        select(FamilyMember).where(FamilyMember.user_id == user.id)
    ).scalar_one_or_none()


def raise_event(
    db: Session,
    *,
    subject: User,
    category: SafetyCategory,
    severity: SafetySeverity,
    source: SafetySource,
    channel: DetectionChannel,
    excerpt: str | None = None,
    detail: dict[str, Any] | None = None,
    source_ref: str | None = None,
    activity_stopped: bool = False,
    created_by: User | None = None,
) -> SafetyEvent:
    """Create a safety event, or add to the open one from the same activity.

    Repeated flags from one lesson / diary entry / joint session go onto the same unresolved
    event (severity only ever goes up), so the queue shows one item per activity.
    """
    member = family_of(db, subject)
    existing = None
    if source_ref is not None:
        existing = db.execute(
            select(SafetyEvent)
            .where(
                SafetyEvent.subject_user_id == subject.id,
                SafetyEvent.source == source,
                SafetyEvent.source_ref == source_ref,
                SafetyEvent.category == category,
                SafetyEvent.status != SafetyStatus.resolved,
            )
            .order_by(SafetyEvent.created_at.desc())
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()

    if existing is not None:
        if SEVERITY_RANK[severity] > SEVERITY_RANK[existing.severity]:
            existing.severity = severity
        if excerpt:
            joined = "\n---\n".join(x for x in (existing.trigger_excerpt, excerpt.strip()) if x)
            existing.trigger_excerpt = _trim(joined[-EXCERPT_MAX:])
        if detail:
            old = json.loads(existing.detection_detail) if existing.detection_detail else []
            existing.detection_detail = json.dumps([*old, detail][-10:], ensure_ascii=False)
        existing.activity_stopped = existing.activity_stopped or activity_stopped
        existing.occurrences += 1
        existing.updated_at = _now()
        audit.record(
            db,
            "safety.event_updated",
            actor=created_by,
            target_type="safety_event",
            target_id=existing.id,
            details={"severity": existing.severity.value, "occurrences": existing.occurrences},
        )
        return existing

    event = SafetyEvent(
        category=category,
        severity=severity,
        source=source,
        channel=channel,
        status=SafetyStatus.new,
        subject_user_id=subject.id,
        family_id=member.family_id if member else None,
        source_ref=source_ref,
        trigger_excerpt=_trim(excerpt),
        detection_detail=json.dumps([detail], ensure_ascii=False) if detail else None,
        activity_stopped=activity_stopped,
        occurrences=1,
        created_by=created_by.id if created_by else None,
        updated_at=_now(),
    )
    db.add(event)
    db.flush()
    audit.record(
        db,
        "safety.event_created",
        actor=created_by,
        target_type="safety_event",
        target_id=event.id,
        details={
            "category": category.value,
            "severity": severity.value,
            "source": source.value,
            "channel": channel.value,
            "subject": subject.pseudonym_code,
            "stopped": activity_stopped,
        },
    )
    return event


def transition(
    db: Session,
    event: SafetyEvent,
    actor: User,
    to: SafetyStatus,
    *,
    note: str | None = None,
    follow_up: str | None = None,
) -> SafetyEvent:
    if to not in TRANSITIONS[event.status]:
        raise bad_request("safety.transition_invalid", current=event.status.value, to=to.value)
    if to is SafetyStatus.resolved and not (follow_up and follow_up.strip()):
        raise bad_request("safety.follow_up_required")
    now = _now()
    previous = event.status
    event.status = to
    event.updated_at = now
    if to is SafetyStatus.acknowledged:
        event.acknowledged_at = now
        event.assignee_id = event.assignee_id or actor.id
    elif to is SafetyStatus.in_review:
        event.review_started_at = now
    elif to is SafetyStatus.resolved:
        event.resolved_at = now
        event.resolved_by = actor.id
        event.follow_up = _trim(follow_up, NOTE_MAX)
    audit.record(
        db,
        "safety.status_changed",
        actor=actor,
        target_type="safety_event",
        target_id=event.id,
        details={"from": previous.value, "to": to.value},
    )
    if note and note.strip():
        add_note(db, event, actor, note)
    return event


def add_note(db: Session, event: SafetyEvent, actor: User, body: str) -> SafetyEventNote:
    body = body.strip()
    if not body:
        raise bad_request("safety.note_empty")
    note = SafetyEventNote(event_id=event.id, author_id=actor.id, body=_trim(body, NOTE_MAX))
    db.add(note)
    event.updated_at = _now()
    db.flush()
    audit.record(
        db,
        "safety.note_added",
        actor=actor,
        target_type="safety_event",
        target_id=event.id,
        details={"note_id": str(note.id)},
    )
    return note
