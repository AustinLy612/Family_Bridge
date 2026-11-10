"""Groups, families, invitations, suitability (Plan §5.1, §5.8; Phase 1 task 4).

Therapists see only groups they are assigned to; admins manage all (Plan §4.2).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AdminUser, AppSettings, Db, StaffUser, TherapistUser
from app.api.schemas import (
    DyadOut,
    FamilyDetail,
    FamilyIn,
    FamilySummary,
    GroupDetail,
    GroupIn,
    GroupSummary,
    GroupTherapistsIn,
    InviteIn,
    IssuedCode,
    MemberOut,
    PendingInvite,
    SuitabilityIn,
)
from app.core import audit
from app.core.errors import bad_request, conflict, not_found
from app.core.policy import (
    audit_read,
    ensure_family,
    ensure_group,
    ensure_manages_user,
    therapist_group_ids,
)
from app.core.sessions import utcnow
from app.models import (
    CodePurpose,
    DyadSuitability,
    Family,
    FamilyMember,
    Group,
    GroupTherapist,
    Invitation,
    Role,
    User,
    UserStatus,
)
from app.services import codes

router = APIRouter(prefix="/api/v1", tags=["groups"])


def _therapist_aliases(db: Db, group_id: uuid.UUID) -> list[str]:
    return list(
        db.execute(
            select(User.display_alias)
            .join(GroupTherapist, GroupTherapist.therapist_id == User.id)
            .where(GroupTherapist.group_id == group_id)
            .order_by(User.display_alias)
        ).scalars()
    )


def _pending_invites(db: Db, family_id: uuid.UUID) -> list[Invitation]:
    rows = db.execute(
        select(Invitation)
        .where(Invitation.family_id == family_id, Invitation.purpose == CodePurpose.invite)
        .order_by(Invitation.created_at)
    ).scalars()
    return [i for i in rows if codes.is_pending(i)]


def _summary(db: Db, g: Group) -> GroupSummary:
    count = db.execute(
        select(func.count()).select_from(Family).where(Family.group_id == g.id)
    ).scalar_one()
    return GroupSummary(
        id=g.id,
        name=g.name,
        family_count=int(count),
        therapists=_therapist_aliases(db, g.id),
        is_demo=g.is_demo,
    )


def _valid_therapists(db: Db, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    found = set(
        db.execute(
            select(User.id).where(
                User.id.in_(ids), User.role == Role.therapist, User.status == UserStatus.active
            )
        ).scalars()
    )
    if found != set(ids):
        raise bad_request("group.unknown_therapist")
    return list(dict.fromkeys(ids))


@router.get("/groups")
def list_groups(user: StaffUser, db: Db) -> list[GroupSummary]:
    q = select(Group).order_by(Group.created_at)
    if user.role is Role.therapist:
        q = q.where(Group.id.in_(therapist_group_ids(db, user) or {uuid.UUID(int=0)}))
    return [_summary(db, g) for g in db.execute(q).scalars()]


@router.post("/groups", status_code=201)
def create_group(body: GroupIn, user: StaffUser, db: Db) -> GroupSummary:
    therapist_ids = _valid_therapists(db, body.therapist_ids)
    if user.role is Role.therapist and user.id not in therapist_ids:
        therapist_ids.insert(0, user.id)
    group = Group(name=body.name.strip(), is_demo=user.is_demo, created_by=user.id)
    db.add(group)
    db.flush()
    for tid in therapist_ids:
        db.add(GroupTherapist(group_id=group.id, therapist_id=tid))
    db.flush()
    audit.record(
        db,
        "group.created",
        actor=user,
        target_type="group",
        target_id=group.id,
        details={"therapists": [str(t) for t in therapist_ids]},
    )
    return _summary(db, group)


@router.put("/groups/{group_id}/therapists")
def set_group_therapists(
    group_id: uuid.UUID, body: GroupTherapistsIn, admin: AdminUser, db: Db
) -> GroupSummary:
    group = ensure_group(db, admin, group_id)
    ids = _valid_therapists(db, body.therapist_ids)
    for gt in list(group.therapists):
        if gt.therapist_id not in ids:
            group.therapists.remove(gt)
    have = {gt.therapist_id for gt in group.therapists}
    for tid in ids:
        if tid not in have:
            group.therapists.append(GroupTherapist(group_id=group.id, therapist_id=tid))
    db.flush()
    audit.record(
        db,
        "group.therapists_changed",
        actor=admin,
        target_type="group",
        target_id=group.id,
        details={"therapists": [str(t) for t in ids]},
    )
    return _summary(db, group)


@router.get("/groups/{group_id}")
def get_group(group_id: uuid.UUID, user: StaffUser, db: Db) -> GroupDetail:
    group = ensure_group(db, user, group_id)
    families = []
    for f in sorted(group.families, key=lambda f: f.created_at):
        families.append(
            FamilySummary(
                id=f.id,
                label=f.label,
                member_count=len(f.members),
                pending_invites=len(_pending_invites(db, f.id)),
            )
        )
    audit_read(db, user, "group.read", target_type="group", target_id=group.id)
    return GroupDetail(**_summary(db, group).model_dump(), families=families)


@router.post("/groups/{group_id}/families", status_code=201)
def create_family(group_id: uuid.UUID, body: FamilyIn, user: StaffUser, db: Db) -> FamilySummary:
    group = ensure_group(db, user, group_id)
    family = Family(group_id=group.id, label=body.label.strip(), is_demo=group.is_demo)
    db.add(family)
    db.flush()
    audit.record(
        db,
        "family.created",
        actor=user,
        target_type="family",
        target_id=family.id,
        details={"group_id": str(group.id)},
    )
    return FamilySummary(id=family.id, label=family.label, member_count=0, pending_invites=0)


def _pending_out(inv: Invitation) -> PendingInvite:
    return PendingInvite(
        id=inv.id,
        role=inv.intended_role,
        relationship_label=inv.relationship_label,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    )


def _dyads(db: Db, family: Family) -> list[DyadOut]:
    adolescents = [m.user_id for m in family.members if m.member_role is Role.adolescent]
    caregivers = [m.user_id for m in family.members if m.member_role is Role.caregiver]
    stored = {
        (d.adolescent_id, d.caregiver_id): d
        for d in db.execute(
            select(DyadSuitability).where(DyadSuitability.family_id == family.id)
        ).scalars()
    }
    out: list[DyadOut] = []
    for a in adolescents:
        for c in caregivers:
            d = stored.get((a, c))
            out.append(
                DyadOut(
                    adolescent_id=a,
                    caregiver_id=c,
                    decision=d.decision if d else "not_assessed",
                    note=d.note if d else None,
                    decided_at=d.decided_at if d else None,
                )
            )
    return out


@router.get("/families/{family_id}")
def get_family(family_id: uuid.UUID, user: StaffUser, db: Db) -> FamilyDetail:
    family = ensure_family(db, user, family_id)
    members = [
        MemberOut(
            user_id=m.user_id,
            pseudonym=m.user.pseudonym_code,
            display_alias=m.user.display_alias,
            role=m.member_role,
            relationship_label=m.relationship_label,
            onboarded=m.user.onboarded_at is not None,
            status=m.user.status.value,
        )
        for m in sorted(
            family.members,
            key=lambda m: (m.member_role is not Role.adolescent, m.user.display_alias),
        )
    ]
    audit_read(db, user, "family.read", target_type="family", target_id=family.id)
    return FamilyDetail(
        id=family.id,
        group_id=family.group_id,
        label=family.label,
        members=members,
        pending=[_pending_out(i) for i in _pending_invites(db, family.id)],
        dyads=_dyads(db, family),
    )


@router.post("/families/{family_id}/invitations", status_code=201)
def create_invitation(
    family_id: uuid.UUID, body: InviteIn, user: StaffUser, db: Db, settings: AppSettings
) -> IssuedCode:
    family = ensure_family(db, user, family_id)
    role = Role(body.role)
    if role is Role.adolescent:
        has_member = any(m.member_role is Role.adolescent for m in family.members)
        has_pending = any(
            i.intended_role is Role.adolescent for i in _pending_invites(db, family.id)
        )
        if has_member or has_pending:
            raise conflict("family.adolescent_exists")
    label = body.relationship_label.strip() if body.relationship_label else None
    inv, code = codes.issue(
        db,
        actor=user,
        purpose=CodePurpose.invite,
        role=role,
        family_id=family.id,
        relationship_label=label or None,
        ttl=timedelta(days=settings.invitation_ttl_days),
    )
    audit.record(
        db,
        "invitation.created",
        actor=user,
        target_type="invitation",
        target_id=inv.id,
        details={"role": role.value, "family_id": str(family.id)},
    )
    return IssuedCode(invitation_id=inv.id, code=code, expires_at=inv.expires_at)


@router.post("/invitations/{invitation_id}/revoke", status_code=204)
def revoke_invitation(invitation_id: uuid.UUID, user: StaffUser, db: Db) -> None:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.family_id is None or not codes.is_pending(inv):
        raise not_found()
    ensure_family(db, user, inv.family_id)
    inv.revoked_at = utcnow()
    audit.record(db, "invitation.revoked", actor=user, target_type="invitation", target_id=inv.id)


def _member(db: Db, family: Family, user_id: uuid.UUID) -> FamilyMember:
    m = next((m for m in family.members if m.user_id == user_id), None)
    if m is None:
        raise not_found()
    return m


@router.post("/families/{family_id}/members/{user_id}/reset-code", status_code=201)
def member_reset_code(
    family_id: uuid.UUID,
    user_id: uuid.UUID,
    therapist: TherapistUser,
    db: Db,
    settings: AppSettings,
) -> IssuedCode:
    family = ensure_family(db, therapist, family_id)
    member = _member(db, family, user_id)
    ensure_manages_user(db, therapist, member.user)
    inv, code = codes.issue(
        db,
        actor=therapist,
        purpose=CodePurpose.reset,
        role=member.member_role,
        target_user_id=member.user_id,
        ttl=timedelta(hours=settings.reset_code_ttl_hours),
    )
    audit.record(
        db, "reset_code.created", actor=therapist, target_type="user", target_id=member.user_id
    )
    return IssuedCode(invitation_id=inv.id, code=code, expires_at=inv.expires_at)


@router.put("/families/{family_id}/suitability")
def set_suitability(
    family_id: uuid.UUID, body: SuitabilityIn, therapist: TherapistUser, db: Db
) -> DyadOut:
    """Suitability for joint work is a clinical decision (Plan §5.8), so only therapists set it."""
    family = ensure_family(db, therapist, family_id)
    a = _member(db, family, body.adolescent_id)
    c = _member(db, family, body.caregiver_id)
    if a.member_role is not Role.adolescent or c.member_role is not Role.caregiver:
        raise bad_request("suitability.wrong_roles")
    row = db.execute(
        select(DyadSuitability).where(
            DyadSuitability.adolescent_id == a.user_id, DyadSuitability.caregiver_id == c.user_id
        )
    ).scalar_one_or_none()
    if row is None:
        row = DyadSuitability(family_id=family.id, adolescent_id=a.user_id, caregiver_id=c.user_id)
        db.add(row)
    row.decision = body.decision
    row.note = body.note.strip() if body.note else None
    row.decided_by = therapist.id
    row.decided_at = utcnow()
    db.flush()
    audit.record(
        db,
        "suitability.set",
        actor=therapist,
        target_type="family",
        target_id=family.id,
        details={"decision": body.decision.value},
    )
    return DyadOut(
        adolescent_id=a.user_id,
        caregiver_id=c.user_id,
        decision=row.decision,
        note=row.note,
        decided_at=row.decided_at,
    )
