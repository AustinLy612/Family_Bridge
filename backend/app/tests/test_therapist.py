"""Therapist dashboard (Plan §5.8; Phase 7 acceptance).

- Homework is set per group and role, ticked in the diary, and has no overdue state (D69).
- Diary expectations are days per week and drive the review's completion figure (D70).
- Learning review shows summaries without the participant's words; transcripts open on demand
  and every read is audited (D15).
- The coverage map is not a ranking. Cached AI content can be reviewed by any therapist;
  "needs change" withdraws and regenerates (D71).
- Metrics are counts only. Therapist time is recorded per family, capped per report.
- Everything is confined to the therapist's own groups.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Task, TaskCompletion, TherapistTime
from app.models.ai import AICacheItem, CacheReview
from app.tests.factories import World, login
from app.tests.learning_helpers import complete_lesson, ok, profile

pytestmark = pytest.mark.db

NewClient = Callable[[], TestClient]


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def code_of(r: Any) -> str:
    return str(r.json()["detail"]["code"])


def task_body(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Practise TIPP once",
        "details": "Fictional homework for tests.",
        "for_roles": ["adolescent"],
        "skill_ids": ["dt.tipp"],
        "starts_on": (today() - timedelta(days=1)).isoformat(),
        "due_on": (today() + timedelta(days=5)).isoformat(),
    }
    body.update(kw)
    return body


def actions(db: Session, actor_id: Any, action: str) -> list[AuditLog]:
    return list(
        db.scalars(select(AuditLog).where(AuditLog.actor_id == actor_id, AuditLog.action == action))
    )


# --- homework (D69) ---


def test_homework_set_ticked_in_diary_and_shown_on_home(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    login(client, world.t1)
    task = ok(client.post(f"/api/v1/groups/{world.g1.id}/tasks", json=task_body()), 201)["task"]
    both = ok(
        client.post(
            f"/api/v1/groups/{world.g1.id}/tasks",
            json=task_body(
                title="Notice one validating moment",
                for_roles=["adolescent", "caregiver"],
                skill_ids=[],
            ),
        ),
        201,
    )["task"]

    teen = new_client()
    login(teen, world.f1.teen)
    home = ok(teen.get("/api/v1/homework"))["items"]
    assert [h["title"] for h in home] == ["Practise TIPP once", "Notice one validating moment"]
    assert not any(h["done"] for h in home)
    assert "overdue" not in json.dumps(home)
    checklist = ok(teen.get(f"/api/v1/diary/homework?date={today().isoformat()}"))["items"]
    assert {h["id"] for h in checklist} == {task["id"], both["id"]}

    carer = new_client()
    login(carer, world.f1.carers[0])
    assert [h["id"] for h in ok(carer.get("/api/v1/homework"))["items"]] == [both["id"]]
    # a caregiver cannot tick the adolescent's homework
    r = carer.post(
        "/api/v1/diary/entries",
        json={"entry_date": today().isoformat(), "homework": [task["id"]]},
    )
    assert r.status_code == 400 and code_of(r) == "diary.unknown_homework"

    # homework alone is a valid entry
    entry = ok(
        teen.post(
            "/api/v1/diary/entries",
            json={"entry_date": today().isoformat(), "homework": [task["id"]]},
        ),
        201,
    )["entry"]
    assert [h["id"] for h in entry["homework"]] == [task["id"]]
    home = {h["id"]: h["done"] for h in ok(teen.get("/api/v1/homework"))["items"]}
    assert home == {task["id"]: True, both["id"]: False}

    # editing without "homework" keeps ticks; an empty list clears them
    e = ok(
        teen.put(
            f"/api/v1/diary/entries/{entry['id']}",
            json={"values": {"sad": 2}, "revision_no": 1},
        )
    )["entry"]
    assert [h["id"] for h in e["homework"]] == [task["id"]]
    e = ok(
        teen.put(
            f"/api/v1/diary/entries/{entry['id']}",
            json={"values": {"sad": 2}, "revision_no": e["revision_no"], "homework": []},
        )
    )["entry"]
    assert e["homework"] == []
    ok(
        teen.put(
            f"/api/v1/diary/entries/{entry['id']}",
            json={
                "values": {"sad": 2},
                "revision_no": e["revision_no"],
                "homework": [task["id"], both["id"]],
            },
        )
    )

    sched = ok(client.get(f"/api/v1/groups/{world.g1.id}/schedule"))
    assert sched["diary_days_per_week"] == 7
    rows = {t["id"]: t for t in sched["tasks"]}
    assert {(a["role"], a["done"]) for a in rows[task["id"]]["assignees"]} == {("adolescent", True)}
    both_status = {(a["role"], a["done"]) for a in rows[both["id"]]["assignees"]}
    assert both_status == {("adolescent", True), ("caregiver", False)}

    # the therapist's diary review shows ticked homework per entry
    review = ok(client.get(f"/api/v1/families/{world.f1.family.id}/diary?days=7"))
    teen_panel = next(p for p in review["participants"] if p["role"] == "adolescent")
    assert set(teen_panel["entries"][0]["homework"]) == {task["title"], both["title"]}

    # archiving removes it from participants' lists but keeps the completion
    assert client.delete(f"/api/v1/tasks/{task['id']}").status_code == 204
    assert [h["id"] for h in ok(teen.get("/api/v1/homework"))["items"]] == [both["id"]]
    assert db.scalar(select(func.count()).select_from(TaskCompletion)) == 2
    assert actions(db, world.t1.id, "task.archived")


def test_homework_outside_its_window_cannot_be_ticked(
    client: TestClient, world: World, new_client: NewClient
) -> None:
    login(client, world.t1)
    later = ok(
        client.post(
            f"/api/v1/groups/{world.g1.id}/tasks",
            json=task_body(
                starts_on=(today() + timedelta(days=3)).isoformat(),
                due_on=(today() + timedelta(days=9)).isoformat(),
            ),
        ),
        201,
    )["task"]
    teen = new_client()
    login(teen, world.f1.teen)
    # listed on Home as this week's homework, but not tickable for today
    assert [h["id"] for h in ok(teen.get("/api/v1/homework"))["items"]] == [later["id"]]
    r = teen.post(
        "/api/v1/diary/entries", json={"entry_date": today().isoformat(), "homework": [later["id"]]}
    )
    assert r.status_code == 400 and code_of(r) == "diary.unknown_homework"
    # other groups' homework never appears
    other = new_client()
    login(other, world.f2.teen)
    assert ok(other.get("/api/v1/homework"))["items"] == []


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            {"due_on": (date(2026, 1, 1)).isoformat(), "starts_on": "2026-01-05"},
            "task.invalid_window",
        ),
        ({"starts_on": "2026-01-01", "due_on": "2026-04-01"}, "task.invalid_window"),
        ({"skill_ids": ["xx.nope"]}, "task.unknown_skill"),
        ({"title": "   "}, "task.title_required"),
    ],
)
def test_task_validation(
    client: TestClient, world: World, change: dict[str, Any], code: str
) -> None:
    login(client, world.t1)
    r = client.post(f"/api/v1/groups/{world.g1.id}/tasks", json=task_body(**change))
    assert r.status_code == 400 and code_of(r) == code
    r = client.post(f"/api/v1/groups/{world.g1.id}/tasks", json=task_body(for_roles=["therapist"]))
    assert r.status_code == 422


def test_task_update_and_audit(client: TestClient, world: World, db: Session) -> None:
    login(client, world.t1)
    task = ok(client.post(f"/api/v1/groups/{world.g1.id}/tasks", json=task_body()), 201)["task"]
    upd = ok(
        client.put(
            f"/api/v1/tasks/{task['id']}", json=task_body(title="Changed", for_roles=["caregiver"])
        )
    )
    assert upd["task"]["title"] == "Changed" and upd["task"]["for_roles"] == ["caregiver"]
    assert actions(db, world.t1.id, "task.created") and actions(db, world.t1.id, "task.updated")
    client.delete(f"/api/v1/tasks/{task['id']}")
    r = client.put(f"/api/v1/tasks/{task['id']}", json=task_body())
    assert r.status_code == 400 and code_of(r) == "task.archived"


# --- diary expectation (D70) ---


def test_diary_expectation_drives_review_completion(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.t1)
    assert ok(
        client.put(f"/api/v1/groups/{world.g1.id}/diary-expectation", json={"days_per_week": 3})
    ) == {"diary_days_per_week": 3}
    review = ok(client.get(f"/api/v1/families/{world.f1.family.id}/diary?days=14"))
    assert review["days_per_week"] == 3
    for p in review["participants"]:
        assert p["completion"]["expected_days"] == 6 and p["completion"]["days_per_week"] == 3
    r = client.put(f"/api/v1/groups/{world.g1.id}/diary-expectation", json={"days_per_week": 0})
    assert r.status_code == 422
    assert actions(db, world.t1.id, "group.diary_expectation_set")


# --- learning review (D15) ---


def test_learning_review_without_transcripts_and_on_demand_detail(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    teen = new_client()
    login(teen, world.f1.teen)
    profile(teen)
    sid = complete_lesson(teen, answer="Fictional: exams made me tense.")

    login(client, world.t1)
    review = ok(client.get(f"/api/v1/families/{world.f1.family.id}/learning"))
    panels = {p["role"]: p for p in review["participants"]}
    assert set(panels) == {"adolescent", "caregiver"} and len(review["participants"]) == 3
    lesson = panels["adolescent"]["lessons"][0]
    assert lesson["id"] == sid and lesson["status"] == "completed"
    assert lesson["skill"]["name"] and lesson["recommendation_reason"]
    assert lesson["summary"]["summary_text"] and lesson["understanding"]
    assert lesson["checkin"] == "answered"
    assert lesson["mood_before"] == 3 and lesson["mood_after"] == 4
    assert panels["adolescent"]["mastery"][0]["lessons_completed"] == 1
    text = json.dumps(review)
    assert "exams made me tense" not in text and '"messages"' not in text
    assert len(actions(db, world.t1.id, "learning.review")) == 3

    detail = ok(client.get(f"/api/v1/families/{world.f1.family.id}/learning/lessons/{sid}"))
    assert detail["checkin"]["answer"] == "Fictional: exams made me tense."
    assert any(m["role"] == "student" for m in detail["messages"])
    reads = actions(db, world.t1.id, "learning.transcript.read")
    assert len(reads) == 1 and reads[0].target_id == sid

    # not visible through another family, nor to another group's therapist
    r = client.get(f"/api/v1/families/{world.f2.family.id}/learning/lessons/{sid}")
    assert r.status_code == 403
    other = new_client()
    login(other, world.t2)
    r = other.get(f"/api/v1/families/{world.f1.family.id}/learning/lessons/{sid}")
    assert r.status_code == 403 and "tense" not in r.text


def _caregiver_lesson(client: TestClient, skill: str = "mf.what_skills") -> str:
    lid = ok(client.post("/api/v1/learn/caregiver/lessons", json={"skill_id": skill}), 201)[
        "lesson"
    ]["id"]
    lesson = ok(
        client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": "explain"})
    )["lesson"]
    text_item = next(
        i for i, it in enumerate(lesson["practice"]["items"]) if it["answer_mode"] == "short_text"
    )
    ok(
        client.post(
            f"/api/v1/learn/caregiver/lessons/{lid}/practice",
            json={"item_index": text_item, "text": "Fictional: I would pause first."},
        )
    )
    for step in ("practice", "quiz"):
        ok(client.post(f"/api/v1/learn/caregiver/lessons/{lid}/next", json={"from_step": step}))
    ok(
        client.post(
            f"/api/v1/learn/caregiver/lessons/{lid}/finish",
            json={"reflection": "Fictional reflection."},
        )
    )
    return str(lid)


def test_caregiver_lessons_in_review_and_group_coverage(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    carer = new_client()
    login(carer, world.f1.carers[0])
    lid = _caregiver_lesson(carer)

    login(client, world.t1)
    review = ok(client.get(f"/api/v1/families/{world.f1.family.id}/learning"))
    panel = next(p for p in review["participants"] if p["user_id"] == str(world.f1.carers[0].id))
    row = panel["lessons"][0]
    assert row["id"] == lid and row["reflection"] == "written"
    assert sum(row["practice_categories"].values()) == 1
    assert "Fictional reflection" not in json.dumps(review)
    detail = ok(client.get(f"/api/v1/families/{world.f1.family.id}/learning/lessons/{lid}"))
    assert detail["reflection"] == "Fictional reflection."
    assert detail["practice"][0]["answer"].startswith("Fictional")

    cov = ok(client.get(f"/api/v1/groups/{world.g1.id}/coverage"))
    assert [p["role"] for p in cov["participants"]] == ["adolescent", "caregiver", "caregiver"]
    assert cov["cells"]["mf.what_skills"][str(world.f1.carers[0].id)]["lessons"] == 1
    assert "total" not in json.dumps(cov) and "rank" not in json.dumps(cov)
    assert cov["modules"] and actions(db, world.t1.id, "learning.coverage")


# --- content review (D71) ---


def test_content_review_needs_change_withdraws_and_regenerates(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    carer = new_client()
    login(carer, world.f1.carers[0])
    _caregiver_lesson(carer)

    login(client, world.t2)  # any therapist (D71), not only the family's own
    listing = ok(client.get("/api/v1/content/cache?review=unreviewed"))
    assert listing["total"] >= 1 and listing["counts"]["unreviewed"] == listing["total"]
    explain = next(i for i in listing["items"] if i["function"] == "explain_skill")
    assert explain["skill"]["name"] and explain["output"]

    reviewed = next(i for i in listing["items"] if i["id"] != explain["id"])
    out = ok(
        client.post(f"/api/v1/content/cache/{reviewed['id']}/review", json={"decision": "reviewed"})
    )
    assert out["item"]["review"] == "reviewed" and out["item"]["reviewed_by"]

    ok(
        client.post(
            f"/api/v1/content/cache/{explain['id']}/review", json={"decision": "needs_change"}
        )
    )
    r = client.post(f"/api/v1/content/cache/{explain['id']}/review", json={"decision": "reviewed"})
    assert r.status_code == 409 and code_of(r) == "content.already_withdrawn"
    assert len(actions(db, world.t2.id, "content.cache_reviewed")) == 2

    # the next caregiver to open the skill gets a regenerated explanation, cached for review
    other = new_client()
    login(other, world.f1.carers[1])
    ok(other.post("/api/v1/learn/caregiver/lessons", json={"skill_id": "mf.what_skills"}), 201)
    db.expire_all()
    rows = list(
        db.scalars(
            select(AICacheItem).where(
                AICacheItem.function == "explain_skill",
                AICacheItem.skill_id == "mf.what_skills",
                AICacheItem.variant == explain["variant"],
                AICacheItem.language == explain["language"],
            )
        )
    )
    assert sorted(r.review for r in rows) == sorted(
        [CacheReview.needs_change, CacheReview.unreviewed]
    )

    # participants and admins cannot review
    assert carer.get("/api/v1/content/cache").status_code == 403
    admin = new_client()
    login(admin, world.admin)
    assert admin.get("/api/v1/content/cache").status_code == 403


# --- metrics and therapist time ---


def test_metrics_and_therapist_time(
    client: TestClient, world: World, db: Session, new_client: NewClient
) -> None:
    login(client, world.t1)
    fam = world.f1.family.id
    assert client.post(f"/api/v1/families/{fam}/time", json={"seconds": 30}).status_code == 204
    assert client.post(f"/api/v1/families/{fam}/time", json={"seconds": 60}).status_code == 204
    assert client.post(f"/api/v1/families/{fam}/time", json={"seconds": 500}).status_code == 422
    assert db.scalar(select(TherapistTime.seconds)) == 90

    ok(client.post(f"/api/v1/groups/{world.g1.id}/tasks", json=task_body()), 201)
    teen = new_client()
    login(teen, world.f1.teen)
    ok(
        teen.post(
            "/api/v1/diary/entries", json={"entry_date": today().isoformat(), "values": {"sad": 3}}
        ),
        201,
    )

    m = ok(client.get(f"/api/v1/groups/{world.g1.id}/metrics?days=7"))
    assert m["enrolment"]["families"] == 1
    assert m["enrolment"]["by_role"]["caregiver"] == {"members": 2, "onboarded": 2}
    assert m["diary"]["adolescent"]["days_with_entries"] == 1
    assert m["diary"]["adolescent"]["expected_days"] == 7
    assert m["homework"] == {"tasks": 1, "assigned": 1, "done": 0}
    assert m["therapist_time"]["families"][0]["minutes"] == 1.5
    assert m["safety"]["sla_hours"] == 24
    assert client.get(f"/api/v1/groups/{world.g1.id}/metrics?days=5").status_code == 400

    other = new_client()
    login(other, world.t2)
    assert other.get(f"/api/v1/groups/{world.g1.id}/metrics").status_code == 403
    assert other.post(f"/api/v1/families/{fam}/time", json={"seconds": 30}).status_code == 403


def test_phase7_routes_are_confined_to_own_groups(
    client: TestClient, world: World, db: Session
) -> None:
    login(client, world.t1)
    other_task = Task(
        group_id=world.g2.id,
        kind="homework",
        for_roles=["adolescent"],
        title="other group",
        skill_ids=[],
        starts_on=today(),
        due_on=today(),
    )
    db.add(other_task)
    db.commit()
    g2, f2 = world.g2.id, world.f2.family.id
    attempts = [
        ("GET", f"/api/v1/groups/{g2}/schedule", None),
        ("PUT", f"/api/v1/groups/{g2}/diary-expectation", {"days_per_week": 3}),
        ("POST", f"/api/v1/groups/{g2}/tasks", task_body()),
        ("PUT", f"/api/v1/tasks/{other_task.id}", task_body()),
        ("DELETE", f"/api/v1/tasks/{other_task.id}", None),
        ("GET", f"/api/v1/families/{f2}/learning", None),
        ("GET", f"/api/v1/groups/{g2}/coverage", None),
        ("GET", f"/api/v1/groups/{g2}/metrics", None),
        ("POST", f"/api/v1/families/{f2}/time", {"seconds": 10}),
    ]
    for method, url, body in attempts:
        r = client.request(method, url, json=body)
        assert r.status_code == 403, (method, url, r.status_code)
    assert len(actions(db, world.t1.id, "access.denied")) == len(attempts)
