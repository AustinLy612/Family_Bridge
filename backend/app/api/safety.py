"""Help screen and the clinician safety queue (Plan §5.7, §5.8; Phase 2 tasks 3, 5, 6).

- `GET /api/v1/help` is public: the help screen must be reachable even when signed out.
- The queue is for therapists (own families only) and admins (all events, read-only, D39).
  Participants never reach these routes (role gate + policy), and see only the help screen.
- Every read of an event, and every queue listing, is audited.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.api.deps import Db, StaffUser, TherapistUser
from app.api.schemas import (
    FamilyRef,
    HelpDocOut,
    HelpPageOut,
    Language,
    NoticeOut,
    PersonRef,
    SafetyCounts,
    SafetyEventDetail,
    SafetyEventIn,
    SafetyEventList,
    SafetyEventSummary,
    SafetyNoteIn,
    SafetyNoteOut,
    SafetyStatusIn,
    SafetySubject,
    SafetyTimelineItem,
)
from app.content.loader import ContentBundle
from app.core.errors import bad_request, not_found
from app.core.policy import audit_read, deny, ensure_safety_event, therapist_group_ids
from app.models import (
    SEVERITY_RANK,
    TRANSITIONS,
    DetectionChannel,
    Family,
    FamilyMember,
    Role,
    SafetyCategory,
    SafetyEvent,
    SafetySeverity,
    SafetySource,
    SafetyStatus,
    User,
)
from app.safety import events as safety_events
from app.services.site import site_help

router = APIRouter(prefix="/api/v1", tags=["safety"])


# --- help screen -------------------------------------------------------------------------------


@router.get("/help")
def help_page(
    request: Request, db: Db, language: Annotated[Language, Query()] = "zh-CN"
) -> HelpPageOut:
    content: ContentBundle = request.app.state.content
    doc = content.help(language)
    if doc is None:
        raise not_found("help.missing")
    return HelpPageOut(
        document=HelpDocOut(
            version=doc.version,
            language=doc.language,
            approval=doc.approval.status.value,
            stop_notice=NoticeOut(**doc.stop_notice.model_dump()),
            care_card=NoticeOut(**doc.care_card.model_dump()),
            sections=[s.model_dump() for s in doc.sections],
        ),
        site=site_help(db),
    )


# --- queue helpers -----------------------------------------------------------------------------


def _person(db: Session, user_id: uuid.UUID | None) -> PersonRef | None:
    if user_id is None:
        return None
    u = db.get(User, user_id)
    return PersonRef(id=u.id, alias=u.display_alias, role=u.role) if u else None


def _family(db: Session, family_id: uuid.UUID | None) -> FamilyRef | None:
    if family_id is None:
        return None
    f = db.get(Family, family_id)
    if f is None:
        return None
    return FamilyRef(id=f.id, label=f.label, group_id=f.group_id, group_name=f.group.name)


def _summary(db: Session, e: SafetyEvent) -> SafetyEventSummary:
    subject = _person(db, e.subject_user_id)
    assert subject is not None
    return SafetyEventSummary(
        id=e.id,
        category=e.category.value,
        severity=e.severity.value,
        status=e.status.value,
        source=e.source.value,
        channel=e.channel.value,
        subject=subject,
        family=_family(db, e.family_id),
        assignee=_person(db, e.assignee_id),
        occurrences=e.occurrences,
        activity_stopped=e.activity_stopped,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def _terms(e: SafetyEvent) -> list[str]:
    if not e.detection_detail:
        return []
    out: list[str] = []
    for d in json.loads(e.detection_detail):
        for t in d.get("terms", []):
            if t not in out:
                out.append(t)
    return out


def _detail(db: Session, e: SafetyEvent, actor: User) -> SafetyEventDetail:
    timeline = [SafetyTimelineItem(status="new", at=e.created_at)]
    for status, at in (
        ("acknowledged", e.acknowledged_at),
        ("in_review", e.review_started_at),
        ("resolved", e.resolved_at),
    ):
        if at is not None:
            timeline.append(SafetyTimelineItem(status=status, at=at))
    notes = []
    for n in e.notes:
        author = _person(db, n.author_id)
        assert author is not None
        notes.append(SafetyNoteOut(id=n.id, author=author, body=n.body, created_at=n.created_at))
    nxt = sorted(s.value for s in TRANSITIONS[e.status]) if actor.role is Role.therapist else []
    return SafetyEventDetail(
        **_summary(db, e).model_dump(),
        excerpt=e.trigger_excerpt,
        matched_terms=_terms(e),
        created_by=_person(db, e.created_by),
        follow_up=e.follow_up,
        resolved_by=_person(db, e.resolved_by),
        notes=notes,
        timeline=timeline,
        next_statuses=nxt,
    )


def _scope(db: Session, actor: User) -> Select[SafetyEvent]:
    """Base query limited to what the actor may see."""
    q = select(SafetyEvent)
    if actor.role is Role.therapist:
        groups = therapist_group_ids(db, actor)
        q = q.join(Family, Family.id == SafetyEvent.family_id).where(Family.group_id.in_(groups))
    return q


# --- queue -------------------------------------------------------------------------------------

StatusFilter = Literal["open", "resolved", "all"]
_STATUS_ORDER = {
    SafetyStatus.new: 0,
    SafetyStatus.acknowledged: 1,
    SafetyStatus.in_review: 2,
    SafetyStatus.resolved: 3,
}


@router.get("/safety/events")
def list_events(
    actor: StaffUser,
    db: Db,
    status: Annotated[StatusFilter, Query()] = "open",
) -> SafetyEventList:
    base = _scope(db, actor)
    q = base
    if status == "open":
        q = q.where(SafetyEvent.status != SafetyStatus.resolved)
    elif status == "resolved":
        q = q.where(SafetyEvent.status == SafetyStatus.resolved)
    rows = list(db.execute(q).scalars())
    if status == "resolved":
        rows.sort(key=lambda e: e.resolved_at or e.updated_at, reverse=True)
    else:
        # Unacknowledged first, then highest severity, then longest waiting.
        rows.sort(key=lambda e: (_STATUS_ORDER[e.status], -SEVERITY_RANK[e.severity], e.created_at))
    sub = base.subquery()
    new = db.execute(
        select(func.count()).select_from(sub).where(sub.c.status == SafetyStatus.new.value)
    ).scalar_one()
    open_ = db.execute(
        select(func.count()).select_from(sub).where(sub.c.status != SafetyStatus.resolved.value)
    ).scalar_one()
    audit_read(
        db,
        actor,
        "safety.queue_read",
        target_type="safety_queue",
        target_id=status,
        count=len(rows),
    )
    return SafetyEventList(
        events=[_summary(db, e) for e in rows], counts=SafetyCounts(new=new, open=open_)
    )


@router.get("/safety/events/{event_id}")
def get_event(event_id: uuid.UUID, actor: StaffUser, db: Db) -> SafetyEventDetail:
    event = ensure_safety_event(db, actor, event_id, write=False)
    audit_read(db, actor, "safety.event_read", target_type="safety_event", target_id=event.id)
    return _detail(db, event, actor)


@router.post("/safety/events/{event_id}/status")
def change_status(
    event_id: uuid.UUID, body: SafetyStatusIn, actor: TherapistUser, db: Db
) -> SafetyEventDetail:
    event = ensure_safety_event(db, actor, event_id, write=True)
    safety_events.transition(
        db, event, actor, SafetyStatus(body.status), note=body.note, follow_up=body.follow_up
    )
    db.flush()
    db.refresh(event)
    return _detail(db, event, actor)


@router.post("/safety/events/{event_id}/notes", status_code=201)
def add_note(
    event_id: uuid.UUID, body: SafetyNoteIn, actor: TherapistUser, db: Db
) -> SafetyEventDetail:
    event = ensure_safety_event(db, actor, event_id, write=True)
    safety_events.add_note(db, event, actor, body.body)
    db.flush()
    db.refresh(event)
    return _detail(db, event, actor)


# --- manual events (Phase 2 task 6) ------------------------------------------------------------


def _subjects(db: Session, therapist: User) -> list[tuple[User, Family]]:
    groups = therapist_group_ids(db, therapist)
    rows = db.execute(
        select(User, Family)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.group_id.in_(groups))
        .order_by(Family.label, User.role, User.display_alias)
    ).all()
    return [(u, f) for u, f in rows]


@router.get("/safety/subjects")
def list_subjects(actor: TherapistUser, db: Db) -> list[SafetySubject]:
    return [
        SafetySubject(
            user=PersonRef(id=u.id, alias=u.display_alias, role=u.role),
            family=FamilyRef(id=f.id, label=f.label, group_id=f.group_id, group_name=f.group.name),
        )
        for u, f in _subjects(db, actor)
    ]


@router.post("/safety/events", status_code=201)
def create_event(body: SafetyEventIn, actor: TherapistUser, db: Db) -> SafetyEventDetail:
    subject = db.get(User, body.subject_user_id)
    if subject is None or not subject.is_participant:
        raise bad_request("safety.subject_invalid")
    allowed = {u.id for u, _ in _subjects(db, actor)}
    if subject.id not in allowed:
        raise deny(db, actor, target_type="user", target_id=subject.id, reason="not_assigned")
    event = safety_events.raise_event(
        db,
        subject=subject,
        category=SafetyCategory(body.category),
        severity=SafetySeverity(body.severity),
        source=SafetySource.manual,
        channel=DetectionChannel.manual,
        excerpt=body.description,
        created_by=actor,
    )
    return _detail(db, event, actor)
