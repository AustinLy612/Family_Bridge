"""Safety queue and help-screen API (Plan §4.2, §5.7; Phase 2 tasks 3, 5, 6).

- Participants never see safety events; they only get the (public) help screen.
- Therapists see and update events for their own groups' families only.
- Admins read everything, including excerpts and notes, and cannot change anything (D39).
- Reads and denials are audited.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import load_content
from app.models import AuditLog, SafetyEvent
from app.safety.service import Context, SafetyService
from app.settings import get_settings
from app.tests.factories import World, login

pytestmark = pytest.mark.db


def _flag(db: Session, user, text: str = "I want to die", ref: str | None = None) -> str:  # type: ignore[no-untyped-def]
    s = get_settings()
    out = SafetyService(load_content(s.content_dir), s).screen_text(
        db, user, Context.lesson, text, source_ref=ref
    )
    db.commit()
    assert out.event_id
    return out.event_id


def _last_audit(db: Session) -> AuditLog:
    return db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()


# --- help screen ------------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["zh-CN", "en"])
def test_help_page_is_public_and_bilingual(client: TestClient, world: World, lang: str) -> None:
    r = client.get(f"/api/v1/help?language={lang}")
    assert r.status_code == 200
    body = r.json()
    assert body["document"]["language"] == lang and body["document"]["approval"] == "draft"
    assert body["document"]["stop_notice"]["title"] and body["document"]["care_card"]["body"]
    assert body["site"]["placeholder"] is True  # contacts unconfirmed (O4)


def test_help_page_rejects_unknown_language(client: TestClient) -> None:
    assert client.get("/api/v1/help?language=fr").status_code == 422


# --- participants -----------------------------------------------------------------------------


def test_participants_cannot_reach_safety_events(
    client: TestClient, world: World, db: Session
) -> None:
    own = _flag(db, world.f1.teen)
    for user in (world.f1.teen, world.f1.carers[0]):
        login(client, user)
        for method, url in [
            ("GET", "/api/v1/safety/events"),
            ("GET", f"/api/v1/safety/events/{own}"),
            ("POST", f"/api/v1/safety/events/{own}/status"),
            ("POST", f"/api/v1/safety/events/{own}/notes"),
            ("GET", "/api/v1/safety/subjects"),
            ("POST", "/api/v1/safety/events"),
        ]:
            r = client.request(method, url, json={})
            assert r.status_code == 403, (user.role, method, url, r.status_code)
            assert "I want to die" not in r.text


# --- therapists -------------------------------------------------------------------------------


def test_therapist_sees_only_own_families(client: TestClient, world: World, db: Session) -> None:
    mine = _flag(db, world.f1.teen)
    theirs = _flag(db, world.f2.teen)
    login(client, world.t1)
    r = client.get("/api/v1/safety/events")
    assert r.status_code == 200
    assert [e["id"] for e in r.json()["events"]] == [mine]
    assert r.json()["counts"] == {"new": 1, "open": 1}
    assert _last_audit(db).action == "safety.queue_read"

    for method, url, body in [
        ("GET", f"/api/v1/safety/events/{theirs}", None),
        ("POST", f"/api/v1/safety/events/{theirs}/status", {"status": "acknowledged"}),
        ("POST", f"/api/v1/safety/events/{theirs}/notes", {"body": "x"}),
    ]:
        r = client.request(method, url, json=body)
        assert r.status_code == 403, (method, url)
        assert "I want to die" not in r.text and str(world.f2.teen.id) not in r.text
        row = _last_audit(db)
        assert row.action == "access.denied" and row.details == {"reason": "not_assigned"}
    assert db.get(SafetyEvent, theirs).status.value == "new"  # type: ignore[union-attr]


def test_therapist_detail_and_workflow(client: TestClient, world: World, db: Session) -> None:
    eid = _flag(db, world.f1.teen, "我想自杀")
    login(client, world.t1)
    d = client.get(f"/api/v1/safety/events/{eid}").json()
    assert d["excerpt"] == "我想自杀" and d["matched_terms"] == ["自杀"]
    assert d["next_statuses"] == ["acknowledged"] and d["subject"]["role"] == "adolescent"
    assert d["family"]["label"] == world.f1.family.label
    row = _last_audit(db)
    assert row.action == "safety.event_read" and row.target_id == eid

    d = client.post(f"/api/v1/safety/events/{eid}/status", json={"status": "acknowledged"}).json()
    assert d["status"] == "acknowledged" and d["assignee"]["id"] == str(world.t1.id)
    assert d["next_statuses"] == ["in_review", "resolved"]
    d = client.post(f"/api/v1/safety/events/{eid}/notes", json={"body": "Spoke with the teen."})
    assert d.status_code == 201 and d.json()["notes"][0]["body"] == "Spoke with the teen."
    r = client.post(f"/api/v1/safety/events/{eid}/status", json={"status": "resolved"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "safety.follow_up_required"
    d = client.post(
        f"/api/v1/safety/events/{eid}/status",
        json={"status": "resolved", "follow_up": "Safety plan reviewed in person."},
    ).json()
    assert d["status"] == "resolved" and d["follow_up"] == "Safety plan reviewed in person."
    assert [t["status"] for t in d["timeline"]] == ["new", "acknowledged", "resolved"]
    assert d["next_statuses"] == []
    r = client.post(f"/api/v1/safety/events/{eid}/status", json={"status": "in_review"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "safety.transition_invalid"

    assert client.get("/api/v1/safety/events").json()["events"] == []
    assert [
        e["id"] for e in client.get("/api/v1/safety/events?status=resolved").json()["events"]
    ] == [eid]


def test_queue_order_puts_new_and_severe_first(
    client: TestClient, world: World, db: Session
) -> None:
    medium = _flag(db, world.f1.teen, "I feel hopeless", ref="a")
    high = _flag(db, world.f1.carers[0], "I want to die", ref="b")
    acked = _flag(db, world.f1.carers[1], "I want to die", ref="c")
    login(client, world.t1)
    client.post(f"/api/v1/safety/events/{acked}/status", json={"status": "acknowledged"})
    ids = [e["id"] for e in client.get("/api/v1/safety/events").json()["events"]]
    assert ids == [high, medium, acked]


def test_manual_event_creation(client: TestClient, world: World, db: Session) -> None:
    login(client, world.t1)
    subjects = client.get("/api/v1/safety/subjects").json()
    assert {s["user"]["id"] for s in subjects} == {
        str(u.id) for u in [world.f1.teen, *world.f1.carers]
    }
    r = client.post(
        "/api/v1/safety/events",
        json={
            "subject_user_id": str(world.f1.teen.id),
            "category": "suspected_abuse",
            "severity": "high",
            "description": "Raised in group; follow up with the safeguarding lead.",
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["source"] == "manual" and d["channel"] == "manual"
    assert d["created_by"]["id"] == str(world.t1.id) and d["status"] == "new"
    assert d["excerpt"].startswith("Raised in group")

    bad = [
        ({"category": "urge_threshold"}, 422),  # automated only (Plan §5.7)
        ({"subject_user_id": str(world.f2.teen.id)}, 403),  # another therapist's family
        ({"subject_user_id": str(world.t2.id)}, 400),  # not a participant
        ({"description": ""}, 422),
    ]
    base = {
        "subject_user_id": str(world.f1.teen.id),
        "category": "privacy_breach",
        "severity": "low",
        "description": "x",
    }
    for change, status in bad:
        r = client.post("/api/v1/safety/events", json={**base, **change})
        assert r.status_code == status, (change, r.status_code, r.text)


def test_admin_cannot_create_manual_events(client: TestClient, world: World) -> None:
    login(client, world.admin)
    r = client.post(
        "/api/v1/safety/events",
        json={
            "subject_user_id": str(world.f1.teen.id),
            "category": "privacy_breach",
            "severity": "low",
            "description": "x",
        },
    )
    assert r.status_code == 403


# --- admin oversight (D39) --------------------------------------------------------------------


def test_admin_reads_everything_but_changes_nothing(
    client: TestClient, world: World, db: Session
) -> None:
    a = _flag(db, world.f1.teen)
    b = _flag(db, world.f2.teen, "我想自杀")
    login(client, world.admin)
    listed = client.get("/api/v1/safety/events").json()
    assert {e["id"] for e in listed["events"]} == {a, b}
    d = client.get(f"/api/v1/safety/events/{b}").json()
    assert d["excerpt"] == "我想自杀" and d["next_statuses"] == []
    row = _last_audit(db)
    assert row.action == "safety.event_read" and row.actor_id == world.admin.id

    r = client.post(f"/api/v1/safety/events/{a}/status", json={"status": "acknowledged"})
    assert r.status_code == 403
    r = client.post(f"/api/v1/safety/events/{a}/notes", json={"body": "x"})
    assert r.status_code == 403
    assert db.get(SafetyEvent, a).status.value == "new"  # type: ignore[union-attr]
