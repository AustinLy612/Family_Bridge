"""Consent records (Plan §5.2; D31, D32). Records are append-only; the newest row per
(user, category) is the current decision."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.models import ConsentDocument
from app.models import ConsentRecord, User


def current(db: Session, user: User) -> dict[str, ConsentRecord]:
    rows = db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.user_id == user.id)
        .order_by(ConsentRecord.recorded_at, ConsentRecord.id)
    ).scalars()
    latest: dict[str, ConsentRecord] = {}
    for r in rows:
        latest[r.category] = r
    return latest


def has_granted(db: Session, user: User, category: str) -> bool:
    rec = current(db, user).get(category)
    return bool(rec and rec.granted)


def write(
    db: Session, user: User, doc: ConsentDocument, sha256: str, decisions: dict[str, bool]
) -> list[ConsentRecord]:
    out: list[ConsentRecord] = []
    for cat in doc.categories:
        rec = ConsentRecord(
            user_id=user.id,
            document_id=doc.id,
            document_version=doc.version,
            document_sha256=sha256,
            category=cat.id,
            grantee=cat.grantee,
            granted=decisions[cat.id],
        )
        db.add(rec)
        out.append(rec)
    db.flush()
    return out
