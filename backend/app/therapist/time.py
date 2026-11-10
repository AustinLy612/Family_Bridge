"""Therapist active time per family (§8.4 "therapist time per family"; Plan §5.8).

The dashboard reports focused seconds while a family's screens are visible and the window has
focus. Each report is capped, so a stuck tab cannot inflate the total, and seconds are summed
per therapist, family and site day. Nothing about what was viewed is stored.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.diary.entries import site_today
from app.models import Family, TherapistTime, User

MAX_REPORT_SECONDS = 120


def record(db: Session, therapist: User, family: Family, seconds: int) -> None:
    if not 1 <= seconds <= MAX_REPORT_SECONDS:
        raise bad_request("time.invalid_seconds")
    stmt = insert(TherapistTime).values(
        therapist_id=therapist.id, family_id=family.id, day=site_today(db), seconds=seconds
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["therapist_id", "family_id", "day"],
            set_={"seconds": TherapistTime.seconds + stmt.excluded.seconds},
        )
    )
