"""Invitation codes, redemption, staff-issued reset codes (Plan §5.1; D29, D30)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sessions import utcnow
from app.models import AuditLog, Family, FamilyMember, Invitation, User
from app.tests.factories import PASSWORD, World, login

NewClient = Callable[[], TestClient]

pytestmark = pytest.mark.db

NEW_PW = "bright-maple-leaf-9"


def _invite(
    client: TestClient, world: World, role: str = "caregiver", family: Family | None = None
) -> str:
    login(client, world.t1)
    fam = family or world.f1.family
    r = client.post(f"/api/v1/families/{fam.id}/invitations", json={"role": role})
    assert r.status_code == 201, r.text
    client.post("/api/v1/auth/logout")
    client.headers.pop("X-CSRF-Token", None)
    code: str = r.json()["code"]
    return code


def _redeem(client: TestClient, code: str, username: str = "new-carer", **kw: str) -> Response:
    body = {
        "code": code,
        "username": username,
        "display_alias": "Willow",
        "language": "en",
        "password": NEW_PW,
    } | kw
    r: Response = client.post("/api/v1/auth/redeem", json=body)
    return r


def test_code_is_stored_only_as_digest(client: TestClient, world: World, db: Session) -> None:
    code = _invite(client, world)
    stored = db.execute(select(Invitation.code_digest)).scalars().all()
    assert stored and all(code not in s and code.replace("-", "") not in s for s in stored)


def test_inspect_and_redeem_creates_unonboarded_member(
    client: TestClient, world: World, db: Session
) -> None:
    code = _invite(client, world)
    info = client.post("/api/v1/auth/codes/inspect", json={"code": code.lower()}).json()
    assert info["purpose"] == "invite" and info["role"] == "caregiver"
    r = _redeem(client, code.replace("-", " "))
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["role"] == "caregiver" and user["onboarded"] is False
    member = db.execute(select(FamilyMember).where(FamilyMember.user_id == user["id"])).scalar_one()
    assert member.family_id == world.f1.family.id
    assert client.get("/api/v1/auth/session").json()["user"]["username"] == "new-carer"


def test_invitation_single_use(client: TestClient, world: World) -> None:
    code = _invite(client, world)
    assert _redeem(client, code).status_code == 200
    client.cookies.clear()
    r = _redeem(client, code, username="second-try")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "code.invalid"
    assert client.post("/api/v1/auth/codes/inspect", json={"code": code}).status_code == 400


def test_invitation_expires(client: TestClient, world: World, db: Session) -> None:
    code = _invite(client, world)
    inv = db.execute(select(Invitation)).scalar_one()
    inv.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert _redeem(client, code).json()["detail"]["code"] == "code.invalid"


def test_default_expiry_is_14_days(client: TestClient, world: World) -> None:
    login(client, world.t1)
    r = client.post(
        f"/api/v1/families/{world.f1.family.id}/invitations", json={"role": "caregiver"}
    )
    from datetime import datetime

    expires = datetime.fromisoformat(r.json()["expires_at"])
    assert timedelta(days=13, hours=23) < expires - utcnow() <= timedelta(days=14)


def test_revoked_invitation_cannot_be_used(client: TestClient, world: World, db: Session) -> None:
    code = _invite(client, world)
    inv = db.execute(select(Invitation)).scalar_one()
    login(client, world.t1)
    assert client.post(f"/api/v1/invitations/{inv.id}/revoke").status_code == 204
    client.post("/api/v1/auth/logout")
    assert _redeem(client, code).status_code == 400


def test_one_adolescent_per_family(client: TestClient, world: World) -> None:
    login(client, world.t1)
    r = client.post(
        f"/api/v1/families/{world.f1.family.id}/invitations", json={"role": "adolescent"}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "family.adolescent_exists"
    fam = client.post(f"/api/v1/groups/{world.g1.id}/families", json={"label": "New"}).json()
    ok = client.post(f"/api/v1/families/{fam['id']}/invitations", json={"role": "adolescent"})
    assert ok.status_code == 201
    again = client.post(f"/api/v1/families/{fam['id']}/invitations", json={"role": "adolescent"})
    assert again.status_code == 409  # a pending adolescent invitation counts too


def test_redeem_validates_username_and_password(client: TestClient, world: World) -> None:
    code = _invite(client, world)
    assert _redeem(client, code, username="名字").json()["detail"]["code"] == "username.invalid"
    r = _redeem(client, code, password="short")
    assert r.json()["detail"]["code"] == "password.invalid"
    r = _redeem(client, code, username=world.f1.teen.username.upper())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "username.taken"
    assert _redeem(client, code).status_code == 200  # the code survived the failed attempts


def test_therapist_invite_creates_onboarded_staff(client: TestClient, world: World) -> None:
    login(client, world.admin)
    code = client.post("/api/v1/admin/therapists").json()["code"]
    client.post("/api/v1/auth/logout")
    r = _redeem(client, code, username="dr-new")
    assert r.json()["user"]["role"] == "therapist" and r.json()["user"]["onboarded"] is True


def test_code_rate_limit(client: TestClient, world: World) -> None:
    results = [
        client.post("/api/v1/auth/codes/inspect", json={"code": "AAAA-BBBB-CCCC-DDDD"}).status_code
        for _ in range(21)
    ]
    assert results[:20] == [400] * 20 and results[20] == 429


# --- reset codes (D30) -----------------------------------------------------------------------


def test_therapist_resets_participant_in_own_group(
    client: TestClient,
    new_client: NewClient,
    world: World,
    db: Session,
) -> None:
    teen_browser = new_client()
    login(teen_browser, world.f1.teen)
    login(client, world.t1)
    r = client.post(f"/api/v1/families/{world.f1.family.id}/members/{world.f1.teen.id}/reset-code")
    assert r.status_code == 201
    code = r.json()["code"]
    anon = new_client()
    info = anon.post("/api/v1/auth/codes/inspect", json={"code": code}).json()
    assert info["purpose"] == "reset" and info["username"] == world.f1.teen.username
    assert (
        anon.post("/api/v1/auth/reset", json={"code": code, "password": NEW_PW}).status_code == 204
    )
    # Signed out everywhere; old password gone; code single-use.
    assert teen_browser.get("/api/v1/me").status_code == 401
    bad = anon.post(
        "/api/v1/auth/login", json={"username": world.f1.teen.username, "password": PASSWORD}
    )
    assert bad.status_code == 401
    login(anon, world.f1.teen, NEW_PW)
    again = new_client().post("/api/v1/auth/reset", json={"code": code, "password": NEW_PW})
    assert again.status_code == 400
    assert db.execute(select(AuditLog).where(AuditLog.action == "auth.password_reset")).first()


def test_newer_reset_code_replaces_older(client: TestClient, world: World) -> None:
    login(client, world.t1)
    url = f"/api/v1/families/{world.f1.family.id}/members/{world.f1.teen.id}/reset-code"
    first = client.post(url).json()["code"]
    second = client.post(url).json()["code"]
    assert client.post("/api/v1/auth/codes/inspect", json={"code": first}).status_code == 400
    assert client.post("/api/v1/auth/codes/inspect", json={"code": second}).status_code == 200


def test_reset_code_not_valid_as_invitation(client: TestClient, world: World) -> None:
    login(client, world.t1)
    url = f"/api/v1/families/{world.f1.family.id}/members/{world.f1.teen.id}/reset-code"
    code = client.post(url).json()["code"]
    assert _redeem(client, code).json()["detail"]["code"] == "code.invalid"


def test_therapist_cannot_reset_outside_group(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.t1)
    r = client.post(f"/api/v1/families/{world.f2.family.id}/members/{world.f2.teen.id}/reset-code")
    assert r.status_code == 403
    denied = (
        db.execute(
            select(AuditLog).where(AuditLog.action == "access.denied").order_by(AuditLog.id.desc())
        )
        .scalars()
        .first()
    )
    assert denied is not None and denied.actor_id == world.t1.id


def test_admin_resets_therapist_not_participant(client: TestClient, world: World) -> None:
    login(client, world.admin)
    assert client.post(f"/api/v1/admin/therapists/{world.t1.id}/reset-code").status_code == 201
    r = client.post(f"/api/v1/families/{world.f1.family.id}/members/{world.f1.teen.id}/reset-code")
    assert r.status_code == 403  # participant resets go through their therapist (D30)
    assert client.post(f"/api/v1/admin/therapists/{world.f1.teen.id}/reset-code").status_code == 404


def test_disabling_therapist_signs_them_out(
    client: TestClient, new_client: NewClient, world: World, db: Session
) -> None:
    t = new_client()
    login(t, world.t2)
    login(client, world.admin)
    r = client.put(f"/api/v1/admin/therapists/{world.t2.id}/status", json={"status": "disabled"})
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert t.get("/api/v1/me").status_code == 401
    assert db.get(User, world.t2.id) is not None


def test_relationship_label_encrypted_at_rest(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.t1)
    client.post(
        f"/api/v1/families/{world.f1.family.id}/invitations",
        json={"role": "caregiver", "relationship_label": "aunt"},
    )
    from sqlalchemy import text

    raw = db.execute(text("SELECT relationship_label FROM invitation")).scalar_one()
    assert raw.startswith("v1:") and "aunt" not in raw
    assert db.execute(select(Invitation.relationship_label)).scalar_one() == "aunt"
