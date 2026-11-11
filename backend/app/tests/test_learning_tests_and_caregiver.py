"""Skill tests, caregiver structured lessons and group review (Plan §5.5.1 step 7, §5.5.2,
§5.5.3; Phase 5 tasks 4-6, 8)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import AIResult
from app.learning import testing as ts
from app.models import (
    AIOutcome,
    ContentSource,
    LessonStatus,
    MoodKind,
    MoodRecord,
    SafetyEvent,
    SkillProgress,
    SkillTest,
    SkillTestStatus,
)
from app.tests.factories import World, login
from app.tests.learning_helpers import complete_lesson, ok, profile, start

pytestmark = pytest.mark.db


# --- skill tests ---


def _answer_all(client: TestClient, test: dict[str, Any], *, right: int) -> dict[str, Any]:
    tid = test["id"]
    body: dict[str, Any] = {}
    for q in test["questions"]:
        # the mock always makes option 0 correct
        idx = 0 if q["position"] <= right else 1
        body = ok(
            client.post(
                f"/api/v1/learn/tests/{tid}/answers",
                json={"position": q["position"], "answer_index": idx},
            )
        )
        assert body["question"]["correct_index"] == 0 and body["question"]["explanation"]
    test_out: dict[str, Any] = body["test"]
    return test_out


def test_skill_test_with_retake(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = complete_lesson(client)

    test = ok(client.post(f"/api/v1/learn/sessions/{sid}/tests"), 201)["test"]
    assert test["attempt_no"] == 1
    test = ok(client.get(f"/api/v1/learn/tests/{test['id']}"))["test"]  # background task ran
    assert test["status"] == "ready" and len(test["questions"]) == 5
    assert all(q["correct_index"] is None and q["explanation"] is None for q in test["questions"])

    # one at a time
    r = client.post(
        f"/api/v1/learn/tests/{test['id']}/answers", json={"position": 2, "answer_index": 0}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "test.out_of_order"

    done = _answer_all(client, test, right=3)  # 3/5: below mastery
    assert done["status"] == "completed" and done["outcome"] == "another_look"
    assert "correct_count" not in json.dumps(done) and "3/5" not in json.dumps(done)
    p = db.scalar(select(SkillProgress).where(SkillProgress.user_id == world.f1.teen.id))
    assert p is not None and p.mastered is False

    ok(client.post(f"/api/v1/learn/tests/{test['id']}/mood", json={"value": 3}))
    assert (
        client.post(f"/api/v1/learn/tests/{test['id']}/mood", json={"value": 3}).status_code == 409
    )

    retake = ok(client.post(f"/api/v1/learn/sessions/{sid}/tests"), 201)["test"]
    assert retake["attempt_no"] == 2
    retake = ok(client.get(f"/api/v1/learn/tests/{retake['id']}"))["test"]
    done = _answer_all(client, retake, right=4)  # 4/5: mastery
    assert done["outcome"] == "got_it"
    db.expire_all()
    p = db.scalar(select(SkillProgress).where(SkillProgress.user_id == world.f1.teen.id))
    assert p is not None and p.mastered is True
    progress = ok(client.get("/api/v1/learn/progress"))["skills"]
    assert progress[0]["outcome"] == "understood"
    lesson = ok(client.get(f"/api/v1/learn/sessions/{sid}"))["lesson"]
    assert [t["outcome"] for t in lesson["tests"]] == ["another_look", "got_it"]
    moods = db.scalars(select(MoodRecord).where(MoodRecord.kind == MoodKind.after_testing)).all()
    assert len(moods) == 1


def test_test_needs_a_completed_lesson(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = start(client)["id"]
    r = client.post(f"/api/v1/learn/sessions/{sid}/tests")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "test.lesson_not_completed"


def test_open_test_is_returned_not_duplicated(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.teen)
    profile(client)
    sid = complete_lesson(client)
    a = ok(client.post(f"/api/v1/learn/sessions/{sid}/tests"), 201)["test"]
    b = ok(client.post(f"/api/v1/learn/sessions/{sid}/tests"), 201)["test"]
    assert a["id"] == b["id"]
    ok(client.post(f"/api/v1/learn/tests/{a['id']}/stop"))
    assert db.scalar(select(SkillTest).where(SkillTest.id == a["id"])).status is (  # type: ignore[union-attr]
        SkillTestStatus.user_terminated
    )


class _FlakyAI:
    """generate_skill_test fails `fails` times (no output), then delegates to the real AI."""

    def __init__(self, real: Any, fails: int) -> None:
        self.real, self.fails, self.calls = real, fails, 0

    def run(self, db: Session, function: str, inputs: Any, **kw: Any) -> AIResult:
        self.calls += 1
        if self.calls <= self.fails:
            return AIResult(
                function,
                "adolescent",
                "en",
                None,
                "unavailable",
                ContentSource.none,
                AIOutcome.fallback,
                "none",
            )
        return self.real.run(db, function, inputs, **kw)  # type: ignore[no-any-return]


@pytest.mark.parametrize(("fails", "status", "attempts"), [(2, "ready", 3), (3, "unavailable", 3)])
def test_generation_retries_without_terminating(
    client: TestClient, world: World, db: Session, fails: int, status: str, attempts: int
) -> None:
    """DBT_Revised marked a test USER_TERMINATED on the first failed retry; we keep trying and
    only give up as `unavailable` after the last attempt."""
    login(client, world.f1.teen)
    profile(client)
    sid = complete_lesson(client)
    app = client.app
    statuses: list[str] = []
    flaky = _FlakyAI(app.state.ai, fails)  # type: ignore[attr-defined]
    factory: Callable[[], Session] = app.state.session_factory  # type: ignore[attr-defined]

    def sleep(_: float) -> None:  # observe the state between attempts
        with factory() as s:
            t = s.scalars(select(SkillTest).order_by(SkillTest.created_at.desc())).first()
            assert t is not None
            statuses.append(t.status.value)

    with factory() as s2:
        from app.models import TeachingSession, User

        user = s2.get(User, world.f1.teen.id)
        lesson = s2.get(TeachingSession, sid)
        assert user is not None and lesson is not None
        t, _ = ts.create(s2, user, lesson)
        s2.commit()
        tid = t.id
    ts.generate(factory, flaky, tid, sleep=sleep)
    with factory() as s3:
        t2 = s3.get(SkillTest, tid)
        assert t2 is not None
        assert t2.status.value == status and t2.generation_attempts == attempts
    assert "user_terminated" not in statuses and all(x == "generating" for x in statuses)


# --- caregiver structured lessons ---


def test_caregiver_structured_lesson(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.carers[0])
    skills = ok(client.get("/api/v1/learn/skills"))["modules"]
    assert any(m["id"] == "mindfulness" for m in skills)

    lesson = ok(
        client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "mf.what_skills"}), 201
    )["lesson"]
    lid = lesson["id"]
    assert lesson["step"] == "explain" and lesson["source"] == "explore"
    assert lesson["explanation"]["summary"] and lesson["explanation"]["source"]
    lesson = ok(
        client.post(f"/api/v1/learn/caregiver/lessons/{lid}/adapt", json={"variant": "simpler"})
    )["lesson"]
    assert lesson["variant"] == "simpler"

    lesson = ok(
        client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": "explain"})
    )["lesson"]
    items = lesson["practice"]["items"]
    assert lesson["step"] == "practice" and len(items) >= 2
    choice = next(i for i, it in enumerate(items) if it["answer_mode"] == "choice")
    text_item = next(i for i, it in enumerate(items) if it["answer_mode"] == "short_text")
    body = ok(
        client.post(
            f"/api/v1/learn/caregiver/lessons/{lid}/practice",
            json={"item_index": choice, "option_index": 0},
        )
    )
    assert body["feedback"]["what_worked"] and body["feedback"]["can_retry"] is True
    for n in (1, 2):
        body = ok(
            client.post(
                f"/api/v1/learn/caregiver/lessons/{lid}/practice",
                json={"item_index": text_item, "text": f"I would pause first ({n})."},
            )
        )
    assert body["feedback"]["attempt_no"] == 2 and body["feedback"]["can_retry"] is False
    r = client.post(
        f"/api/v1/learn/caregiver/lessons/{lid}/practice",
        json={"item_index": text_item, "text": "Third try"},
    )
    assert r.status_code == 409  # second opportunity only
    assert "rubric" not in r.text and '"category"' not in json.dumps(body)

    lesson = ok(
        client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": "practice"})
    )["lesson"]
    questions = lesson["quiz"]["questions"]
    assert lesson["step"] == "quiz" and 3 <= len(questions) <= 5
    for i, _ in enumerate(questions):
        res = ok(
            client.post(
                f"/api/v1/learn/caregiver/lessons/{lid}/quiz",
                json={"question_index": i, "answer_index": 0},
            )
        )["result"]
        assert res["is_correct"] is True and res["explanation"]
    ok(client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": "quiz"}))
    lesson = ok(
        client.post(
            f"/api/v1/learn/caregiver/lessons/{lid}/finish",
            json={"reflection": "At dinner time."},
        )
    )["lesson"]
    assert lesson["status"] == "completed" and lesson["outcome"] == "understood"
    assert lesson["reflection"] == "At dinner time."

    progress = ok(client.get("/api/v1/learn/progress"))["skills"]
    assert progress[0]["skill"]["id"] == "mf.what_skills" and progress[0]["outcome"] == "understood"
    history = ok(client.get("/api/v1/learn/history"))["lessons"]
    assert history[0]["kind"] == "caregiver"
    # reopen a past lesson (D57): own answers and feedback, no internal tags
    past = ok(client.get(f"/api/v1/learn/caregiver/lessons/{lid}"))["lesson"]
    assert past["practice"]["items"][text_item]["attempts"][0]["answer"].startswith("I would")
    assert "rubric" not in json.dumps(past) and "category" not in json.dumps(past)


def test_caregiver_can_skip_every_step(client: TestClient, world: World) -> None:
    login(client, world.f1.carers[0])
    lid = ok(client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "dt.tipp"}), 201)[
        "lesson"
    ]["id"]
    for step in ("explain", "practice", "quiz"):
        ok(client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": step}))
    lesson = ok(client.post(f"/api/v1/learn/caregiver/lessons/{lid}/finish", json={}))["lesson"]
    assert lesson["status"] == "completed" and lesson["outcome"] == "practised"
    # duplicate advance is rejected
    r = client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": "quiz"})
    assert r.status_code == 409


def test_caregiver_one_open_lesson_and_stop(client: TestClient, world: World) -> None:
    login(client, world.f1.carers[0])
    lid = ok(client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "dt.tipp"}), 201)[
        "lesson"
    ]["id"]
    r = client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "mf.what_skills"})
    assert r.status_code == 409
    assert ok(client.get("/api/v1/learn/caregiver/current"))["lesson"]["id"] == lid
    ok(client.post(f"/api/v1/learn/caregiver/lessons/{lid}/stop"))
    assert ok(client.get("/api/v1/learn/caregiver/current"))["lesson"] is None
    bad = client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "xx.nope"})
    assert bad.status_code == 400


def test_caregiver_high_risk_text_stops_the_lesson(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.f1.carers[0])
    lid = ok(
        client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "mf.what_skills"}), 201
    )["lesson"]["id"]
    items = ok(
        client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": "explain"})
    )["lesson"]["practice"]["items"]
    text_item = next(i for i, it in enumerate(items) if it["answer_mode"] == "short_text")
    body = ok(
        client.post(
            f"/api/v1/learn/caregiver/lessons/{lid}/practice",
            json={"item_index": text_item, "text": "I want to kill myself"},
        )
    )
    assert body["safety"] == "stop" and body["lesson"]["status"] == "stopped_by_safety"
    assert body["feedback"] is None
    assert db.scalars(
        select(SafetyEvent).where(SafetyEvent.source_ref == f"caregiver_lesson:{lid}")
    ).one()


def test_roles_are_separated(client: TestClient, world: World) -> None:
    login(client, world.f1.teen)
    assert (
        client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "dt.tipp"}).status_code
        == 403
    )
    login(client, world.f1.carers[0])
    assert client.post("/api/v1/learn/sessions", json={}).status_code == 403
    lid = ok(client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "dt.tipp"}), 201)[
        "lesson"
    ]["id"]
    login(client, world.f1.carers[1])  # the other caregiver in the same family
    assert client.get(f"/api/v1/learn/caregiver/lessons/{lid}").status_code == 404


# --- group review (D24) ---


def _record(client: TestClient, group_id: Any, skills: list[str]) -> dict[str, Any]:
    rec: dict[str, Any] = ok(
        client.post(
            f"/api/v1/groups/{group_id}/skill-records",
            json={"session_date": date.today().isoformat(), "skill_ids": skills, "note": "Week 3"},
        ),
        201,
    )["record"]
    return rec


def test_group_review_for_both_roles(
    client: TestClient, world: World, db: Session, new_client: Callable[[], TestClient]
) -> None:
    login(client, world.t1)
    rec = _record(client, world.g1.id, ["dt.tipp", "mf.what_skills"])
    assert [s["id"] for s in rec["skills"]] == ["dt.tipp", "mf.what_skills"]
    listed = ok(client.get(f"/api/v1/groups/{world.g1.id}/skill-records"))["records"]
    assert listed[0]["note"] == "Week 3"

    teen = new_client()
    login(teen, world.f1.teen)
    profile(teen)
    review = ok(teen.get("/api/v1/learn/group-review"))["records"]
    assert review[0]["id"] == rec["id"] and "note" not in review[0]
    assert not {"due", "completed", "done", "overdue"} & set(review[0])
    lesson = start(teen, group_record_id=rec["id"], skill_id="dt.tipp")
    assert lesson["source"] == "group_review" and lesson["skill"]["id"] == "dt.tipp"
    lesson = ok(teen.post(f"/api/v1/learn/sessions/{lesson['id']}/mood", json={"value": 3}))[
        "lesson"
    ]
    # check-in and selection are skipped: straight to teaching with the fixed skill
    assert lesson["phase"] == "teaching" and lesson["checkin"] is None
    assert lesson["recommendation"] is None and lesson["messages"]

    carer = new_client()
    login(carer, world.f1.carers[0])
    lesson = ok(
        carer.post(
            "/api/v1/learn/caregiver/lessons",
            json={"skill_id": "mf.what_skills", "group_record_id": rec["id"]},
        ),
        201,
    )["lesson"]
    assert lesson["source"] == "group_review"
    bad = carer.post(
        "/api/v1/learn/caregiver/lessons",
        json={"skill_id": "er.check_the_facts", "group_record_id": rec["id"]},
    )
    assert bad.status_code in (400, 409)

    other = new_client()
    login(other, world.f2.teen)  # another group
    assert ok(other.get("/api/v1/learn/group-review"))["records"] == []
    profile(other)
    r = other.post(
        "/api/v1/learn/sessions", json={"group_record_id": rec["id"], "skill_id": "dt.tipp"}
    )
    assert r.status_code == 404


def test_group_records_are_therapist_scoped(client: TestClient, world: World) -> None:
    login(client, world.t2)
    r = client.post(
        f"/api/v1/groups/{world.g1.id}/skill-records",
        json={"session_date": "2026-11-01", "skill_ids": ["dt.tipp"]},
    )
    assert r.status_code == 403
    login(client, world.t1)
    r = client.post(
        f"/api/v1/groups/{world.g1.id}/skill-records",
        json={"session_date": "2026-11-01", "skill_ids": ["xx.unknown"]},
    )
    assert r.status_code == 400
    rec = _record(client, world.g1.id, ["dt.tipp"])
    assert (
        client.delete(f"/api/v1/groups/{world.g1.id}/skill-records/{rec['id']}").status_code == 204
    )
    login(client, world.admin)
    assert (
        client.post(
            f"/api/v1/groups/{world.g1.id}/skill-records",
            json={"session_date": "2026-11-01", "skill_ids": ["dt.tipp"]},
        ).status_code
        == 403
    )


def test_closed_lessons_stay_closed(client: TestClient, world: World, db: Session) -> None:
    login(client, world.f1.carers[0])
    lid = ok(client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "dt.tipp"}), 201)[
        "lesson"
    ]["id"]
    ok(client.post(f"/api/v1/learn/caregiver/lessons/{lid}/stop"))
    r = client.post(f"/api/v1/learn/caregiver/lessons/{lid}/adapt", json={"variant": "simpler"})
    assert r.status_code == 409
    assert (
        LessonStatus.user_terminated.value
        == ok(client.get(f"/api/v1/learn/caregiver/lessons/{lid}"))["lesson"]["status"]
    )


def test_caregiver_explanation_follows_a_language_switch(client: TestClient, world: World) -> None:
    """An explanation still on screen is rewritten in the new language (D92)."""
    login(client, world.f1.carers[0])
    ok(client.patch("/api/v1/me", json={"language": "en"}))
    lesson = ok(client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "dt.tipp"}), 201)[
        "lesson"
    ]
    en_summary = lesson["explanation"]["summary"]
    ok(client.patch("/api/v1/me", json={"language": "zh-CN"}))
    lesson = ok(client.get(f"/api/v1/learn/caregiver/lessons/{lesson['id']}"))["lesson"]
    assert lesson["explanation"]["summary"] != en_summary
