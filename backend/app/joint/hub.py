"""In-process WebSocket hub for joint rooms (Plan §5.9 "WebSocket protocol").

Room state lives in Postgres (snapshot + `RoomEvent` log); the hub only tracks live connections
(presence) and fans out role-projected state. The API runs as one uvicorn process (Dockerfile),
so one hub sees every connection. Running several API processes would need a shared channel
such as Postgres LISTEN/NOTIFY (noted in D78).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.content.loader import ContentBundle
from app.joint import engine, service
from app.models import JointSession

SessionFactory = Callable[[], Session]


@dataclass
class Conn:
    ws: WebSocket
    user_id: uuid.UUID
    role: str


@dataclass
class Room:
    conns: list[Conn] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    timers: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    def present(self) -> set[str]:
        return {c.role for c in self.conns}


class Hub:
    def __init__(
        self, content: ContentBundle, session_factory: SessionFactory, disconnect_seconds: int
    ) -> None:
        self.content = content
        self.session_factory = session_factory
        self.disconnect_seconds = disconnect_seconds
        self.rooms: dict[uuid.UUID, Room] = {}
        self._episodes: dict[uuid.UUID, Any] = {}

    def room(self, sid: uuid.UUID) -> Room:
        return self.rooms.setdefault(sid, Room())

    def present(self, sid: uuid.UUID) -> set[str]:
        room = self.rooms.get(sid)
        return room.present() if room else set()

    # --- database work, run in a worker thread -----------------------------------------

    def _tx(self, fn: Callable[[Session], Any]) -> Any:
        with self.session_factory() as db:
            try:
                out = fn(db)
                db.commit()
                return out
            except Exception:
                db.rollback()
                raise

    async def run(self, fn: Callable[[Session], Any]) -> Any:
        return await run_in_threadpool(self._tx, fn)

    # --- fan-out -----------------------------------------------------------------------

    async def episode(self, sid: uuid.UUID) -> Any:
        if sid not in self._episodes:

            def load(db: Session) -> tuple[str, int]:
                s = db.get(JointSession, sid)
                assert s is not None
                return s.episode_id, s.episode_version

            ep_id, ver = await self.run(load)
            self._episodes[sid] = self.content.episode(ep_id, ver)
        return self._episodes[sid]

    async def broadcast(
        self, sid: uuid.UUID, state: dict[str, Any] | None = None, seq: int | None = None
    ) -> None:
        room = self.rooms.get(sid)
        if room is None or not room.conns:
            return
        if state is None or seq is None:

            def load(db: Session) -> tuple[dict[str, Any], int]:
                s = db.get(JointSession, sid)
                assert s is not None
                return s.snapshot, s.seq

            state, seq = await self.run(load)
        episode = await self.episode(sid)
        present = room.present()
        for c in list(room.conns):
            partner_present = bool(present - {c.role}) if len(state["roles"]) > 1 else None
            view = engine.project_for_role(episode, state, c.role, partner_present=partner_present)
            await self._send(room, c, {"type": "state", "seq": seq, "state": view})

    async def _send(self, room: Room, c: Conn, msg: dict[str, Any]) -> None:
        # a closed socket is cleaned up by its own receive loop
        with contextlib.suppress(Exception):
            await c.ws.send_json(msg)

    async def send_to(self, sid: uuid.UUID, user_id: uuid.UUID, msg: dict[str, Any]) -> None:
        room = self.rooms.get(sid)
        if room:
            for c in [c for c in room.conns if c.user_id == user_id]:
                await self._send(room, c, msg)

    async def notify(self, sid: uuid.UUID, msg: dict[str, Any]) -> None:
        room = self.rooms.get(sid)
        if room:
            for c in list(room.conns):
                await self._send(room, c, msg)

    # --- presence ----------------------------------------------------------------------

    async def connect(self, sid: uuid.UUID, conn: Conn) -> None:
        room = self.room(sid)
        returning = conn.role not in room.present()
        room.conns.append(conn)
        timer = room.timers.pop(conn.role, None)
        if timer is not None:
            timer.cancel()
        if returning:
            await self.notify(sid, {"type": "presence", "role": conn.role, "present": True})
            present = room.present()
            async with room.lock:
                out = await self.run(
                    lambda db: service.system_update(db, self.content, sid, "recheck", present)
                )
            if out is not None:
                await self.broadcast(sid, out.state, out.seq)
                return
        await self.broadcast(sid)

    async def disconnect(self, sid: uuid.UUID, conn: Conn) -> None:
        room = self.rooms.get(sid)
        if room is None:
            return
        if conn in room.conns:
            room.conns.remove(conn)
        if conn.role in room.present():
            return  # another tab of the same person is still connected
        await self.notify(sid, {"type": "presence", "role": conn.role, "present": False})
        await self.broadcast(sid)
        if self.disconnect_seconds > 0:
            room.timers[conn.role] = asyncio.create_task(self._auto_pause(sid, conn.role))
        if not room.conns:
            pass  # keep the Room (timers) until the session finishes; it holds no state

    async def _auto_pause(self, sid: uuid.UUID, role: str) -> None:
        await asyncio.sleep(self.disconnect_seconds)
        room = self.rooms.get(sid)
        if room is None or role in room.present():
            return
        async with room.lock:
            out = await self.run(
                lambda db: service.system_update(
                    db, self.content, sid, "auto_pause", room.present()
                )
            )
        room.timers.pop(role, None)
        if out is not None:
            await self.notify(sid, {"type": "paused", "pause": "pause"})
            await self.broadcast(sid, out.state, out.seq)

    # --- actions -----------------------------------------------------------------------

    async def act(
        self,
        sid: uuid.UUID,
        conn: Conn,
        action: dict[str, Any],
        user_loader: Callable[[Session], Any],
        safety: Any,
    ) -> None:
        room = self.room(sid)
        started = time.perf_counter()
        async with room.lock:
            present = room.present()

            def do(db: Session) -> service.Outcome:
                user = user_loader(db)
                return service.act(db, self.content, safety, sid, user, action, present)

            out: service.Outcome = await self.run(do)
        await self._send(
            room,
            conn,
            {"type": "ack", "id": action.get("id"), "seq": out.seq, "duplicate": out.duplicate},
        )
        for msg in out.to_actor:
            await self.send_to(sid, conn.user_id, msg)
        if not out.duplicate:
            await self._after_change(sid, out)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if not out.duplicate:

            def log(db: Session) -> None:
                service.research(
                    db,
                    "joint.latency",
                    None,
                    session=str(sid),
                    ms=elapsed_ms,
                    action=str(action.get("type")),
                )

            await self.run(log)

    async def therapist_control(
        self, sid: uuid.UUID, fn: Callable[[Session, set[str]], service.Outcome]
    ) -> service.Outcome:
        room = self.room(sid)
        async with room.lock:
            present = room.present()
            out: service.Outcome = await self.run(lambda db: fn(db, present))
        await self._after_change(sid, out)
        return out

    async def _after_change(self, sid: uuid.UUID, out: service.Outcome) -> None:
        phase = out.state["phase"]
        if phase in ("paused", "paused_safety"):
            kind = "hold" if out.state["pause"]["by"] in engine.STAFF_HOLDS else "pause"
            await self.notify(sid, {"type": "paused", "pause": kind})
        elif phase in ("ended", "completed"):
            await self.notify(sid, {"type": "ended", "status": phase})
        await self.broadcast(sid, out.state, out.seq)
