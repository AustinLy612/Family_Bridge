"""Joint sessions and the episode engine (Plan §5.9; Phase 8 acceptance).

Ported and extended from the Lantern Forest prototype's room tests:
- rooms come only from a therapist's assignment, for a suitable pair, with an assignable
  episode version; wrong-family users are rejected;
- separate acceptance; a decline is neutral and the partner sees no reason;
- private choices never reach the partner's projection before the declared reveal;
- `both` steps never advance with one participant absent;
- disconnect / reconnect resumes the same step, also after a server restart;
- either participant can pause; a safety pause ("I need to stop", D75) is therapist-resume only;
- therapist permission checks; demo-only reset;
- the shared completion record holds no private fields; distress ratings (D76) and reflections
  (D77) are private, shown to the therapist after the session, and every read is audited.
All text is fictional.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session
from starlette.testclient import WebSocketTestSession

from app.core.sessions import COOKIE_NAME
from app.models import (
    AuditLog,
    DistressRating,
    DyadSuitability,
    JointSession,
    PrivateReflection,
    RoomEvent,
    SafetyEvent,
    SharedCompletionRecord,
    Suitability,
    User,
)
from app.settings import Settings
from app.tests.conftest import make_client
from app.tests.factories import World, login

pytestmark = pytest.mark.db

ORIGIN = {"origin": "http://testserver"}
CONTENT = Path(__file__).resolve().parents[3] / "content"


# --- helpers ----------------------------------------------------------------------------


class Actor:
    """A signed-in person, addressed through one shared TestClient (one app, one hub)."""

    def __init__(self, tc: TestClient, user: User) -> None:
        tc.cookies.clear()
        tc.headers.pop("X-CSRF-Token", None)
        self.csrf = login(tc, user)
        self.token = tc.cookies.get(COOKIE_NAME)
        tc.cookies.clear()
        tc.headers.pop("X-CSRF-Token", None)
        self.tc, self.user = tc, user

    @property
    def headers(self) -> dict[str, str]:
        return {"cookie": f"{COOKIE_NAME}={self.token}", "X-CSRF-Token": self.csrf}

    def get(self, url: str) -> Any:
        return self.tc.get(url, headers=self.headers)

    def post(self, url: str, body: Any = None) -> Any:
        return self.tc.post(url, json=body or {}, headers=self.headers)

    def delete(self, url: str) -> Any:
        return self.tc.delete(url, headers=self.headers)

    @contextmanager
    def room(self, sid: str, origin: dict[str, str] = ORIGIN) -> Iterator[Room]:
        with self.tc.websocket_connect(
            f"/api/v1/joint/sessions/{sid}/ws",
            headers={"cookie": f"{COOKIE_NAME}={self.token}", **origin},
        ) as ws:
            yield Room(ws)


async def _recv(rx: Any) -> Any:
    with anyio.fail_after(5):
        return await rx.receive()


class Room:
    def __init__(self, ws: WebSocketTestSession) -> None:
        self.ws = ws
        self.seq = 0
        self.state: dict[str, Any] = {}
        self.log: list[dict[str, Any]] = []

    def recv(self) -> dict[str, Any]:
        msg = self.ws.portal.call(_recv, self.ws._send_rx)
        self.ws._raise_on_close(msg)
        data: dict[str, Any] = json.loads(msg["text"])
        self.log.append(data)
        if data["type"] == "state" and data["seq"] >= self.seq:
            self.seq, self.state = data["seq"], data["state"]
        return data

    def until(self, pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        for _ in range(40):
            m = self.recv()
            if pred(m):
                return m
        raise AssertionError(f"message not received; last: {self.log[-3:]}")

    def at_least(self, seq: int) -> dict[str, Any]:
        if self.seq >= seq and self.state:
            return self.state
        self.until(lambda m: m["type"] == "state" and m["seq"] >= seq)
        return self.state

    def wait_step(self, step_id: str) -> dict[str, Any]:
        def at(st: dict[str, Any]) -> bool:
            return bool(st.get("step")) and st["step"]["id"] == step_id

        if not at(self.state):
            self.until(lambda m: m["type"] == "state" and at(m["state"]))
        return self.state

    def ready_state(self) -> dict[str, Any]:
        self.until(lambda m: m["type"] == "state")
        return self.state

    def send(self, kind: str, **kw: Any) -> dict[str, Any]:
        """Send an action and wait for its ack or error; returns that message."""
        aid = kw.pop("id", uuid.uuid4().hex)
        self.ws.send_json({"type": kind, "id": aid, **kw})
        return self.until(lambda m: m.get("id") == aid and m["type"] in ("ack", "error"))

    def act(self, kind: str, **kw: Any) -> dict[str, Any]:
        m = self.send(kind, **kw)
        assert m["type"] == "ack", m
        return self.at_least(m["seq"])

    def step_act(self, kind: str, value: Any = None) -> dict[str, Any]:
        sid = self.state["step"]["id"]
        return self.act(kind, step_id=sid, **({} if value is None else {"value": value}))


def suitable(db: Session, w: World, carer: int = 0) -> None:
    db.add(
        DyadSuitability(
            family_id=w.f1.family.id,
            adolescent_id=w.f1.teen.id,
            caregiver_id=w.f1.carers[carer].id,
            decision=Suitability.suitable,
        )
    )
    db.commit()


def window(hours_from: float = -1, hours_to: float = 2) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "opens_at": (now + timedelta(hours=hours_from)).isoformat(),
        "closes_at": (now + timedelta(hours=hours_to)).isoformat(),
    }


def schedule(
    t: Actor, w: World, episode: str = "demo-stub-episode", carer: int = 0, **kw: str
) -> Any:
    body = {
        "family_id": str(w.f1.family.id),
        "caregiver_id": str(w.f1.carers[carer].id),
        "episode_id": episode,
        "episode_version": 1,
        **window(),
        **kw,
    }
    return t.post(f"/api/v1/groups/{w.g1.id}/joint-sessions", body)


@pytest.fixture
def tc(settings: Settings, clean_db: Engine) -> Iterator[TestClient]:
    with make_client(settings, clean_db, room_disconnect_pause_seconds=0) as c:
        yield c


@pytest.fixture
def people(tc: TestClient, world: World, db: Session) -> dict[str, Actor]:
    suitable(db, world)
    return {
        "t": Actor(tc, world.t1),
        "teen": Actor(tc, world.f1.teen),
        "carer": Actor(tc, world.f1.carers[0]),
    }


def accepted_session(p: dict[str, Actor], w: World, **kw: Any) -> str:
    r = schedule(p["t"], w, **kw)
    assert r.status_code == 201, r.text
    sid: str = r.json()["id"]
    for who in ("teen", "carer"):
        assert (
            p[who]
            .post(f"/api/v1/joint/sessions/{sid}/respond", {"response": "accepted"})
            .status_code
            == 200
        )
    return sid


def start(a: Room, b: Room) -> None:
    a.ready_state()
    b.ready_state()
    a.act("ready")
    m = b.send("ready")
    assert m["type"] == "ack"
    b.at_least(m["seq"])
    a.at_least(m["seq"])
    assert a.state["phase"] == b.state["phase"] == "running"


# --- scheduling gates -------------------------------------------------------------------


def test_scheduling_requires_suitable_pair_and_assignable_episode(
    tc: TestClient, world: World, db: Session
) -> None:
    t = Actor(tc, world.t1)
    r = schedule(t, world)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "joint.not_suitable"
    suitable(db, world)
    # bad windows
    for w in (window(1, 0.5), window(-3, -1), window(0, 24 * 20)):
        r = schedule(t, world, "demo-stub-episode", 0, **w)
        assert r.json()["detail"]["code"] == "joint.invalid_window", w
    # a demo episode is never assignable to a non-demo family
    world.f1.family.is_demo = False
    db.commit()
    r = schedule(t, world)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "joint.episode_not_approved"
    world.f1.family.is_demo = True
    db.commit()
    assert schedule(t, world).status_code == 201
    # another group's therapist cannot schedule here, and the denial is audited
    t2 = Actor(tc, world.t2)
    assert schedule(t2, world).status_code == 403
    assert db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.actor_id == world.t2.id, AuditLog.action == "access.denied")
    )
    # a caregiver from outside the family is rejected
    r = t.post(
        f"/api/v1/groups/{world.g1.id}/joint-sessions",
        {
            "family_id": str(world.f1.family.id),
            "caregiver_id": str(world.f2.carers[0].id),
            "episode_id": "demo-stub-episode",
            "episode_version": 1,
            **window(),
        },
    )
    assert r.json()["detail"]["code"] == "joint.not_in_family"


def test_episode_approval_by_content_approver_makes_it_assignable(
    settings: Settings, clean_db: Engine, world: World, db: Session, tmp_path: Path
) -> None:
    content = tmp_path / "content"
    shutil.copytree(CONTENT, content)
    draft = content / "episodes" / "draft-episode"
    draft.mkdir()
    src = (CONTENT / "episodes" / "demo-stub-episode" / "v1.yaml").read_text(encoding="utf-8")
    (draft / "v1.yaml").write_text(
        src.replace("id: demo-stub-episode", "id: draft-episode").replace(
            "status: demo", "status: draft"
        ),
        encoding="utf-8",
    )
    suitable(db, world)
    world.f1.family.is_demo = False
    db.commit()
    with make_client(settings, clean_db, content_dir=content) as c:
        t = Actor(c, world.t1)
        admin = Actor(c, world.admin)
        eps = {e["id"]: e for e in t.get("/api/v1/episodes").json()["episodes"]}
        assert eps["draft-episode"]["status"] == "draft"
        assert (
            schedule(t, world, "draft-episode").json()["detail"]["code"]
            == "joint.episode_not_approved"
        )
        url = "/api/v1/episodes/draft-episode/versions/1/decision"
        assert t.post(url, {"status": "approved"}).status_code == 403  # not a content approver
        r = admin.tc.put(
            f"/api/v1/admin/therapists/{world.t1.id}/content-approver",
            json={"content_approver": True},
            headers=admin.headers,
        )
        assert r.status_code == 200 and r.json()["content_approver"] is True
        assert t.post(url, {"status": "approved"}).json()["status"] == "approved"
        # demo fixtures can never be approved for real use
        r = t.post("/api/v1/episodes/demo-stub-episode/versions/1/decision", {"status": "approved"})
        assert r.status_code == 409
        assert schedule(t, world, "draft-episode").status_code == 201
        assert t.post(url, {"status": "retired"}).json()["status"] == "retired"
        assert (
            schedule(t, world, "draft-episode").json()["detail"]["code"]
            == "joint.episode_not_approved"
        )
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_id == world.t1.id, AuditLog.action == "episode.approved")
        )
        == 1
    )


# --- invitations ------------------------------------------------------------------------


def test_separate_acceptance_and_neutral_decline(
    tc: TestClient, world: World, people: dict[str, Actor]
) -> None:
    p = people
    sid = schedule(p["t"], world).json()["id"]
    teen_view = p["teen"].get("/api/v1/joint/sessions").json()["sessions"][0]
    assert teen_view["status"] == "invited" and teen_view["can_respond"]
    assert teen_view["episode"]["objective"]["en"]
    assert (
        p["carer"]
        .post(f"/api/v1/joint/sessions/{sid}/respond", {"response": "accepted"})
        .status_code
        == 200
    )
    # the teen still sees a plain invitation: nothing about the partner's answer
    assert p["teen"].get(f"/api/v1/joint/sessions/{sid}").json()["status"] == "invited"
    r = p["teen"].post(f"/api/v1/joint/sessions/{sid}/respond", {"response": "declined"})
    assert r.json()["status"] == "you_declined"
    carer_view = p["carer"].get(f"/api/v1/joint/sessions/{sid}")
    assert carer_view.json()["status"] == "wont_run" and not carer_view.json()["can_join"]
    text = carer_view.text
    assert "declin" not in text and world.f1.teen.display_alias not in text
    # no second answer, and the room cannot open
    assert (
        p["teen"]
        .post(f"/api/v1/joint/sessions/{sid}/respond", {"response": "accepted"})
        .status_code
        == 409
    )
    with p["carer"].room(sid) as room:
        assert room.recv() == {"type": "error", "code": "joint.not_open"}
    # the therapist sees who declined (§9.1C: declines are visible to the therapist only)
    board = p["t"].get(f"/api/v1/groups/{world.g1.id}/joint").json()
    row = next(s for s in board["sessions"] if s["id"] == sid)
    assert row["adolescent"]["response"] == "declined" and row["status"] == "declined"


def test_room_needs_both_acceptances_and_rejects_other_families(
    tc: TestClient, world: World, people: dict[str, Actor]
) -> None:
    p = people
    sid = schedule(p["t"], world).json()["id"]
    p["teen"].post(f"/api/v1/joint/sessions/{sid}/respond", {"response": "accepted"})
    with p["teen"].room(sid) as room:
        assert room.recv()["code"] == "joint.not_accepted"
    outsider = Actor(tc, world.f2.teen)
    with outsider.room(sid) as room:
        assert room.recv()["code"] == "access.forbidden"
    other_carer = Actor(tc, world.f1.carers[1])  # same family, not in this pair
    with other_carer.room(sid) as room:
        assert room.recv()["code"] == "access.forbidden"
    # cross-site WebSocket hijacking guard
    with (
        pytest.raises(Exception),  # noqa: B017 - closed before accept
        p["teen"].room(sid, origin={"origin": "http://evil.example"}) as room,
    ):
        room.recv()


# --- the room ---------------------------------------------------------------------------


def test_private_choices_hidden_until_reveal_and_both_steps_wait(
    tc: TestClient, world: World, people: dict[str, Actor]
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        a.ws.send_json({"type": "join", "location": "hospital"})
        start(a, b)
        assert a.state["step"]["id"] == "s1"
        a.step_act("submit")
        b.at_least(a.seq)
        assert b.state["step"]["id"] == "s1" and b.state["step"]["partner_acted"] is True
        b.step_act("submit")
        a.at_least(b.seq)
        assert a.state["step"]["id"] == b.state["step"]["id"] == "s2"
        a.step_act("distress", 3)
        b.step_act("skip")
        a.at_least(b.seq)
        # s3: private choice. Each sees only their own options; the partner's choice is hidden.
        assert a.state["step"]["id"] == "s3"
        assert {o["id"] for o in a.state["step"]["options"]} == {"a-apple", "a-book"}
        assert {o["id"] for o in b.state["step"]["options"]} == {"c-scarf", "c-map"}
        a.step_act("submit", "a-apple")
        b.at_least(a.seq)
        seen = json.dumps(b.log)
        assert "a-apple" not in seen and "An apple" not in seen
        assert b.state["step"]["partner_acted"] is True
        b.step_act("submit", "c-map")
        a.at_least(b.seq)
        # declared reveal: choice text only, after both submitted
        for room in (a, b):
            step = room.state["step"]
            assert step["phase"] == "review"
            assert step["revealed"]["adolescent"]["text"]["en"] == "An apple"
            assert step["revealed"]["caregiver"]["text"]["en"] == "A map"
            assert "rubric_tag" not in step["revealed"]["adolescent"]
        a.step_act("submit")
        b.step_act("submit")
        a.at_least(b.seq)
        assert a.state["step"]["id"] == "s4"
        # distress values never enter the room state or the event log
        assert '"value": 3' not in json.dumps(a.log + b.log)


def test_both_step_never_advances_while_partner_absent_then_resumes(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a:
        with p["carer"].room(sid) as b:
            start(a, b)
            b.step_act("submit")  # caregiver acknowledges s1, then drops
        a.until(lambda m: m["type"] == "presence" and m["present"] is False)
        a.ready_state()
        assert a.state["partner_present"] is False
        a.step_act("submit")
        assert a.state["step"]["id"] == "s1"  # both acted, but one is absent: no advance
        with p["carer"].room(sid) as b2:
            b2.ready_state()
            for r in (a, b2):
                r.wait_step("s2")
    s = db.get(JointSession, uuid.UUID(sid))
    db.refresh(s)
    assert s is not None and s.snapshot["step"] == 1


def test_reconnect_resumes_same_step_after_server_restart(
    settings: Settings, clean_db: Engine, tc: TestClient, world: World, people: dict[str, Actor]
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        start(a, b)
        for r in (a, b):
            r.step_act("submit")
        a.at_least(b.seq)
        assert a.state["step"]["id"] == "s2"
        seq = a.seq
    # a fresh app instance (new process, empty hub) with the same database
    with make_client(settings, clean_db, room_disconnect_pause_seconds=0) as c2:
        teen, carer = Actor(c2, world.f1.teen), Actor(c2, world.f1.carers[0])
        with teen.room(sid) as a2, carer.room(sid) as b2:
            st = a2.ready_state()
            b2.ready_state()
            assert st["phase"] == "running" and st["step"]["id"] == "s2" and a2.seq >= seq
            # sequence numbers keep counting across the restart
            nxt = a2.step_act("distress", 1)
            assert a2.seq == seq + 1 and nxt["step"]["id"] == "s2"


def test_idempotent_actions_and_typed_validation(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        start(a, b)
        first = a.send("submit", id="same-key-123", step_id="s1")
        again = a.send("submit", id="same-key-123", step_id="s1")
        assert first["type"] == again["type"] == "ack"
        assert again["duplicate"] is True and again["seq"] == first["seq"]
        # clients send actions, never states: skipping ahead or bad values are refused
        assert a.send("submit", step_id="s5")["code"] == "room.wrong_step"
        assert b.send("submit", step_id="s1", value={"phase": "completed"})["type"] == "ack"
        a.at_least(b.seq)
        assert a.send("distress", step_id="s2", value=11)["code"] == "room.invalid_value"
        assert a.send("submit", step_id="s2", value=5)["code"] == "room.wrong_step"
        assert a.send("teleport")["code"] == "room.unknown_message"
        assert a.send("submit", id="short", step_id="s2")["code"] == "room.missing_id"
    n = db.scalar(
        select(func.count())
        .select_from(RoomEvent)
        .where(RoomEvent.idempotency_key == "same-key-123")
    )
    assert n == 1


def test_pause_either_resumes_but_safety_pause_is_therapist_only(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        start(a, b)
        a.act("pause")
        b.at_least(a.seq)
        assert b.state["phase"] == "paused" and b.state["pause"] == "pause"
        assert b.send("submit", step_id="s1")["code"] == "room.paused"
        b.act("resume")  # either participant may resume a participant pause
        a.at_least(b.seq)
        assert a.state["phase"] == "running" and a.state["step"]["id"] == "s1"

        # "I need to stop" (D75): safety pause; the stopper is sent to Help
        a.send("stop")
        a.until(lambda m: m["type"] == "safety")
        assert any(m == {"type": "safety", "action": "help"} for m in a.log)
        b.until(lambda m: m["type"] == "state" and m["state"]["phase"] == "paused")
        assert b.state["pause"] == "hold"
        partner_seen = json.dumps(b.log)
        assert "safety" not in partner_seen and "stop" not in partner_seen
        assert b.send("resume")["code"] == "room.not_allowed"
        assert a.send("resume")["code"] == "room.not_allowed"

        # therapist controls: other group's therapist refused; own therapist resumes
        t2 = Actor(tc, world.t2)
        assert (
            t2.post(f"/api/v1/joint-sessions/{sid}/control", {"action": "resume"}).status_code
            == 403
        )
        r = p["t"].post(f"/api/v1/joint-sessions/{sid}/control", {"action": "resume"})
        assert r.status_code == 200 and r.json()["board"]["phase"] == "running"
        b.until(lambda m: m["type"] == "state" and m["state"]["phase"] == "running")
        # a therapist pause is also therapist-resume only
        p["t"].post(f"/api/v1/joint-sessions/{sid}/control", {"action": "pause"})
        a.until(lambda m: m["type"] == "state" and m["state"]["phase"] == "paused")
        assert a.state["pause"] == "hold" and a.send("resume")["code"] == "room.not_allowed"
    ev = db.scalars(select(SafetyEvent).where(SafetyEvent.source_ref == sid)).one()
    assert ev.source.value == "joint" and ev.channel.value == "participant"
    assert ev.category.value == "discomfort_or_trauma_cue"


def test_leave_ends_for_both_with_partial_record(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        start(a, b)
        a.step_act("submit")
        b.step_act("submit")
        b.act("leave")
        a.until(lambda m: m["type"] == "ended")
        a.at_least(b.seq)
        assert a.state["phase"] == "ended" and a.state["end_reason"] == "ended"
        assert "left" not in json.dumps(a.state)
    rec = db.scalars(
        select(SharedCompletionRecord).where(SharedCompletionRecord.session_id == uuid.UUID(sid))
    ).one()
    assert rec.status == "partial" and rec.completed_step_ids == ["s1"]


def _run_stub(a: Room, b: Room, reflection: str = "Fictional: that was calm.") -> None:
    start(a, b)
    for r in (a, b):
        r.step_act("submit")  # s1
    a.at_least(b.seq)
    a.step_act("distress", 4)
    b.step_act("distress", 2)  # s2
    a.at_least(b.seq)
    a.step_act("submit", "a-book")
    b.step_act("submit", "c-scarf")  # s3 input
    a.at_least(b.seq)
    a.step_act("submit")
    b.step_act("submit")  # s3 reveal ack
    a.at_least(b.seq)
    assert a.state["step"]["id"] == "s4"
    a.step_act("submit", ["f-notice"])
    b.at_least(a.seq)
    assert b.state["step"]["partner_count"] == 1 and b.state["step"]["my_fragments"] is None
    b.step_act("submit", ["f-ask", "f-hello"])  # s4
    a.at_least(b.seq)
    fb = a.state["step"]
    assert fb["id"] == "s5" and fb["feedback"]["title"]["en"] == "You noticed and you asked"
    assert [c["id"] for c in fb["composition"]] == ["f-hello", "f-notice", "f-ask"]
    a.step_act("submit")
    b.step_act("submit")  # s5
    a.at_least(b.seq)
    a.step_act("skip")
    b.step_act("skip")  # s6 retry skipped by both
    a.at_least(b.seq)
    assert a.state["step"]["id"] == "s7"
    a.step_act("submit", "t-ask")
    assert a.state["step"]["my_feedback"]["en"].startswith("Placeholder")
    b.step_act("submit", "t-fix")  # s7
    a.at_least(b.seq)
    a.step_act("submit", reflection)
    b.step_act("skip")  # s8
    a.at_least(b.seq)


def test_full_stub_run_completion_record_has_no_private_fields(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        _run_stub(a, b)
        assert a.state["phase"] == b.state["phase"] == "completed"
        partner_seen = json.dumps(b.log)
        i = partner_seen.find("that was calm")
        assert i < 0, partner_seen[max(0, i - 400) : i + 50]
        assert '"my_choice": "t-ask"' not in partner_seen
    rec = db.scalars(
        select(SharedCompletionRecord).where(SharedCompletionRecord.session_id == uuid.UUID(sid))
    ).one()
    assert rec.status == "completed"
    assert rec.completed_step_ids == ["s1", "s2", "s3", "s4", "s5", "s7", "s8"]
    assert rec.skipped_step_ids == ["s6"]
    assert rec.shared_rubric_tags == ["asking", "greeting", "noticing"]
    # nothing private: no private-choice tags, transfer answers, distress or reflection
    dumped = json.dumps(
        {c.name: str(getattr(rec, c.name)) for c in SharedCompletionRecord.__table__.columns}
    )
    for private in ("placeholder", "fixing", "calm", '"4"', "a-book", "c-scarf"):
        assert private not in dumped
    # private records: distress ratings (D76) and an encrypted reflection (D77)
    assert sorted(d.value for d in db.scalars(select(DistressRating))) == [2, 4]  # type: ignore[type-var]
    refl = db.scalars(select(PrivateReflection)).one()
    assert refl.text == "Fictional: that was calm."
    raw = db.execute(text("SELECT text FROM private_reflection")).scalar_one()
    assert "calm" not in raw
    # the room state and event log never hold the reflection or distress values
    s = db.get(JointSession, uuid.UUID(sid))
    assert s is not None and "calm" not in json.dumps(s.snapshot)
    payloads = json.dumps([e.payload for e in db.scalars(select(RoomEvent))])
    assert "calm" not in payloads

    # the therapist summary shows rubric-coded outputs, distress and reflections, audited
    summ = p["t"].get(f"/api/v1/joint-sessions/{sid}/summary").json()
    assert summ["record"]["status"] == "completed"
    assert summ["rubric"]["adolescent"]["s3"] == ["placeholder_b"]
    assert summ["rubric"]["caregiver"]["s7"] == ["fixing"]
    assert {(d["role"], d["value"]) for d in summ["distress"]} == {
        ("adolescent", 4),
        ("caregiver", 2),
    }
    assert summ["reflections"] == [
        {"role": "adolescent", "text": "Fictional: that was calm.", "flagged": False}
    ]
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_id == world.t1.id, AuditLog.action == "joint.summary.read")
        )
        == 1
    )
    # another group's therapist cannot read it
    assert Actor(tc, world.t2).get(f"/api/v1/joint-sessions/{sid}/summary").status_code == 403
    # participants see the session as finished
    assert p["carer"].get(f"/api/v1/joint/sessions/{sid}").json()["status"] == "completed"


def test_risky_reflection_safety_pauses_the_room(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        _run_stub_to_reflection(a, b)
        a.step_act("submit", "I want to kill myself")
        assert {"type": "safety", "action": "stop"} in a.log
        b.until(lambda m: m["type"] == "state" and m["state"]["phase"] == "paused")
        assert b.state["pause"] == "hold" and "kill" not in json.dumps(b.log)
    ev = db.scalars(select(SafetyEvent).where(SafetyEvent.source_ref == sid)).one()
    assert ev.source.value == "joint" and ev.severity.value == "high"
    assert db.scalars(select(PrivateReflection)).one().flagged is True


def _run_stub_to_reflection(a: Room, b: Room) -> None:
    start(a, b)
    for kind, va, vb in [
        ("submit", None, None),
        ("skip", None, None),
        ("skip", None, None),
        ("skip", None, None),
        ("submit", None, None),
        ("skip", None, None),
        ("skip", None, None),
    ]:
        a.step_act(kind, va)
        b.step_act(kind, vb)
        a.at_least(b.seq)
    assert a.state["step"]["id"] == "s8"


def test_hints_are_authored_and_private(
    tc: TestClient, world: World, people: dict[str, Actor]
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        start(a, b)
        st = a.step_act("hint")
        assert (
            st["step"]["hints"][0]["en"] == "Take your time reading."
            and st["step"]["hints_left"] == 0
        )
        assert a.send("hint", step_id="s1")["code"] == "room.no_hint"
        b.at_least(a.seq)
        assert b.state["step"]["hints"] == []


def test_reset_is_demo_only_and_solo_rehearsal_runs_alone(
    tc: TestClient, world: World, people: dict[str, Actor], db: Session
) -> None:
    p = people
    sid = accepted_session(p, world)
    with p["teen"].room(sid) as a, p["carer"].room(sid) as b:
        start(a, b)
        a.step_act("submit")
        r = p["t"].post(f"/api/v1/joint-sessions/{sid}/control", {"action": "reset"})
        assert r.status_code == 200 and r.json()["board"]["phase"] == "lobby"
        a.until(lambda m: m["type"] == "state" and m["state"]["phase"] == "lobby")
    world.f1.family.is_demo = False
    db.commit()
    r = p["t"].post(f"/api/v1/joint-sessions/{sid}/control", {"action": "reset"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "room.reset_demo_only"

    solo = p["carer"].post("/api/v1/joint/solo").json()
    assert solo["mode"] == "solo" and solo["can_join"]
    with p["carer"].room(solo["id"]) as r1:
        st = r1.ready_state()
        assert st["solo"] is True and st["partner_present"] is None
        r1.act("ready")
        r1.step_act("submit")
        r1.step_act("skip")
        st = r1.step_act("submit", "c-map")
        assert st["step"]["id"] == "s4"  # no reveal in solo mode
    # solo rehearsals are not on the therapist's joint board
    board = p["t"].get(f"/api/v1/groups/{world.g1.id}/joint").json()
    assert all(s["id"] != solo["id"] for s in board["sessions"])


def test_board_lists_catalog_and_episodes(
    tc: TestClient, world: World, people: dict[str, Actor]
) -> None:
    board = people["t"].get(f"/api/v1/groups/{world.g1.id}/joint").json()
    assert {w["id"] for w in board["catalog"]} == {
        "lantern_forest",
        "bridge_of_two_moons",
        "floating_islands",
    }
    assert all(len(w["levels"]) == 2 for w in board["catalog"])
    eps = {e["id"]: e for e in board["episodes"]}
    assert eps["demo-lantern-forest-l2"]["status"] == "demo"
    assert eps["demo-stub-episode"]["assignable_families"]
    fam = next(f for f in board["families"] if f["id"] == str(world.f1.family.id))
    assert [pair["suitable"] for pair in fam["pairs"]] == [True, False]


def test_cancel_before_start_only(tc: TestClient, world: World, people: dict[str, Actor]) -> None:
    p = people
    sid = schedule(p["t"], world).json()["id"]
    assert p["t"].delete(f"/api/v1/joint-sessions/{sid}").status_code == 204
    assert p["teen"].get(f"/api/v1/joint/sessions/{sid}").json()["status"] == "wont_run"
    assert p["t"].delete(f"/api/v1/joint-sessions/{sid}").status_code == 409
