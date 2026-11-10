"""Least privilege (Plan §5.12): the API's database role has DML only, no DDL, and cannot
change or delete audit entries."""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ProgrammingError

from app.core.db import ensure_app_role, make_engine

USER = "familybridge_app_test"


@pytest.fixture
def app_engine(clean_db: Engine) -> Iterator[Engine]:
    owner = clean_db.url.render_as_string(hide_password=False)
    password = secrets.token_urlsafe(24)
    ensure_app_role(owner, USER, password)
    ensure_app_role(owner, USER, password)  # idempotent
    url = make_url(owner).set(username=USER, password=password)
    eng = make_engine(url.render_as_string(hide_password=False))
    yield eng
    eng.dispose()


def test_app_role_can_read_and_write_data(app_engine: Engine) -> None:
    with app_engine.begin() as c:
        c.execute(text("SELECT count(*) FROM app_user")).scalar_one()
        c.execute(
            text("INSERT INTO research_event (event_type, props) VALUES ('login_failure', '{}')")
        )
        c.execute(text("DELETE FROM research_event WHERE event_type = 'login_failure'"))


@pytest.mark.parametrize(
    "stmt",
    [
        "CREATE TABLE sneaky (id int)",
        "DROP TABLE research_event",
        "ALTER TABLE app_user ADD COLUMN x int",
        "UPDATE audit_log SET action = 'x'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
        "UPDATE alembic_version SET version_num = 'x'",
    ],
)
def test_app_role_cannot_change_schema_or_audit(app_engine: Engine, stmt: str) -> None:
    with (
        pytest.raises(ProgrammingError, match=r"permission denied|must be owner"),
        app_engine.begin() as c,
    ):
        c.execute(text(stmt))


def test_app_role_can_append_audit_entries(app_engine: Engine) -> None:
    with app_engine.begin() as c:
        before = c.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
    from sqlalchemy.orm import Session

    from app.core import audit

    with Session(app_engine) as db, db.begin():
        audit.record(db, "test.least_privilege")
    with app_engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar_one() == before + 1
