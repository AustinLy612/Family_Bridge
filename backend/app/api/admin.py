"""Admin: therapist accounts and site settings (Plan §5.1; Phase 1 task 3). All changes audited."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AdminUser, AppSettings, Db
from app.api.schemas import (
    ApproverIn,
    IssuedCode,
    PendingInvite,
    SiteIn,
    SiteOut,
    StatusIn,
    TherapistList,
    TherapistOut,
)
from app.core import audit
from app.core.errors import bad_request, not_found
from app.core.policy import audit_read, ensure_manages_user
from app.core.sessions import revoke_all_sessions, utcnow
from app.models import (
    CodePurpose,
    GroupTherapist,
    Invitation,
    Role,
    Setting,
    Site,
    User,
    UserStatus,
)
from app.services import codes
from app.services.site import HELP_CONFIRMED_KEY, get_site

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _pending(inv: Invitation) -> PendingInvite:
    return PendingInvite(
        id=inv.id,
        role=inv.intended_role,
        relationship_label=inv.relationship_label,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    )


@router.get("/therapists")
def list_therapists(admin: AdminUser, db: Db) -> TherapistList:
    counts = dict(
        db.execute(
            select(GroupTherapist.therapist_id, func.count()).group_by(GroupTherapist.therapist_id)
        ).all()
    )
    therapists = db.execute(
        select(User).where(User.role == Role.therapist).order_by(User.display_alias)
    ).scalars()
    pending = db.execute(
        select(Invitation)
        .where(
            Invitation.purpose == CodePurpose.invite,
            Invitation.intended_role == Role.therapist,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > utcnow(),
        )
        .order_by(Invitation.created_at)
    ).scalars()
    audit_read(db, admin, "therapist.list", target_type="therapist", target_id="*")
    return TherapistList(
        therapists=[
            TherapistOut(
                id=t.id,
                username=t.username,
                display_alias=t.display_alias,
                status=t.status.value,
                last_login_at=t.last_login_at,
                group_count=int(counts.get(t.id, 0)),
                content_approver=t.content_approver,
            )
            for t in therapists
        ],
        pending=[_pending(i) for i in pending],
    )


@router.post("/therapists", status_code=201)
def invite_therapist(admin: AdminUser, db: Db, settings: AppSettings) -> IssuedCode:
    """Issue a one-time code; the therapist picks their username and password when redeeming."""
    inv, code = codes.issue(
        db,
        actor=admin,
        purpose=CodePurpose.invite,
        role=Role.therapist,
        ttl=timedelta(days=settings.invitation_ttl_days),
    )
    audit.record(
        db,
        "invitation.created",
        actor=admin,
        target_type="invitation",
        target_id=inv.id,
        details={"role": "therapist"},
    )
    return IssuedCode(invitation_id=inv.id, code=code, expires_at=inv.expires_at)


@router.post("/invitations/{invitation_id}/revoke", status_code=204)
def revoke_therapist_invite(invitation_id: uuid.UUID, admin: AdminUser, db: Db) -> None:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.intended_role is not Role.therapist or not codes.is_pending(inv):
        raise not_found()
    inv.revoked_at = utcnow()
    audit.record(db, "invitation.revoked", actor=admin, target_type="invitation", target_id=inv.id)


def _therapist(db: Db, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.role is not Role.therapist:
        raise not_found()
    return user


@router.post("/therapists/{user_id}/reset-code", status_code=201)
def therapist_reset_code(
    user_id: uuid.UUID, admin: AdminUser, db: Db, settings: AppSettings
) -> IssuedCode:
    target = _therapist(db, user_id)
    ensure_manages_user(db, admin, target)
    inv, code = codes.issue(
        db,
        actor=admin,
        purpose=CodePurpose.reset,
        role=target.role,
        target_user_id=target.id,
        ttl=timedelta(hours=settings.reset_code_ttl_hours),
    )
    audit.record(db, "reset_code.created", actor=admin, target_type="user", target_id=target.id)
    return IssuedCode(invitation_id=inv.id, code=code, expires_at=inv.expires_at)


@router.put("/therapists/{user_id}/status")
def set_therapist_status(
    user_id: uuid.UUID, body: StatusIn, admin: AdminUser, db: Db
) -> TherapistOut:
    target = _therapist(db, user_id)
    target.status = UserStatus(body.status)
    if target.status is UserStatus.disabled:
        revoke_all_sessions(db, target.id)
    audit.record(
        db,
        "user.status_changed",
        actor=admin,
        target_type="user",
        target_id=target.id,
        details={"status": body.status},
    )
    count = db.execute(
        select(func.count())
        .select_from(GroupTherapist)
        .where(GroupTherapist.therapist_id == target.id)
    ).scalar_one()
    return TherapistOut(
        id=target.id,
        username=target.username,
        display_alias=target.display_alias,
        status=target.status.value,
        last_login_at=target.last_login_at,
        group_count=int(count),
        content_approver=target.content_approver,
    )


@router.put("/therapists/{user_id}/content-approver")
def set_content_approver(
    user_id: uuid.UUID, body: ApproverIn, admin: AdminUser, db: Db
) -> TherapistOut:
    """Who may approve or retire episode versions (Plan §4.2 `content_approver`)."""
    target = _therapist(db, user_id)
    target.content_approver = body.content_approver
    audit.record(
        db,
        "user.content_approver_changed",
        actor=admin,
        target_type="user",
        target_id=target.id,
        details={"content_approver": body.content_approver},
    )
    count = db.execute(
        select(func.count())
        .select_from(GroupTherapist)
        .where(GroupTherapist.therapist_id == target.id)
    ).scalar_one()
    return TherapistOut(
        id=target.id,
        username=target.username,
        display_alias=target.display_alias,
        status=target.status.value,
        last_login_at=target.last_login_at,
        group_count=int(count),
        content_approver=target.content_approver,
    )


def _site_out(site: Site) -> SiteOut:
    return SiteOut(
        name=site.name,
        timezone=site.timezone,
        help_contacts=list(site.help_contacts or []),
        service_hours=dict(site.service_hours or {}),
        updated_at=site.updated_at,
    )


@router.get("/site")
def get_site_settings(admin: AdminUser, db: Db) -> SiteOut:
    site = get_site(db)
    if site is None:
        raise not_found("site.missing")
    return _site_out(site)


@router.put("/site")
def put_site_settings(body: SiteIn, admin: AdminUser, db: Db) -> SiteOut:
    for c in body.help_contacts:
        if not {"zh-CN", "en"} <= set(c.label):
            raise bad_request("site.contact_label_both_languages")
    site = get_site(db)
    if site is None:
        site = Site(name=body.name)
        db.add(site)
    site.name = body.name
    site.timezone = body.timezone
    site.help_contacts = [c.model_dump() for c in body.help_contacts]
    site.service_hours = {str(k): v for k, v in body.service_hours.items()}
    site.updated_at = utcnow()
    db.flush()
    audit.record(
        db,
        "site.updated",
        actor=admin,
        target_type="site",
        target_id=site.id,
        details={"contacts": len(body.help_contacts)},
    )
    return _site_out(site)


@router.put("/site/help-confirmed", status_code=204)
def confirm_help(admin: AdminUser, db: Db, confirmed: bool = False) -> None:
    """Mark help contacts as confirmed by the hospital (O4). Until then the UI says they are
    placeholders."""
    row = db.get(Setting, HELP_CONFIRMED_KEY)
    if row is None:
        row = Setting(key=HELP_CONFIRMED_KEY, value=confirmed, updated_by=admin.id)
        db.add(row)
    row.value = confirmed
    row.updated_by = admin.id
    row.updated_at = utcnow()
    audit.record(
        db,
        "setting.updated",
        actor=admin,
        target_type="setting",
        target_id=HELP_CONFIRMED_KEY,
        details={"value": confirmed},
    )
