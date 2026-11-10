"""Helpers for the Phase 5 learning API tests."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

PROFILE = {"age": 15, "grade": "grade_9", "hobby_tags": ["music"], "concern_tags": ["sleep"]}


def sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines.get("data", "{}"))))
    return out


def ok(r: Any, code: int = 200) -> dict[str, Any]:
    assert r.status_code == code, r.text
    body: dict[str, Any] = r.json()
    return body


def profile(client: TestClient) -> None:
    ok(client.put("/api/v1/learn/profile", json=PROFILE))


def start(client: TestClient, **body: Any) -> dict[str, Any]:
    lesson: dict[str, Any] = ok(client.post("/api/v1/learn/sessions", json=body), 201)["lesson"]
    return lesson


def to_teaching(client: TestClient, *, answer: str | None = "School was busy.") -> dict[str, Any]:
    """Start a lesson and go through mood, check-in and the recommended skill."""
    lesson = start(client)
    sid = lesson["id"]
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/mood", json={"value": 3}))["lesson"]
    body = {"answer": answer} if answer else {"skip": True}
    lesson = ok(client.post(f"/api/v1/learn/sessions/{sid}/checkin", json=body))["lesson"]
    rec = lesson["recommendation"]["skill"]["id"]
    out: dict[str, Any] = ok(
        client.post(
            f"/api/v1/learn/sessions/{sid}/choose",
            json={"skill_id": rec, "choice": "recommended"},
        )
    )["lesson"]
    return out


def chat_until_complete(client: TestClient, sid: str, limit: int = 10) -> list[Any]:
    events: list[Any] = []
    for i in range(limit):
        r = client.post(f"/api/v1/learn/sessions/{sid}/messages", json={"message": f"ok {i}"})
        assert r.status_code == 200, r.text
        ev = sse(r.text)
        events += ev
        final = [d for e, d in ev if e == "final"]
        assert final, ev
        if final[0]["completed"]:
            return events
    raise AssertionError("lesson did not auto-complete")


def complete_lesson(client: TestClient, **kw: Any) -> str:
    lesson = to_teaching(client, **kw)
    sid: str = lesson["id"]
    chat_until_complete(client, sid)
    ok(client.post(f"/api/v1/learn/sessions/{sid}/post-mood", json={"value": 4}))
    return sid
