"""Participant onboarding consent (Plan §5.2; Phase 1 task 5). It cannot be skipped: every
participant feature depends on `require_onboarded`, which only this endpoint satisfies."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import CurrentUser, Db
from app.api.schemas import (
    ConsentCategoryOut,
    Language,
    OnboardingAccept,
    OnboardingDoc,
    OnboardingOut,
    SiteHelp,
    UserOut,
)
from app.content.loader import ContentBundle
from app.content.models import ConsentDocument
from app.core import audit
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.sessions import utcnow
from app.models import User
from app.research import events as research_events
from app.services import consent as consent_svc
from app.services.site import site_help

router = APIRouter(prefix="/api/v1", tags=["onboarding"])


def _doc(request: Request, language: str) -> tuple[ConsentDocument, str]:
    content: ContentBundle = request.app.state.content
    doc = content.consent(language)
    if doc is None:
        raise not_found("consent.missing")
    return doc, content.consent_sha256(doc)


def _doc_out(doc: ConsentDocument) -> OnboardingDoc:
    return OnboardingDoc(
        document_id=doc.id,
        version=doc.version,
        language=doc.language,
        approval=doc.approval.status.value,
        sections=[s.model_dump() for s in doc.sections],
        categories=[ConsentCategoryOut(**c.model_dump()) for c in doc.categories],
    )


def _participant(user: User) -> User:
    if not user.is_participant:
        raise forbidden("onboarding.participants_only")
    return user


@router.get("/onboarding")
def get_onboarding(
    request: Request,
    user: CurrentUser,
    db: Db,
    language: Annotated[Language | None, Query()] = None,
) -> OnboardingOut:
    _participant(user)
    doc, _ = _doc(request, language or user.language)
    return OnboardingOut(
        completed=user.onboarded_at is not None, document=_doc_out(doc), help=site_help(db)
    )


@router.post("/onboarding/accept")
def accept(body: OnboardingAccept, request: Request, user: CurrentUser, db: Db) -> UserOut:
    _participant(user)
    if user.onboarded_at is not None:
        raise conflict("onboarding.already_completed")
    doc, sha = _doc(request, body.language)
    if doc.version != body.version:
        raise bad_request("consent.version_changed")
    if user.role.value not in doc.roles:
        raise forbidden("onboarding.participants_only")
    ids = {c.id for c in doc.categories}
    if set(body.decisions) != ids:
        raise bad_request("consent.decisions_incomplete")
    declined = [c.id for c in doc.categories if c.required and not body.decisions[c.id]]
    if declined:
        # O5: declining is not yet defined clinically, so onboarding stops here and the
        # participant is asked to talk to their therapist. Nothing is recorded.
        raise bad_request("consent.required_declined", categories=declined)

    consent_svc.write(db, user, doc, sha, body.decisions)
    user.onboarded_at = utcnow()
    research_events.record(db, "enrolment.onboarded", user)
    audit.record(
        db,
        "onboarding.completed",
        actor=user,
        target_type="consent",
        target_id=f"{doc.id}:v{doc.version}:{doc.language}",
        details={"decisions": body.decisions},
    )
    return UserOut.of(user)


@router.get("/site/help")
def public_help(db: Db) -> SiteHelp:
    """Help contacts and service hours are public: reachable even when signed out."""
    return site_help(db)
