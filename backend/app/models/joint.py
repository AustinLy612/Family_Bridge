"""Phase 8 joint sessions and episode engine records (Plan §4.1, §5.9).

- `EpisodeApproval`: registry decisions on episode versions (approve / retire). The content
  file's own approval is the starting status; the latest decision here overrides it.
- `JointSession`: one adolescent + one caregiver (or one participant in solo rehearsal) + an
  episode version + a window. Room state is a persisted snapshot plus an append-only
  `RoomEvent` log, so a restart or reconnect resumes the same step.
- `JointSessionResponse`: accept / decline per participant, no reason asked (§9.1C).
- `SharedCompletionRecord`: minimal shared outcome (§5.3); never private choices, reflections
  or distress ratings.
- `PrivateReflection` (encrypted) and `DistressRating`: private per participant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedText
from app.core.db import Base
from app.models.entities import _now, _uuid_pk

USER_FK = "app_user.id"
SESSION_FK = "joint_session.id"


class SessionStatus(StrEnum):
    invited = "invited"  # waiting for responses, or accepted and waiting for the room
    declined = "declined"  # someone said "not this time"; it will not run
    cancelled = "cancelled"  # the therapist withdrew it before it started
    active = "active"  # the room has started
    completed = "completed"
    ended = "ended"  # left or ended before the last step (partial completion)


class Response(StrEnum):
    accepted = "accepted"
    declined = "declined"


class EpisodeApproval(Base):
    __tablename__ = "episode_approval"
    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[str] = mapped_column(String(64), index=True)
    episode_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # approved | retired
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(USER_FK, ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime] = _now()


class JointSession(Base):
    __tablename__ = "joint_session"
    id: Mapped[uuid.UUID] = _uuid_pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="joint")  # joint | solo
    adolescent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(USER_FK), nullable=True)
    caregiver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(USER_FK), nullable=True)
    episode_id: Mapped[str] = mapped_column(String(64))
    episode_version: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SessionStatus] = mapped_column(String(16), default=SessionStatus.invited)
    # Server-owned room state (app/joint/engine.py) and the last stamped sequence number.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(USER_FK, ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)

    def participant_ids(self) -> list[uuid.UUID]:
        return [u for u in (self.adolescent_id, self.caregiver_id) if u is not None]


class JointSessionResponse(Base):
    __tablename__ = "joint_session_response"
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(SESSION_FK, ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK))
    response: Mapped[Response] = mapped_column(String(10))
    responded_at: Mapped[datetime] = _now()
    # Self-reported when joining (§5.10 "join location"); never inferred.
    join_location: Mapped[str | None] = mapped_column(String(10), nullable=True)
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_joint_response"),)


class RoomEvent(Base):
    """Append-only typed log of accepted room actions. Payloads hold ids and tags, no free text."""

    __tablename__ = "room_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(SESSION_FK, ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(USER_FK), nullable=True)
    actor_role: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(24))
    step_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_room_event_seq"),
        Index(
            "uq_room_event_idem",
            "session_id",
            "actor_id",
            "idempotency_key",
            unique=True,
        ),
    )


class SharedCompletionRecord(Base):
    __tablename__ = "shared_completion_record"
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(SESSION_FK, ondelete="CASCADE"), unique=True
    )
    episode_id: Mapped[str] = mapped_column(String(64))
    episode_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))  # completed | partial
    completed_step_ids: Mapped[list[str]] = mapped_column(ARRAY(String(24)), default=list)
    skipped_step_ids: Mapped[list[str]] = mapped_column(ARRAY(String(24)), default=list)
    shared_rubric_tags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime] = _now()


class PrivateReflection(Base):
    __tablename__ = "private_reflection"
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(SESSION_FK, ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK))
    step_id: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(EncryptedText)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()


class DistressRating(Base):
    __tablename__ = "distress_rating"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(SESSION_FK, ondelete="CASCADE"), nullable=True, index=True
    )
    context: Mapped[str] = mapped_column(String(16), default="episode_step")
    step_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    value: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # None = skipped
    created_at: Mapped[datetime] = _now()
