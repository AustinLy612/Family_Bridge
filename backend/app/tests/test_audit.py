"""Append-only, hash-chained audit log (Plan §5.12)."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core import audit
from app.models import AuditLog
from app.tests.factories import World

pytestmark = pytest.mark.db


def _append(db: Session, n: int = 3) -> list[AuditLog]:
    rows = [audit.record(db, "test.event", target_type="test", details={"i": i}) for i in range(n)]
    db.commit()
    return rows


def test_chain_verifies(db: Session, world: World) -> None:
    _append(db)
    report = audit.verify_chain(db)
    assert report.ok and report.entries >= 3


def test_update_and_delete_blocked_by_trigger(db: Session, world: World) -> None:
    row = _append(db, 1)[0]
    for sql in (
        "UPDATE audit_log SET action = 'x' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql), {"id": row.id})
        db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("TRUNCATE audit_log"))
    db.rollback()


def test_tampering_is_detected(db: Session, clean_db: Engine, world: World) -> None:
    rows = _append(db, 3)
    target = rows[1]
    original = dict(target.details)
    # Simulate an attacker with table-owner rights who disables the trigger.
    with clean_db.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
        conn.execute(
            text("UPDATE audit_log SET details = '{\"i\": 999}' WHERE id = :id"), {"id": target.id}
        )
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER USER"))
    try:
        db.expire_all()
        report = audit.verify_chain(db)
        assert not report.ok
        assert report.first_bad_id == target.id
        assert report.reason == "content does not match its hash"
    finally:
        with clean_db.begin() as conn:
            conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
            conn.execute(
                text("UPDATE audit_log SET details = CAST(:d AS jsonb) WHERE id = :id"),
                {"d": __import__("json").dumps(original), "id": target.id},
            )
            conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER USER"))
    db.expire_all()
    assert audit.verify_chain(db).ok


def test_deleted_entry_breaks_chain(db: Session, clean_db: Engine, world: World) -> None:
    rows = _append(db, 3)
    victim = rows[1]
    saved = {c.name: getattr(victim, c.key) for c in AuditLog.__table__.columns}
    with clean_db.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": victim.id})
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER USER"))
    try:
        db.expire_all()
        report = audit.verify_chain(db)
        assert not report.ok and report.first_bad_id == rows[2].id
        assert report.reason == "prev_hash does not match the previous entry"
    finally:
        with Session(clean_db) as s, s.begin():
            s.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
            s.add(AuditLog(**saved))
            s.flush()
            s.execute(text("ALTER TABLE audit_log ENABLE TRIGGER USER"))
    db.expire_all()
    assert audit.verify_chain(db).ok


def test_audit_details_never_contain_codes_or_passwords(db: Session, world: World) -> None:
    # Spot check over everything the suite has written so far.
    for row in db.execute(select(AuditLog)).scalars():
        blob = str(row.details).lower()
        assert "password" not in blob and 'code":' not in blob
