"""One-time invitation and reset codes (Plan §5.1; D30).

Codes are high-entropy, shown once, stored only as an HMAC digest, single-use and expiring.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import code_digest
from app.core.errors import bad_request
from app.core.security import new_code, normalise_code
from app.core.sessions import utcnow
from app.models import CodePurpose, Invitation, Role, User
from app.research import events as research_events


def _digest(code: str) -> str:
    return code_digest("code:" + normalise_code(code))


def issue(
    db: Session,
    *,
    actor: User,
    purpose: CodePurpose,
    role: Role,
    ttl: timedelta,
    family_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    relationship_label: str | None = None,
) -> tuple[Invitation, str]:
    code = new_code()
    if purpose is CodePurpose.reset and target_user_id is not None:
        # Only the newest reset code for an account stays valid.
        for old in db.execute(
            select(Invitation).where(
                Invitation.target_user_id == target_user_id,
                Invitation.purpose == CodePurpose.reset,
                Invitation.used_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
        ).scalars():
            old.revoked_at = utcnow()
    inv = Invitation(
        purpose=purpose,
        code_digest=_digest(code),
        intended_role=role,
        family_id=family_id,
        target_user_id=target_user_id,
        relationship_label=relationship_label,
        expires_at=utcnow() + ttl,
        created_by=actor.id,
    )
    db.add(inv)
    db.flush()
    research_events.record(
        db,
        "enrolment.code_issued",
        None,
        role=role.value,
        purpose=purpose.value,
        family=str(family_id) if family_id else None,
    )
    return inv, code


def find_usable(db: Session, code: str, purpose: CodePurpose | None = None) -> Invitation:
    """Return a usable code or raise one generic error (no hint whether it existed)."""
    inv = db.execute(
        select(Invitation).where(Invitation.code_digest == _digest(code)).with_for_update()
    ).scalar_one_or_none()
    if (
        inv is None
        or inv.used_at is not None
        or inv.revoked_at is not None
        or inv.expires_at <= utcnow()
        or (purpose is not None and inv.purpose is not purpose)
    ):
        raise bad_request("code.invalid")
    return inv


def is_pending(inv: Invitation) -> bool:
    return inv.used_at is None and inv.revoked_at is None and inv.expires_at > utcnow()
