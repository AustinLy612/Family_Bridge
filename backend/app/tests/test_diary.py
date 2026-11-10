"""Diary Cards (Plan §5.6; Phase 6 acceptance).

- Caregivers never see adolescent entries without a share; revoking removes access at once.
- An urge score at or above the threshold creates an event and returns "help" (D14).
- Revisions are retained; entries older than 7 days are read-only (D65).
- Cards are never merged: the therapist review has one panel per participant.
- Values and notes are encrypted at rest; every cross-user read is audited.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    DetectionChannel,
    DiaryEntry,
    DiaryRevision,
    SafetyCategory,
    SafetyEvent,
    SafetySource,
    Setting,
)
from app.tests.factories import World, login

pytestmark = pytest.mark.db

NewClient = Callable[[], TestClient]


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def ok(r: Any, code: int = 200) -> dict[str, Any]:
    assert r.status_code == code, r.text
    body: dict[str, Any] = r.json()
    return body


def code_of(r: Any) -> str:
    return str(r.json()["detail"]["code"])


def add(
    client: TestClient,
    values: dict[str, Any],
    note: str | None = None,
    day: date | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"entry_date": (day or today()).isoformat(), "values": values}
    if note is not None:
        body["note"] = note
    return ok(client.post("/api/v1/diary/entries", json=body), 201)


CALM = {"sad": 3, "calm": 7, "self_harm_urge": 1, "suicide_urge": 1}


# --- templates ---


def test_templates_are_role_specific_and_localised(
    client: TestClient, world: World, new_client: NewClient
) -> None:
    login(client, world.f1.teen)
    teen = ok(client.get("/api/v1/diary/template"))
    fields = {f["id"]: f for g in teen["template"]["groups"] for f in g["fields"]}
    assert fields["self_harm_urge"]["urge"] and fields["suicide_urge"]["urge"]
    assert "validating" not in fields and teen["can_share"] is True
    assert teen["template"]["skills"] and teen["today"] == today().isoformat()
    assert teen["editable_from"] == (today() - timedelta(days=6)).isoformat()

    carer = new_client()
    login(carer, world.f1.carers[0])
    c = ok(carer.get("/api/v1/diary/template"))
    cfields = {f["id"]: f for g in c["template"]["groups"] for f in g["fields"]}
    assert "self_harm_urge" not in cfields and cfields["validating"]["type"] == "frequency"
    assert c["can_share"] is False  # caregiver -> adolescent sharing is not enabled (O6)
    ok(carer.patch("/api/v1/me", json={"language": "zh-CN"}))
    zh = ok(carer.get("/api/v1/diary/template"))
    assert zh["template"]["title"] == "日记卡"

    login(client, world.t1)
    assert client.get("/api/v1/diary/template").status_code == 403
    login(client, world.admin)
    assert client.get("/api/v1/diary/template").status_code == 403


# --- validation ---


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"nope": 1}, "diary.unknown_field"),
        ({"note": "x"}, "diary.unknown_field"),  # the note has its own field
        ({"sad": 11}, "diary.invalid_value"),
        ({"sad": 0}, "diary.invalid_value"),
        ({"sad": True}, "diary.invalid_value"),
        ({"sad": "5"}, "diary.invalid_value"),
        ({"skill_used": 1}, "diary.invalid_value"),
        ({"skill_used": True, "skills_used": ["xx.not_a_skill"]}, "diary.invalid_value"),
        ({"skill_used": True, "skills_used": ["dt.tipp", "dt.tipp"]}, "diary.invalid_value"),
        ({}, "diary.empty"),
        ({"sad": None}, "diary.empty"),
    ],
)
def test_values_are_validated(
    client: TestClient, world: World, values: dict[str, Any], code: str
) -> None:
    login(client, world.f1.teen)
    r = client.post(
        "/api/v1/diary/entries", json={"entry_date": today().isoformat(), "values": values}
    )
    assert r.status_code == 400 and code_of(r) == code


def test_hidden_follow_up_answers_are_dropped(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    e = add(client, {"skill_used": False, "skills_used": ["dt.tipp"], "skill_helpful": 8})["entry"]
    assert e["values"] == {"skill_used": False}
    e = add(client, {"skill_used": True, "skills_used": ["dt.tipp"], "skill_helpful": 8})["entry"]
    assert e["values"] == {"skill_used": True, "skills_used": ["dt.tipp"], "skill_helpful": 8}


def test_caregiver_frequency_options(client: TestClient, world: World) -> None:
    login(client, world.f1.carers[0])
    e = add(client, {"validating": "often", "invalidating": "a_little"})["entry"]
    assert e["values"]["validating"] == "often"
    r = client.post(
        "/api/v1/diary/entries",
        json={"entry_date": today().isoformat(), "values": {"validating": "always"}},
    )
    assert code_of(r) == "diary.invalid_value"
    r = client.post(
        "/api/v1/diary/entries",
        json={"entry_date": today().isoformat(), "values": {"self_harm_urge": 3}},
    )
    assert code_of(r) == "diary.unknown_field"  # urges are on the adolescent card only


def test_note_length_limit(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    r = client.post(
        "/api/v1/diary/entries",
        json={"entry_date": today().isoformat(), "values": {}, "note": "x" * 1001},
    )
    assert code_of(r) == "diary.note_too_long"
    assert add(client, {}, note="  " + "x" * 1000 + " ")["entry"]["note"] == "x" * 1000


# --- days, late entries, several per day ---


def test_several_entries_per_day_and_the_seven_day_window(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.teen)
    add(client, CALM)
    add(client, CALM)
    week_ago = today() - timedelta(days=6)
    late = add(client, CALM, day=week_ago)["entry"]
    assert "added_later" not in late and "is_late" not in late  # never shown to participants
    for day in (today() - timedelta(days=7), today() + timedelta(days=1)):
        r = client.post(
            "/api/v1/diary/entries", json={"entry_date": day.isoformat(), "values": CALM}
        )
        assert r.status_code == 400 and code_of(r) == "diary.date_out_of_range"
    listing = ok(client.get("/api/v1/diary/entries"))["entries"]
    assert len(listing) == 3 and all(e["editable"] for e in listing)
    db.expire_all()
    flags = sorted(e.is_late for e in db.execute(select(DiaryEntry)).scalars())
    assert flags == [False, False, True]


def test_missing_days_have_no_negative_copy(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    body = client.get("/api/v1/diary/entries").text + client.get("/api/v1/diary/template").text
    # The only mention of missing days is the reassurance from Plan §5.6.
    assert "missed entries are okay" in body.lower()
    negative = (
        r"(overdue|late|behind|streak|failed|you missed|incomplete)|逾期|未完成|落后|没有完成"
    )
    assert re.search(negative, body.lower()) is None


def test_values_and_notes_are_encrypted_at_rest(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.teen)
    add(client, {"sad": 9, "skill_used": True, "skills_used": ["dt.tipp"]}, note="fictional note")
    for table in ("diary_entry", "diary_revision"):
        raw = db.execute(text(f"SELECT values_json, note FROM {table}")).one()  # noqa: S608
        assert "dt.tipp" not in raw[0] and "sad" not in raw[0]
        assert "fictional note" not in raw[1]


# --- revisions ---


def test_edits_keep_every_revision(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.teen)
    e = add(client, {"sad": 5}, note="first")["entry"]
    url = f"/api/v1/diary/entries/{e['id']}"
    e2 = ok(client.put(url, json={"values": {"sad": 3}, "note": "second", "revision_no": 1}))
    assert e2["entry"]["revision_no"] == 2 and e2["entry"]["values"] == {"sad": 3}
    # a stale tab cannot overwrite a newer save
    r = client.put(url, json={"values": {"sad": 9}, "revision_no": 1})
    assert r.status_code == 409 and code_of(r) == "diary.changed_elsewhere"
    # saving the same thing again adds no revision
    same = ok(client.put(url, json={"values": {"sad": 3}, "note": "second", "revision_no": 2}))
    assert same["entry"]["revision_no"] == 2
    revs = ok(client.get(f"{url}/revisions"))["revisions"]
    assert [(r["revision_no"], r["values"], r["note"]) for r in revs] == [
        (1, {"sad": 5}, "first"),
        (2, {"sad": 3}, "second"),
    ]
    # older than 7 days: read-only, but still listed with its history
    db.execute(text("UPDATE diary_entry SET entry_date = :d"), {"d": today() - timedelta(days=7)})
    db.commit()
    r = client.put(url, json={"values": {"sad": 1}, "revision_no": 2})
    assert r.status_code == 409 and code_of(r) == "diary.read_only"
    assert ok(client.get(url))["entry"]["editable"] is False
    assert db.execute(select(DiaryRevision)).scalars().all().__len__() == 2


# --- safety ---


def _events(db: Session) -> list[SafetyEvent]:
    db.expire_all()
    return list(db.execute(select(SafetyEvent)).scalars())


def test_urge_threshold_creates_an_event_and_shows_help(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.teen)
    below = add(client, {"self_harm_urge": 6, "suicide_urge": 6})
    assert below["safety"] == "none" and _events(db) == []
    at = add(client, {"self_harm_urge": 7})
    assert at["safety"] == "help"
    [ev] = _events(db)
    assert ev.category is SafetyCategory.urge_threshold
    assert ev.source is SafetySource.diary and ev.channel is DetectionChannel.threshold
    assert ev.source_ref == f"diary:{at['entry']['id']}"
    assert ev.subject_user_id == world.f1.teen.id
    # raising an earlier entry over the threshold by editing also triggers
    url = f"/api/v1/diary/entries/{below['entry']['id']}"
    edited = ok(client.put(url, json={"values": {"suicide_urge": 9}, "revision_no": 1}))
    assert edited["safety"] == "help" and len(_events(db)) == 2


def test_urge_threshold_setting_is_used(client: TestClient, world: World, db: Session) -> None:
    db.add(Setting(key="safety.diary_urge_threshold", value=9))
    db.commit()
    login(client, world.f1.teen)
    assert add(client, {"self_harm_urge": 8})["safety"] == "none"
    assert add(client, {"self_harm_urge": 9})["safety"] == "help"


def test_notes_are_risk_screened(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.carers[0])
    out = add(client, {"sad": 4}, note="I want to die")
    assert out["safety"] == "help"  # the entry is saved; the person is shown where to get help
    [ev] = _events(db)
    assert ev.category is SafetyCategory.risk_disclosure and ev.source is SafetySource.diary
    assert out["entry"]["note"] == "I want to die"
    assert add(client, {"sad": 4}, note="Quiet evening, made tea.")["safety"] == "none"


# --- privacy and sharing ---


def test_caregiver_cannot_see_adolescent_entries(
    client: TestClient, world: World, new_client: NewClient
) -> None:
    login(client, world.f1.teen)
    e = add(client, CALM, note="fictional private teen note")["entry"]
    carer = new_client()
    login(carer, world.f1.carers[0])
    assert ok(carer.get("/api/v1/diary/entries"))["entries"] == []
    assert ok(carer.get("/api/v1/diary/shared-with-me"))["items"] == []
    for method, path in [
        ("GET", f"/api/v1/diary/entries/{e['id']}"),
        ("GET", f"/api/v1/diary/entries/{e['id']}/revisions"),
        ("PUT", f"/api/v1/diary/entries/{e['id']}"),
        ("POST", f"/api/v1/diary/entries/{e['id']}/shares"),
    ]:
        body = {"values": {}, "revision_no": 1} if method == "PUT" else {}
        if method == "POST":
            body = {"recipient": e["id"], "fields": ["sad"]}
        r = carer.request(method, path, json=body)
        assert r.status_code == 404, (method, path, r.text)
        assert "fictional private teen note" not in r.text


def _recipients(client: TestClient) -> list[dict[str, str]]:
    return list(ok(client.get("/api/v1/diary/share-recipients"))["recipients"])


def test_share_chosen_fields_then_revoke(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    carer_a, carer_b = world.f1.carers
    login(client, world.f1.teen)
    e = add(
        client,
        {"sad": 6, "self_harm_urge": 2, "skill_used": True, "skills_used": ["dt.tipp"]},
        note="fictional shared note",
    )["entry"]
    recipients = _recipients(client)
    assert sorted(r["alias"] for r in recipients) == sorted(
        [carer_a.display_alias, carer_b.display_alias]
    )
    assert all(r["id"] not in (str(carer_a.id), str(carer_b.id)) for r in recipients)
    to_a = next(r["id"] for r in recipients if r["alias"] == carer_a.display_alias)
    share = ok(
        client.post(
            f"/api/v1/diary/entries/{e['id']}/shares",
            json={"recipient": to_a, "fields": ["sad", "skills_used", "note"]},
        ),
        201,
    )["share"]
    assert share["recipient"] == carer_a.display_alias and share["revoked_at"] is None

    a = new_client()
    login(a, carer_a)
    [item] = ok(a.get("/api/v1/diary/shared-with-me"))["items"]
    assert item["from"] == world.f1.teen.display_alias
    assert item["entry_date"] == today().isoformat()
    assert [i["field_id"] for i in item["items"]] == ["sad", "skills_used", "note"]
    assert item["items"][1]["display"] == "TIPP skills"
    assert "self_harm_urge" not in a.get("/api/v1/diary/shared-with-me").text
    # the other caregiver was not chosen and sees nothing
    b = new_client()
    login(b, carer_b)
    assert ok(b.get("/api/v1/diary/shared-with-me"))["items"] == []
    # later edits do not change what was shared (the owner previewed a snapshot)
    ok(
        client.put(
            f"/api/v1/diary/entries/{e['id']}",
            json={"values": {"sad": 1}, "note": "changed", "revision_no": 1},
        )
    )
    [item] = ok(a.get("/api/v1/diary/shared-with-me"))["items"]
    assert item["items"][0]["value"] == 6 and item["items"][2]["value"] == "fictional shared note"
    # the owner sees the share on the entry and can revoke it; access ends at once
    listed = ok(client.get(f"/api/v1/diary/entries/{e['id']}"))["entry"]["shares"]
    assert [s["id"] for s in listed] == [share["id"]]
    revoked = ok(client.delete(f"/api/v1/diary/shares/{share['id']}"))["share"]
    assert revoked["revoked_at"] is not None
    assert ok(a.get("/api/v1/diary/shared-with-me"))["items"] == []
    # only the owner can revoke
    assert a.delete(f"/api/v1/diary/shares/{share['id']}").status_code == 404
    db.expire_all()
    mine = {world.f1.teen.id, carer_a.id}
    rows = db.execute(select(AuditLog).where(AuditLog.actor_id.in_(mine))).scalars()
    actions = [r.action for r in rows]
    assert {"diary.share.create", "diary.share.revoke", "diary.shared.read"} <= set(actions)


def test_share_rules(client: TestClient, world: World, new_client: NewClient) -> None:
    login(client, world.f1.teen)
    e = add(client, {"sad": 4})["entry"]
    to = _recipients(client)[0]["id"]
    url = f"/api/v1/diary/entries/{e['id']}/shares"
    r = client.post(url, json={"recipient": to, "fields": ["anxious"]})  # not answered
    assert code_of(r) == "diary.unknown_field"
    r = client.post(url, json={"recipient": to, "fields": ["sad", "sad"]})
    assert code_of(r) == "diary.no_fields"
    # someone outside the family (another family's membership id) is not a valid recipient
    other = new_client()
    login(other, world.f2.teen)
    foreign = _recipients(other)[0]["id"]
    r = client.post(url, json={"recipient": foreign, "fields": ["sad"]})
    assert code_of(r) == "diary.invalid_recipient"
    # caregivers cannot share with the adolescent (O6)
    carer = new_client()
    login(carer, world.f1.carers[0])
    assert _recipients(carer) == []
    ce = add(carer, {"sad": 2})["entry"]
    r = carer.post(
        f"/api/v1/diary/entries/{ce['id']}/shares", json={"recipient": to, "fields": ["sad"]}
    )
    assert r.status_code == 403 and code_of(r) == "diary.share_not_allowed"


# --- therapist review ---


def test_therapist_review_keeps_cards_separate(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    login(client, world.f1.teen)
    add(client, {"sad": 8, "self_harm_urge": 2, "skill_used": True, "skills_used": ["dt.tipp"]})
    add(client, {"sad": 4, "skill_used": True, "skills_used": ["dt.tipp", "mf.what_skills"]})
    add(client, {"sad": 5}, note="fictional teen note", day=today() - timedelta(days=2))
    carer = new_client()
    login(carer, world.f1.carers[0])
    add(carer, {"sad": 2, "validating": "often"})

    login(client, world.t1)
    review = ok(client.get(f"/api/v1/families/{world.f1.family.id}/diary?days=14"))
    panels = review["participants"]
    assert [p["role"] for p in panels] == ["adolescent", "caregiver", "caregiver"]
    teen, carer_a, carer_b = panels
    assert teen["alias"] == world.f1.teen.display_alias
    assert len(teen["entries"]) == 3 and len(carer_a["entries"]) == 1 and carer_b["entries"] == []
    sad = next(s for s in teen["series"] if s["field_id"] == "sad")
    assert [p["value"] for p in sad["points"]] == [5, 8, 4]  # chronological
    assert next(s for s in teen["series"] if s["field_id"] == "self_harm_urge")["urge"] is True
    assert teen["skill_use"]["entries_with_skill"] == 2
    assert {s["skill_id"]: s["count"] for s in teen["skill_use"]["skills"]} == {
        "dt.tipp": 2,
        "mf.what_skills": 1,
    }
    assert teen["completion"] == {
        "days_with_entries": 2,
        "days": 14,
        "entries": 3,
        "days_per_week": 7,
        "expected_days": 14,
    }
    assert any(e["note"] == "fictional teen note" and e["added_later"] for e in teen["entries"])
    assert "validating" not in str(teen) and "self_harm_urge" not in str(carer_a["series"])
    db.expire_all()
    reads = [
        str(r.target_id)
        for r in db.execute(
            select(AuditLog).where(
                AuditLog.action == "diary.review", AuditLog.actor_id == world.t1.id
            )
        ).scalars()
    ]
    assert sorted(reads) == sorted(str(p["user_id"]) for p in panels)

    entry_id = teen["entries"][0]["id"]
    revs = ok(
        client.get(f"/api/v1/families/{world.f1.family.id}/diary/entries/{entry_id}/revisions")
    )
    assert len(revs["revisions"]) == 1
    # an entry from another family cannot be read through this family
    r = client.get(f"/api/v1/families/{world.f2.family.id}/diary/entries/{entry_id}/revisions")
    assert r.status_code == 403
    assert client.get(f"/api/v1/families/{world.f1.family.id}/diary?days=5").status_code == 400

    login(client, world.t2)  # not assigned to this group
    assert client.get(f"/api/v1/families/{world.f1.family.id}/diary").status_code == 403
    login(client, world.admin)  # no diary access (break-glass only, Plan §4.2)
    assert client.get(f"/api/v1/families/{world.f1.family.id}/diary").status_code == 403
