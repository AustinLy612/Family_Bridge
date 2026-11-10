"""Test-database isolation (Plan Phase 0 task 3, as in DBT_Revised).

Tests must never touch a non-test database. The guard refuses unless the target
database name starts with `test_` and differs from the application DATABASE_URL.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url


class UnsafeTestDatabaseError(RuntimeError):
    pass


def assert_safe_test_database(test_url: str, app_url: str) -> str:
    """Return the test database name, or raise if the URL is not clearly a test database."""
    test = make_url(test_url)
    app = make_url(app_url)
    name = test.database or ""
    if not name.startswith("test_"):
        raise UnsafeTestDatabaseError(
            f"Refusing to run tests: database '{name}' does not start with 'test_'."
        )
    same_server = (test.host, test.port) == (app.host, app.port)
    if same_server and name == (app.database or ""):
        raise UnsafeTestDatabaseError(
            "Refusing to run tests: TEST_DATABASE_URL points at the application database."
        )
    return name
