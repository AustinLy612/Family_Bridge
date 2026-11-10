"""The signed-in user's own account, consent and "who can see my data".

Plan §5.2; Phase 1 task 7.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, Db, OnboardedUser
from app.api.schemas import ConsentChange, ConsentState, MePatch, UserOut, Viewer, VisibilityOut
from app.content.loader import ContentBundle
from app.core import audit
from app.core.errors import bad_request, not_found
from app.models import ConsentRecord, FamilyMember, GroupTherapist, Role, User, UserStatus
from app.services import consent as consent_svc

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("")
def get_me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)


@router.patch("")
def patch_me(body: MePatch, user: CurrentUser, db: Db) -> UserOut:
    changed: list[str] = []
    if body.display_alias is not None:
        user.display_alias = body.display_alias.strip()
        changed.append("display_alias")
    if body.language is not None:
        user.language = body.language
        changed.append("language")
    if body.a11y_prefs is not None:
        user.a11y_prefs = body.a11y_prefs.model_dump()
        changed.append("a11y_prefs")
    if changed:
        audit.record(
            db,
            "user.updated_self",
            actor=user,
            target_type="user",
            target_id=user.id,
            details={"fields": changed},
        )
    return UserOut.of(user)


def _family_peers(db: Db, user: User) -> tuple[list[User], list[User]]:
    """(other family members, assigned therapists) for a participant."""
    me = db.execute(
        select(FamilyMember).where(FamilyMember.user_id == user.id)
    ).scalar_one_or_none()
    if me is None:
        return [], []
    peers = [
        m.user
        for m in me.family.members
        if m.user_id != user.id and m.user.status is UserStatus.active
    ]
    therapists = list(
        db.execute(
            select(User)
            .join(GroupTherapist, GroupTherapist.therapist_id == User.id)
            .where(GroupTherapist.group_id == me.family.group_id, User.status == UserStatus.active)
            .order_by(User.display_alias)
        ).scalars()
    )
    return peers, therapists


@router.get("/visibility")
def visibility(user: OnboardedUser, db: Db) -> VisibilityOut:
    viewers: list[Viewer] = [Viewer(kind="self", sees=["visibility.sees.everything_own"])]
    if user.is_participant:
        peers, therapists = _family_peers(db, user)
        for t in therapists:
            viewers.append(
                Viewer(
                    kind="assigned_therapist",
                    alias=t.display_alias,
                    role=Role.therapist,
                    sees=[
                        "visibility.sees.diary_cards",
                        "visibility.sees.lessons_progress",
                        "visibility.sees.safety_events",
                    ],
                )
            )
        for p in peers:
            viewers.append(
                Viewer(
                    kind="family_member",
                    alias=p.display_alias,
                    role=p.role,
                    sees=[
                        "visibility.sees.only_what_you_share",
                        "visibility.sees.joint_shared_steps",
                    ],
                )
            )
        viewers.append(Viewer(kind="admin", sees=["visibility.sees.account_only"]))
        viewers.append(
            Viewer(kind="ai_provider", sees=["visibility.sees.pseudonymous_lesson_text"])
        )
        if consent_svc.has_granted(db, user, "research_export"):
            viewers.append(Viewer(kind="research", sees=["visibility.sees.pseudonymous_usage"]))
    else:
        viewers.append(Viewer(kind="admin", sees=["visibility.sees.account_only"]))
    return VisibilityOut(viewers=viewers)


@router.get("/consent")
def get_consent(user: OnboardedUser, db: Db, request: Request) -> list[ConsentState]:
    content: ContentBundle = request.app.state.content
    doc = content.consent(user.language) or content.consent("en")
    recs = consent_svc.current(db, user)
    if doc is None:
        return []
    return [
        ConsentState(
            category=c.id,
            required=c.required,
            granted=bool(recs.get(c.id) and recs[c.id].granted),
            recorded_at=recs[c.id].recorded_at if c.id in recs else None,
        )
        for c in doc.categories
    ]


@router.put("/consent/{category}")
def change_consent(
    category: str, body: ConsentChange, user: OnboardedUser, db: Db, request: Request
) -> list[ConsentState]:
    """Change an optional consent (D32: research export). Required consents are changed by
    talking to the therapist (O5), so the API refuses them."""
    content: ContentBundle = request.app.state.content
    doc = content.consent(user.language) or content.consent("en")
    cat = doc.category(category) if doc else None
    if doc is None or cat is None or not user.is_participant:
        raise not_found()
    if cat.required:
        raise bad_request("consent.required_contact_therapist")
    # Record only the changed category, against the current document version.
    db.add(
        ConsentRecord(
            user_id=user.id,
            document_id=doc.id,
            document_version=doc.version,
            document_sha256=content.consent_sha256(doc),
            category=cat.id,
            grantee=cat.grantee,
            granted=body.granted,
        )
    )
    db.flush()
    audit.record(
        db,
        "consent.changed",
        actor=user,
        target_type="consent",
        target_id=cat.id,
        details={"granted": body.granted, "version": doc.version},
    )
    return get_consent(user, db, request)
