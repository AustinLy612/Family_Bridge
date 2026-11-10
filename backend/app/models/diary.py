"""Diary Cards (Plan §4.1, §5.6; Phase 6 task 1-4).

Separate, private, role-specific cards. Values and notes are stored encrypted (Plan §5.12);
every save appends a full revision (correction log, §8.4), so nothing is ever overwritten
without a trace. Entries are readable by their owner and, per D15, by the group's therapist
(audited). The other family member sees only what the owner shared (D66): a share is a
snapshot of chosen fields from one entry, revocable at any time.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedText
from app.core.db import Base
from app.models.entities import Role, _enum, _now, _uuid_pk

USER_FK = "app_user.id"


class DiaryEntry(Base):
    """One diary entry. Several per day are allowed (D64); past 7 days are editable (D65)."""

    __tablename__ = "diary_entry"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    template_version: Mapped[int] = mapped_column(SmallInteger)
    entry_date: Mapped[date] = mapped_column(Date)
    # JSON object of field id -> value (note excluded), encrypted (Plan §5.12).
    values_json: Mapped[str] = mapped_column(EncryptedText)
    note: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # Added after its day (research only, §8.4; never shown as a reproach).
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_diary_entry_user_date", "user_id", "entry_date"),)


class DiaryRevision(Base):
    """Append-only history: one row per save, including the first."""

    __tablename__ = "diary_revision"
    id: Mapped[uuid.UUID] = _uuid_pk()
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diary_entry.id", ondelete="CASCADE"))
    revision_no: Mapped[int] = mapped_column(Integer)
    entry_date: Mapped[date] = mapped_column(Date)
    values_json: Mapped[str] = mapped_column(EncryptedText)
    note: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    saved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    saved_at: Mapped[datetime] = _now()

    __table_args__ = (UniqueConstraint("entry_id", "revision_no", name="ux_diary_revision_no"),)


class DiaryShare(Base):
    """Owner-initiated share of chosen fields from one entry with one family member (D66).

    `snapshot_json` holds exactly what the owner previewed; later edits to the entry do not
    change it. Revoking sets `revoked_at`, after which the recipient can no longer read it.
    """

    __tablename__ = "diary_share"
    id: Mapped[uuid.UUID] = _uuid_pk()
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diary_entry.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    owner_role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    template_version: Mapped[int] = mapped_column(SmallInteger)
    entry_date: Mapped[date] = mapped_column(Date)
    field_ids: Mapped[list[str]] = mapped_column(JSONB)
    snapshot_json: Mapped[str] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = _now()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_diary_share_recipient", "recipient_id", "revoked_at"),
        Index("ix_diary_share_entry", "entry_id"),
    )


def decode_values(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}
