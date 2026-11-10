"""Append-only, hash-chained audit log (Plan §4.1 AuditLog, §5.12).

Every entry's hash covers its content and the previous entry's hash, so editing or deleting any
row breaks verification from that point on. Appends take a transaction-scoped advisory lock so
concurrent writers cannot fork the chain. A DB trigger (migration 0002) rejects UPDATE/DELETE.

Never put sensitive content in `details` (no diary text, no passwords, no codes): ids and
category names only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.models import AuditLog, User

GENESIS = "0" * 64
_LOCK_KEY = 72_000_001  # arbitrary constant for pg_advisory_xact_lock


def _canonical(entry: dict[str, Any]) -> bytes:
    return json.dumps(
        entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()


def entry_hash(
    *,
    occurred_at: datetime,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    request_id: str | None,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    payload = {
        "occurred_at": occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor_id": str(actor_id) if actor_id else None,
        "actor_role": actor_role,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "request_id": request_id,
        "details": details,
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry in the caller's transaction (committed with the change it records)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    prev = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
    occurred_at = datetime.now(UTC)
    fields: dict[str, Any] = {
        "occurred_at": occurred_at,
        "actor_id": actor.id if actor else None,
        "actor_role": actor.role.value if actor else None,
        "action": action,
        "target_type": target_type,
        "target_id": str(target_id) if target_id is not None else None,
        "request_id": request_id_var.get(),
        "details": details or {},
        "prev_hash": prev or GENESIS,
    }
    entry = AuditLog(**fields, hash=entry_hash(**fields))
    db.add(entry)
    db.flush()
    return entry


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    entries: int
    first_bad_id: int | None = None
    reason: str | None = None


def verify_chain(db: Session) -> ChainReport:
    prev = GENESIS
    n = 0
    for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        n += 1
        if row.prev_hash != prev:
            return ChainReport(False, n, row.id, "prev_hash does not match the previous entry")
        expected = entry_hash(
            occurred_at=row.occurred_at,
            actor_id=row.actor_id,
            actor_role=row.actor_role,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            request_id=row.request_id,
            details=row.details,
            prev_hash=row.prev_hash,
        )
        if row.hash != expected:
            return ChainReport(False, n, row.id, "content does not match its hash")
        prev = row.hash
    return ChainReport(True, n)
