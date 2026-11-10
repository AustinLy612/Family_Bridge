"""Tests refuse to run against a non-test database (Plan Phase 0 task 3)."""

from __future__ import annotations

import pytest

from app.core.test_db_guard import UnsafeTestDatabaseError, assert_safe_test_database

APP = "postgresql+psycopg://u:p@localhost:5432/familybridge"


def test_accepts_test_prefixed_database() -> None:
    url = "postgresql+psycopg://u:p@localhost:5432/test_familybridge"
    assert assert_safe_test_database(url, APP) == "test_familybridge"


@pytest.mark.parametrize("name", ["familybridge", "prod", "familybridge_test", "postgres", ""])
def test_rejects_non_test_database(name: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        assert_safe_test_database(f"postgresql+psycopg://u:p@localhost:5432/{name}", APP)


def test_rejects_application_database_even_if_test_prefixed() -> None:
    app = "postgresql+psycopg://u:p@localhost:5432/test_x"
    with pytest.raises(UnsafeTestDatabaseError, match="application database"):
        assert_safe_test_database(app, app)
