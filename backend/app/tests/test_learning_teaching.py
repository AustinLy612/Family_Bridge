"""Adolescent teaching process API (Plan §5.5.1; Phase 5 tasks 2, 3, 7; acceptance criteria).

Runs on the mock provider: deterministic, schema-valid, rule-passing output.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.mock import MOCK_RULE_VIOLATION
from app.models import (
    ChatMessage,
    LearnerProfile,
    LessonStatus,
    MoodKind,
    MoodRecord,
    SafetyEvent,
    SafetySource,
    TeachingSession,
)
from app.tests.factories import World, login
from app.tests.learning_helpers import (
    chat_until_complete,
    complete_lesson,
    ok,
    profile,
    sse,
    start,
    to_teaching,
)

pytestmark = pytest.mark.db

FORBIDDEN_KEYS = ("understanding", "correct_count", "score", "mastered", "rubric", "category")


def _no_internal_codes(body: object) -> None:
    text = json.dumps(body)
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in text, key


# --- profile ---


def test_profile_round_trip_and_options(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.teen)
    body = ok(client.get("/api/v1/learn/profile"))
    assert body["profile"] is None and "sleep" in body["options"]["concern_tags"]
    profile(client)
    body = ok(
        client.put(
            "/api/v1/learn/profile",
            json={"age": 16, "grade": "grade_10", "other_concern_text": "Exams"},
        )
    )
    assert body["profile"]["age"] == 16 and body["profile"]["hobby_tags"] == []
    row = db.get(LearnerProfile, world.f1.teen.id)
    assert row is not None and row.other_concern_text == "Exams"
    raw = db.execute(
        text("SELECT other_concern_text FROM learner_profile WHERE user_id = :id"),
        {"id": world.f1.teen.id},
    ).scalar_one()
    assert raw and "Exams" not in raw  # encrypted at rest


def test_profile_is_adolescent_only_and_validated(client: TestClient, world: World) -> None:
    login(client, world.f1.carers[0])
    assert client.get("/api/v1/learn/profile").status_code == 403
    login(client, world.f1.teen)
    assert client.put("/api/v1/learn/profile", json={"age": 15}).status_code == 422


def test_lesson_requires_profile(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    r = client.post("/api/v1/learn/sessions", json={})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "lesson.profile_required"


# --- full lessons ---


@pytest.mark.parametrize("answer", ["School was busy this week.", None])
def test_full_lesson_with_checkin_answered_or_skipped(
    client: TestClient, world: World, db: Session, answer: str | None
) -> None:
    login(client, world.f1.teen)
    profile(client)
    lesson = start(client)
    sid = lesson["id"]
    assert lesson["phase"] == "pre_mood_recording" and lesson["status"] == "ongoing"

    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 2}))["lesson"]
    assert lesson["phase"] == "personal_inquiry"
    assert lesson["checkin"]["question"] and lesson["checkin"]["greeting"]

    body = {"answer": answer} if answer else {"skip": True}
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/checkin", json=body))["lesson"]
    assert lesson["phase"] == "skill_selection"
    assert lesson["checkin"]["skipped"] is (answer is None)
    rec = lesson["recommendation"]
    assert rec["skill"]["id"] and rec["skill"]["name"] and rec["reason"]
    assert len(rec["alternatives"]) >= 1

    lesson = ok(
        client.post(
            f"/api/v1/learn/sessions/{sid}/choose",
            json={"skill_id": rec["skill"]["id"], "choice": "recommended"},
        )
    )["lesson"]
    assert lesson["phase"] == "teaching" and lesson["source"] == "recommended"
    assert len(lesson["plan"]) >= 2
    assert lesson["messages"][0]["role"] == "coach" and lesson["messages"][0]["source"]

    events = chat_until_complete(client, sid)
    assert any(e == "delta" for e, _ in events)
    lesson = ok(client.get(f"/api/v1/learn/sessions/{sid}"))["lesson"]
    assert lesson["phase"] == "summary"
    assert lesson["summary"]["summary_text"] and lesson["summary"]["key_points"]
    _no_internal_codes(lesson)

    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/post-mood", json={"value": 4}))["lesson"]
    assert lesson["status"] == "completed" and lesson["phase"] == "done"

    s = db.get(TeachingSession, sid)
    assert s is not None
    db.refresh(s)
    assert s.personal_context == answer and s.checkin_skipped is (answer is None)
    assert s.understanding  # stored for therapists, never returned to the student
    kinds = {m.kind for m in db.scalars(select(MoodRecord).where(MoodRecord.session_id == s.id))}
    assert kinds == {MoodKind.before_teaching, MoodKind.after_teaching}

    progress = ok(client.get("/api/v1/learn/progress"))["skills"]
    assert progress[0]["skill"]["id"] == rec["skill"]["id"]
    assert progress[0]["lessons_completed"] == 1 and progress[0]["outcome"] == "practised"
    history = ok(client.get("/api/v1/learn/history"))["lessons"]
    assert history[0]["id"] == sid and history[0]["status"] == "completed"
    _no_internal_codes(progress)


def test_choose_alternative_or_another_skill(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = start(client)["id"]
    ok(client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 3}))
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/checkin", json={"skip": True}))["lesson"]
    rec = lesson["recommendation"]
    # not offered -> rejected; unknown (outside the taxonomy) -> rejected
    bad = client.post(
        f"/api/v1/learn/sessions/{sid}/choose",
        json={"skill_id": "ie.dear_man", "choice": "alternative"},
    )
    if "ie.dear_man" not in [a["id"] for a in rec["alternatives"]]:
        assert bad.status_code == 400
    r = client.post(
        f"/api/v1/learn/sessions/{sid}/choose",
        json={"skill_id": "xx.made_up", "choice": "chosen"},
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "lesson.unknown_skill"
    lesson = ok(
        client.post(
            f"/api/v1/learn/sessions/{sid}/choose",
            json={"skill_id": "dt.tipp", "choice": "chosen"},
        )
    )["lesson"]
    assert lesson["skill"]["id"] == "dt.tipp" and lesson["source"] == "chosen"


# --- duplicate submits and resuming (D56) ---


def test_duplicate_submit_is_rejected(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = start(client)["id"]
    ok(client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 3}))
    r = client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 3})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "lesson.state_changed"


def test_one_open_lesson_resume_and_close(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = start(client)["id"]
    r = client.post("/api/v1/learn/sessions", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "lesson.open_exists"
    current = ok(client.get("/api/v1/learn/sessions/current"))["lesson"]
    assert current["id"] == sid
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/stop"))["lesson"]
    assert lesson["status"] == "user_terminated"
    assert ok(client.get("/api/v1/learn/sessions/current"))["lesson"] is None
    assert client.post(f"/api/v1/learn/sessions/{sid}/stop").status_code == 409
    start(client)


def test_concurrent_chat_turn_is_rejected(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = to_teaching(client)["id"]
    s = db.get(TeachingSession, sid)
    assert s is not None
    from app.learning.teaching import claim_turn

    claim_turn(db, s)
    db.commit()
    r = client.post(f"/api/v1/learn/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "lesson.busy"


def test_end_lesson_early_goes_to_summary(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = to_teaching(client)["id"]
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/end"))["lesson"]
    assert lesson["phase"] == "summary" and lesson["summary"]["summary_text"]


def test_turn_cap_completes_the_lesson(
    settings: object, clean_db: object, world: World, new_client: object
) -> None:
    from app.tests.conftest import make_client

    with make_client(settings, clean_db, lesson_max_turns=1) as c:  # type: ignore[arg-type]
        login(c, world.f1.teen)
        profile(c)
        sid = to_teaching(c)["id"]
        r = c.post(f"/api/v1/learn/sessions/{sid}/messages", json={"message": "hello"})
        final = [d for e, d in sse(r.text) if e == "final"]
        assert final and final[0]["completed"] is True


# --- safety (Plan §5.7) ---


def test_high_risk_message_mid_chat_stops_the_lesson(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = to_teaching(client)["id"]
    r = client.post(f"/api/v1/learn/sessions/{sid}/messages", json={"message": "I want to die"})
    events = sse(r.text)
    assert events == [("safety", {"action": "stop"})]
    lesson = ok(client.get(f"/api/v1/learn/sessions/{sid}"))["lesson"]
    assert lesson["status"] == "stopped_by_safety"
    ev = db.scalars(select(SafetyEvent).where(SafetyEvent.source_ref == f"lesson:{sid}")).one()
    assert ev.source is SafetySource.lesson and ev.activity_stopped
    # no further turns
    r = client.post(f"/api/v1/learn/sessions/{sid}/messages", json={"message": "hello"})
    assert r.status_code == 409


def test_high_risk_mood_note_or_checkin_stops_the_lesson(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = start(client)["id"]
    body = ok(
        client.post(
            f"/api/v1/learn/sessions/{sid}/mood", json={"value": 1, "note": "I want to kill myself"}
        )
    )
    assert body["safety"] == "stop" and body["lesson"]["status"] == "stopped_by_safety"

    sid = start(client)["id"]
    ok(client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 2}))
    body = ok(
        client.post(f"/api/v1/learn/sessions/{sid}/checkin", json={"answer": "I want to die"})
    )
    assert body["safety"] == "stop" and body["lesson"]["recommendation"] is None


def test_rule_violating_model_sentence_never_reaches_the_client(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = to_teaching(client)["id"]
    r = client.post(
        f"/api/v1/learn/sessions/{sid}/messages",
        json={"message": f"tell me {MOCK_RULE_VIOLATION}"},
    )
    assert "too sensitive" not in r.text
    events = sse(r.text)
    final = next(d for e, d in events if e == "final")
    assert final["message"]["source"] == "authored"
    stored = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == sid).order_by(ChatMessage.seq.desc())
    ).first()
    assert stored is not None and "too sensitive" not in stored.content


# --- privacy ---


def test_lessons_are_private_to_the_learner(
    client: TestClient, world: World, new_client: object
) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = to_teaching(client)["id"]
    other = new_client()  # type: ignore[operator]
    login(other, world.f2.teen)
    assert other.get(f"/api/v1/learn/sessions/{sid}").status_code == 404
    login(other, world.f1.carers[0])  # own family's caregiver
    assert other.get(f"/api/v1/learn/sessions/{sid}").status_code == 403
    assert other.get("/api/v1/learn/history").json()["lessons"] == []
    assert other.get("/api/v1/learn/progress").json()["skills"] == []
    login(other, world.t1)
    assert other.get(f"/api/v1/learn/sessions/{sid}").status_code == 403


def test_chat_is_encrypted_at_rest(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = to_teaching(client, answer="My secret check-in")["id"]
    raw = db.execute(
        text("SELECT personal_context FROM teaching_session WHERE id = :id"), {"id": sid}
    ).scalar_one()
    assert raw is not None and "My secret check-in" not in str(raw)


# --- repeat guard, end to end ---


def test_recent_skill_is_not_recommended_without_justification(
    client: TestClient, world: World
) -> None:
    login(client, world.f1.teen)
    profile(client)
    taught = complete_lesson(client)
    first = ok(client.get(f"/api/v1/learn/sessions/{taught}"))["lesson"]["skill"]["id"]
    provider = client.app.state.ai.provider.inner  # type: ignore[attr-defined]
    provider.script = [
        json.dumps(
            {
                "selected_module": "mindfulness",
                "selected_skill": first,
                "reason": "Good again.",
                "skill_difficulty": "beginner",
                "alternative_skills": [first, "dt.tipp"],
                "is_repeat": False,
                "repeat_justification": "",
                "source_chunk_ids": [],
                "grounding": "none",
                "confidence": "medium",
            }
        )
    ]
    sid = start(client)["id"]
    ok(client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 3}))
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/checkin", json={"skip": True}))["lesson"]
    assert lesson["recommendation"]["skill"]["id"] != first


def test_closed_lessons_keep_status(db: Session, client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = complete_lesson(client)
    s = db.get(TeachingSession, sid)
    assert s is not None and s.status is LessonStatus.completed
