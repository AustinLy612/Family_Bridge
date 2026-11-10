"""Request dependencies: DB session, current user, role gates, onboarding gate, CSRF.

Every non-public endpoint depends on `require_user` (or a role gate built on it). Unsafe methods
(POST/PUT/PATCH/DELETE) on authenticated endpoints must carry the session's CSRF token.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import forbidden, unauthorized
from app.core.sessions import COOKIE_NAME, CSRF_HEADER, resolve_session
from app.models import AuthSession, Role, User, UserStatus
from app.settings import Settings

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    factory = sessionmaker(bind=request.app.state.engine_factory(), expire_on_commit=False)
    with factory() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


Db = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]


@dataclass(frozen=True)
class Principal:
    user: User
    session: AuthSession


def current_principal(request: Request, db: Db, settings: AppSettings) -> Principal | None:
    sess = resolve_session(db, request.cookies.get(COOKIE_NAME), settings)
    if sess is None:
        return None
    user = db.get(User, sess.user_id)
    if user is None or user.status is not UserStatus.active:
        return None
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(sent, sess.csrf_token):
            raise forbidden("auth.csrf_failed")
    return Principal(user, sess)


OptionalPrincipal = Annotated[Principal | None, Depends(current_principal)]


def require_principal(principal: OptionalPrincipal) -> Principal:
    if principal is None:
        raise unauthorized()
    return principal


AuthPrincipal = Annotated[Principal, Depends(require_principal)]


def require_user(principal: AuthPrincipal) -> User:
    return principal.user


def require_onboarded(user: Annotated[User, Depends(require_user)]) -> User:
    """Participants cannot use the app until onboarding consent is complete (Plan §5.2)."""
    if user.onboarded_at is None:
        raise forbidden("onboarding.required")
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = frozenset(roles)

    def gate(request: Request, db: Db, user: Annotated[User, Depends(require_onboarded)]) -> User:
        if user.role not in allowed:
            from app.core.policy import deny

            route = request.scope.get("route")
            path = str(getattr(route, "path", request.url.path))[:64]
            raise deny(db, user, target_type="route", target_id=path, reason="role")
        return user

    return gate


CurrentUser = Annotated[User, Depends(require_user)]
OnboardedUser = Annotated[User, Depends(require_onboarded)]
AdminUser = Annotated[User, Depends(require_roles(Role.admin))]
TherapistUser = Annotated[User, Depends(require_roles(Role.therapist))]
StaffUser = Annotated[User, Depends(require_roles(Role.therapist, Role.admin))]
