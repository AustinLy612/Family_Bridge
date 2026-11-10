"""Server-side sessions in HTTP-only cookies, CSRF tokens, idle/absolute timeouts.

Plan §3.1, §5.1.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.crypto import code_digest
from app.core.security import new_token
from app.models import AuthSession, User
from app.settings import Settings

COOKIE_NAME = "fb_session"
CSRF_HEADER = "X-CSRF-Token"


def utcnow() -> datetime:
    """Single clock for auth logic (tests monkeypatch this)."""
    return datetime.now(UTC)


def create_session(db: Session, user: User, settings: Settings) -> tuple[str, AuthSession]:
    token = new_token()
    now = utcnow()
    sess = AuthSession(
        token_digest=code_digest("session:" + token),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(sess)
    db.flush()
    return token, sess


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.cookie_secure, samesite="lax")


def resolve_session(db: Session, token: str | None, settings: Settings) -> AuthSession | None:
    """Return the live session for a cookie token, enforcing idle and absolute expiry."""
    if not token:
        return None
    sess = db.execute(
        select(AuthSession).where(AuthSession.token_digest == code_digest("session:" + token))
    ).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None:
        return None
    now = utcnow()
    idle_limit = sess.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if now >= sess.expires_at or now >= idle_limit:
        sess.revoked_at = now
        db.flush()
        return None
    sess.last_seen_at = now
    return sess


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
