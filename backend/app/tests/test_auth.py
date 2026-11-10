"""Login, lockout, sessions, CSRF, logout, password change (Plan §5.1; Phase 1 task 2)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import sessions
from app.core.security import (
    login_limiter,
    new_code,
    normalise_code,
    password_problems,
    username_valid,
)
from app.models import AuditLog, ResearchEvent, Role, UserStatus
from app.tests.factories import PASSWORD, World, login, make_user

NewClient = Callable[[], TestClient]

pytestmark = pytest.mark.db


# --- pure helpers ----------------------------------------------------------------------------


def test_password_policy() -> None:
    assert password_problems("short") == ["password.too_short"]
    assert "password.too_common" in password_problems("password123")
    assert "password.too_common" in password_problems("aaaaaaaaaaaa")
    assert "password.contains_username" in password_problems("xx-maple-tree-xx", username="maple")
    assert "password.too_long" in password_problems("a1" * 70)
    assert password_problems("calm-river-stone-42", username="maple") == []


def test_username_rules() -> None:
    assert username_valid("maple.tree_7-x")
    for bad in ("ab", "a" * 33, "Maple", "名字", "with space", "semi;colon"):
        assert not username_valid(bad), bad


def test_codes_are_high_entropy_and_normalise() -> None:
    codes = {new_code() for _ in range(200)}
    assert len(codes) == 200
    c = next(iter(codes))
    assert len(c) == 19 and c.count("-") == 3
    assert not set(c.replace("-", "")) & set("01ILO")
    assert normalise_code(c.lower().replace("-", " ")) == c


# --- login -----------------------------------------------------------------------------------


def test_login_sets_httponly_lax_cookie_and_records_events(
    client: TestClient, world: World, db: Session
) -> None:
    r = client.post(
        "/api/v1/auth/login", json={"username": world.t1.username.upper(), "password": PASSWORD}
    )
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "fb_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    body = r.json()
    assert body["user"]["role"] == "therapist" and body["csrf_token"]
    assert "password_hash" not in r.text
    events = db.execute(select(ResearchEvent.event_type)).scalars().all()
    assert events == ["login_success"]
    actions = db.execute(select(AuditLog.action).order_by(AuditLog.id.desc()).limit(1)).scalar()
    assert actions == "auth.login"


def test_bad_password_is_generic_and_recorded(
    client: TestClient, world: World, db: Session
) -> None:
    r1 = client.post("/api/v1/auth/login", json={"username": world.t1.username, "password": "x"})
    r2 = client.post("/api/v1/auth/login", json={"username": "nobody-here", "password": "x"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json() == {"detail": {"code": "auth.invalid_credentials"}}
    kinds = db.execute(select(ResearchEvent.event_type)).scalars().all()
    assert kinds == ["login_failure", "login_failure"]
    failed = db.execute(select(AuditLog).where(AuditLog.action == "auth.login_failed")).scalars()
    assert len(list(failed)) >= 2


def test_lockout_with_backoff(client: TestClient, world: World, db: Session) -> None:
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": world.t1.username, "password": "no"})
    # Locked now: even the right password is refused, with a retry hint.
    r = client.post(
        "/api/v1/auth/login", json={"username": world.t1.username, "password": PASSWORD}
    )
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "auth.too_many_attempts"
    assert 0 < r.json()["detail"]["retry_after"] <= 61
    db.refresh(world.t1)
    assert world.t1.locked_until is not None
    # After the lock expires, the right password works and the counter resets.
    world.t1.locked_until = sessions.utcnow() - timedelta(seconds=1)
    db.commit()
    login(client, world.t1)
    db.refresh(world.t1)
    assert world.t1.failed_logins == 0


def test_lockout_backoff_grows_and_is_capped() -> None:
    from app.api.auth import _lockout_seconds
    from app.settings import Settings

    s = Settings()
    assert _lockout_seconds(5, s) == 60
    assert _lockout_seconds(6, s) == 120
    assert _lockout_seconds(20, s) == 900


def test_ip_rate_limit(client: TestClient, world: World) -> None:
    login_limiter.reset()
    codes = [
        client.post("/api/v1/auth/login", json={"username": f"u{i}xx", "password": "x"}).status_code
        for i in range(31)
    ]
    assert codes[:30] == [401] * 30 and codes[30] == 429


def test_disabled_account_cannot_log_in(client: TestClient, world: World, db: Session) -> None:
    world.t2.status = UserStatus.disabled
    db.commit()
    r = client.post(
        "/api/v1/auth/login", json={"username": world.t2.username, "password": PASSWORD}
    )
    assert r.status_code == 401


# --- sessions --------------------------------------------------------------------------------


def test_session_endpoint(client: TestClient, world: World) -> None:
    assert client.get("/api/v1/auth/session").json() == {"user": None, "csrf_token": None}
    token = login(client, world.f1.teen)
    body = client.get("/api/v1/auth/session").json()
    assert body["user"]["id"] == str(world.f1.teen.id) and body["csrf_token"] == token


def test_csrf_required_on_unsafe_methods(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    good = client.headers.pop("X-CSRF-Token")
    r = client.patch("/api/v1/me", json={"language": "zh-CN"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "auth.csrf_failed"
    r = client.patch("/api/v1/me", json={"language": "zh-CN"}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    r = client.patch("/api/v1/me", json={"language": "zh-CN"}, headers={"X-CSRF-Token": good})
    assert r.status_code == 200 and r.json()["language"] == "zh-CN"


def test_idle_timeout(client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client, world.f1.teen)
    assert client.get("/api/v1/me").status_code == 200
    later = sessions.utcnow() + timedelta(minutes=31)
    monkeypatch.setattr(sessions, "utcnow", lambda: later)
    assert client.get("/api/v1/me").status_code == 401


def test_activity_extends_idle_window(
    client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, world.f1.teen)
    t0 = sessions.utcnow()
    for minutes in (20, 40, 60):
        now = t0 + timedelta(minutes=minutes)
        monkeypatch.setattr(sessions, "utcnow", lambda now=now: now)
        assert client.get("/api/v1/me").status_code == 200


def test_absolute_timeout(
    client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, world.f1.teen)
    t0 = sessions.utcnow()
    # Keep the session busy every 20 minutes; it still ends at 12 hours.
    for minutes in range(20, 12 * 60, 20):
        now = t0 + timedelta(minutes=minutes)
        monkeypatch.setattr(sessions, "utcnow", lambda now=now: now)
        assert client.get("/api/v1/me").status_code == 200
    end = t0 + timedelta(hours=12, minutes=1)
    monkeypatch.setattr(sessions, "utcnow", lambda: end)
    assert client.get("/api/v1/me").status_code == 401


def test_logout_revokes_session(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    cookie = client.cookies.get("fb_session")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("fb_session", cookie or "")
    assert client.get("/api/v1/me").status_code == 401


def test_logout_everywhere(client: TestClient, new_client: NewClient, world: World) -> None:
    other = new_client()
    login(client, world.f1.teen)
    login(other, world.f1.teen)
    assert client.post("/api/v1/auth/logout-all").status_code == 204
    assert other.get("/api/v1/me").status_code == 401


def test_password_change_keeps_this_session_only(
    client: TestClient, new_client: NewClient, world: World
) -> None:
    other = new_client()
    login(client, world.f1.teen)
    login(other, world.f1.teen)
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": "wrong-one-xx", "new_password": "new-quiet-lake-77"},
    )
    assert r.json()["detail"]["code"] == "password.current_wrong"
    r = client.post(
        "/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert r.json()["detail"] == {"code": "password.invalid", "problems": ["password.too_short"]}
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "new-quiet-lake-77"},
    )
    assert r.status_code == 204
    assert client.get("/api/v1/me").status_code == 200
    assert other.get("/api/v1/me").status_code == 401
    login(other, world.f1.teen, "new-quiet-lake-77")


def test_username_unique_case_insensitive(db: Session, world: World) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        make_user(db, Role.caregiver, username=world.t1.username.upper())
    db.rollback()
