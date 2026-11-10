"""Onboarding consent cannot be skipped; per-category consent records (Plan §5.2; D31, D32)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConsentRecord
from app.tests.factories import Fam, World, login, make_family

NewClient = Callable[[], TestClient]

pytestmark = pytest.mark.db

ALL_YES = {
    "platform_terms": True,
    "therapist_access": True,
    "ai_provider_processing": True,
    "research_export": True,
}


@pytest.fixture
def fresh(db: Session, world: World) -> Fam:
    fam = make_family(db, world.g1, onboarded=False)
    db.commit()
    return fam


def test_onboarding_document_in_both_languages(client: TestClient, fresh: Fam) -> None:
    login(client, fresh.teen)
    en = client.get("/api/v1/onboarding?language=en").json()
    zh = client.get("/api/v1/onboarding?language=zh-CN").json()
    assert en["completed"] is False
    assert en["document"]["approval"] == "draft"
    assert [c["id"] for c in en["document"]["categories"]] == [
        c["id"] for c in zh["document"]["categories"]
    ]
    research = next(c for c in en["document"]["categories"] if c["id"] == "research_export")
    assert research["required"] is False and research["default"] is True  # D32
    text = " ".join(
        b.get("text") or " ".join(b["items"])
        for s in en["document"]["sections"]
        for b in s["blocks"]
    )
    assert "not a crisis service" in text and "DeepSeek" in text
    assert "help" in en


@pytest.mark.parametrize(
    "path",
    ["/api/v1/me/visibility", "/api/v1/me/consent"],
)
def test_onboarding_cannot_be_skipped(client: TestClient, fresh: Fam, path: str) -> None:
    login(client, fresh.carers[0])
    r = client.get(path)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "onboarding.required"


def test_declining_required_consent_blocks_onboarding(
    client: TestClient,
    fresh: Fam,
    db: Session,
) -> None:
    login(client, fresh.teen)
    body = {"version": 1, "language": "en", "decisions": ALL_YES | {"therapist_access": False}}
    r = client.post("/api/v1/onboarding/accept", json=body)
    assert r.status_code == 400
    assert r.json()["detail"] == {
        "code": "consent.required_declined",
        "categories": ["therapist_access"],
    }
    assert client.get("/api/v1/me").json()["onboarded"] is False
    assert db.execute(select(ConsentRecord)).first() is None


def test_incomplete_or_stale_decisions_rejected(client: TestClient, fresh: Fam) -> None:
    login(client, fresh.teen)
    partial = {k: v for k, v in ALL_YES.items() if k != "research_export"}
    r = client.post(
        "/api/v1/onboarding/accept", json={"version": 1, "language": "en", "decisions": partial}
    )
    assert r.json()["detail"]["code"] == "consent.decisions_incomplete"
    r = client.post(
        "/api/v1/onboarding/accept", json={"version": 99, "language": "en", "decisions": ALL_YES}
    )
    assert r.json()["detail"]["code"] == "consent.version_changed"


def test_accept_records_each_category_with_version(
    client: TestClient,
    fresh: Fam,
    db: Session,
) -> None:
    login(client, fresh.teen)
    body = {"version": 1, "language": "zh-CN", "decisions": ALL_YES | {"research_export": False}}
    r = client.post("/api/v1/onboarding/accept", json=body)
    assert r.status_code == 200 and r.json()["onboarded"] is True
    recs = (
        db.execute(select(ConsentRecord).where(ConsentRecord.user_id == fresh.teen.id))
        .scalars()
        .all()
    )
    assert {r.category: r.granted for r in recs} == body["decisions"]
    assert all(r.document_version == 1 and len(r.document_sha256) == 64 for r in recs)
    assert client.post("/api/v1/onboarding/accept", json=body).status_code == 409
    assert client.get("/api/v1/me/visibility").status_code == 200


def test_research_consent_changeable_required_not(client: TestClient, fresh: Fam) -> None:
    login(client, fresh.teen)
    client.post(
        "/api/v1/onboarding/accept", json={"version": 1, "language": "en", "decisions": ALL_YES}
    )
    states = {s["category"]: s["granted"] for s in client.get("/api/v1/me/consent").json()}
    assert states["research_export"] is True
    r = client.put("/api/v1/me/consent/research_export", json={"granted": False})
    assert {s["category"]: s["granted"] for s in r.json()}["research_export"] is False
    kinds = [v["kind"] for v in client.get("/api/v1/me/visibility").json()["viewers"]]
    assert "research" not in kinds
    r = client.put("/api/v1/me/consent/therapist_access", json={"granted": False})
    assert r.json()["detail"]["code"] == "consent.required_contact_therapist"


def test_staff_have_no_participant_onboarding(client: TestClient, world: World) -> None:
    login(client, world.t1)
    assert client.get("/api/v1/onboarding").status_code == 403


def test_visibility_lists_real_viewers(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    viewers = client.get("/api/v1/me/visibility").json()["viewers"]
    therapists = [v["alias"] for v in viewers if v["kind"] == "assigned_therapist"]
    family = [v for v in viewers if v["kind"] == "family_member"]
    assert therapists == [world.t1.display_alias]
    assert {v["alias"] for v in family} == {c.display_alias for c in world.f1.carers}
    assert all(
        v["sees"] == ["visibility.sees.only_what_you_share", "visibility.sees.joint_shared_steps"]
        for v in family
    )
    assert world.t2.display_alias not in str(viewers)


def test_public_help_reachable_signed_out(client: TestClient, world: World) -> None:
    r = client.get("/api/v1/site/help")
    assert r.status_code == 200 and r.json()["placeholder"] is True


def test_account_settings_saved_on_server(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    prefs = {
        "reduceMotion": True,
        "highContrast": True,
        "calmPalette": False,
        "textScale": 1.5,
        "sound": False,
        "showIllustrations": None,
    }
    r = client.patch(
        "/api/v1/me", json={"a11y_prefs": prefs, "language": "zh-CN", "display_alias": "Fern"}
    )
    assert r.status_code == 200
    me = client.get("/api/v1/me").json()
    assert me["a11y_prefs"] == prefs and me["language"] == "zh-CN" and me["display_alias"] == "Fern"
    bad = client.patch("/api/v1/me", json={"a11y_prefs": prefs | {"textScale": 3}})
    assert bad.status_code == 422
    assert client.patch("/api/v1/me", json={"role": "admin"}).status_code == 422
