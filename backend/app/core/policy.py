"""The single authorisation policy module (Plan §4.2; Phase 1 task 6).

Every endpoint that touches another person's data goes through a function here. Rules:

- Admin: manages all groups, families, invitations and therapist accounts. Admin sees no
  participant clinical data (none exists in Phase 1; later phases keep it aggregate-only).
- Therapist: only groups they are assigned to (`GroupTherapist`), and the families in them.
- Participants (adolescent, caregiver): only themselves. They never reach staff endpoints.
- Every denial writes an `access.denied` audit entry, committed even though the request fails.
- Every successful cross-user read writes an audit entry (see `audit_read`).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import ApiError, forbidden, not_found
from app.models import Family, Group, GroupTherapist, Role, User


def deny(
    db: Session,
    actor: User | None,
    *,
    target_type: str,
    target_id: object | None = None,
    reason: str,
    code: str = "access.forbidden",
) -> ApiError:
    """Record a denial in the audit log and return the error to raise.

    The request transaction is rolled back when the error propagates, so the audit entry is
    written in its own committed step first (nothing else is pending at this point).
    """
    db.rollback()
    audit.record(
        db,
        "access.denied",
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        details={"reason": reason},
    )
    db.commit()
    return forbidden(code)


def audit_read(
    db: Session, actor: User, action: str, *, target_type: str, target_id: object, **details: Any
) -> None:
    audit.record(
        db, action, actor=actor, target_type=target_type, target_id=target_id, details=details
    )


def therapist_group_ids(db: Session, therapist: User) -> set[uuid.UUID]:
    rows = db.execute(
        select(GroupTherapist.group_id).where(GroupTherapist.therapist_id == therapist.id)
    ).scalars()
    return set(rows)


def can_manage_group(db: Session, actor: User, group_id: uuid.UUID) -> bool:
    if actor.role is Role.admin:
        return True
    if actor.role is Role.therapist:
        return group_id in therapist_group_ids(db, actor)
    return False


def ensure_group(db: Session, actor: User, group_id: uuid.UUID) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise not_found()
    if not can_manage_group(db, actor, group.id):
        raise deny(db, actor, target_type="group", target_id=group_id, reason="not_assigned")
    return group


def ensure_family(db: Session, actor: User, family_id: uuid.UUID) -> Family:
    family = db.get(Family, family_id)
    if family is None:
        raise not_found()
    if not can_manage_group(db, actor, family.group_id):
        raise deny(db, actor, target_type="family", target_id=family_id, reason="not_assigned")
    return family


def ensure_manages_user(db: Session, actor: User, target: User) -> None:
    """Who may issue a password-reset code for `target` (D30)."""
    if target.role is Role.therapist:
        allowed = actor.role is Role.admin
    elif target.is_participant:
        from app.models import FamilyMember  # local import keeps the module surface small

        member = db.execute(
            select(FamilyMember).where(FamilyMember.user_id == target.id)
        ).scalar_one_or_none()
        allowed = member is not None and can_manage_group(db, actor, member.family.group_id)
        # Admins manage families, but resets for participants go through their therapist (D30).
        allowed = allowed and actor.role is Role.therapist
    else:
        allowed = False
    if not allowed:
        raise deny(db, actor, target_type="user", target_id=target.id, reason="reset_not_allowed")


def safety_event_visible(db: Session, actor: User, event: Any) -> bool:
    """Safety events (Plan §4.2): assigned therapists of the family's group; admins read all.

    Participants never see events, only their own help screen.
    """
    if actor.role is Role.admin:
        return True
    if actor.role is not Role.therapist or event.family_id is None:
        return False
    family = db.get(Family, event.family_id)
    return family is not None and family.group_id in therapist_group_ids(db, actor)


def ensure_safety_event(db: Session, actor: User, event_id: uuid.UUID, *, write: bool) -> Any:
    from app.models import SafetyEvent  # local import keeps the module surface small

    event = db.get(SafetyEvent, event_id)
    if event is None:
        raise not_found()
    if not safety_event_visible(db, actor, event):
        raise deny(db, actor, target_type="safety_event", target_id=event_id, reason="not_assigned")
    if write and actor.role is not Role.therapist:
        # Admin oversight is read-only (D39).
        raise deny(db, actor, target_type="safety_event", target_id=event_id, reason="read_only")
    return event
