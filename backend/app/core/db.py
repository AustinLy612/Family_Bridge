"""Database engine, sessions and readiness checks (Plan Phase 0 task 3)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import BACKEND_DIR, get_settings


class Base(DeclarativeBase):
    """Declarative base for all models (models are added from Phase 1)."""


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if database_url is not None:
        # '%' must be escaped for configparser interpolation.
        cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def migration_heads() -> set[str]:
    return set(ScriptDirectory.from_config(alembic_config()).get_heads())


@dataclass(frozen=True)
class DbStatus:
    reachable: bool
    at_head: bool
    current: tuple[str, ...]
    expected: tuple[str, ...]
    error: str | None = None


def check_database(engine: Engine) -> DbStatus:
    expected = tuple(sorted(migration_heads()))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            current = tuple(sorted(MigrationContext.configure(conn).get_current_heads()))
    except Exception as exc:  # report, never raise, from a health check
        return DbStatus(False, False, (), expected, error=type(exc).__name__)
    return DbStatus(True, current == expected, current, expected)


APP_GROUP_ROLE = "familybridge_app_rw"  # created by migration 0011_least_privilege


def ensure_app_role(owner_url: str, user: str, password: str) -> None:
    """Create or update the API's login role as a member of the DML-only group (Plan §5.12)."""
    from psycopg import sql

    engine = make_engine(owner_url)
    try:
        with engine.begin() as conn:
            raw = conn.connection.driver_connection
            exists = conn.exec_driver_sql(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)
            ).first()
            verb = "ALTER" if exists else "CREATE"
            with raw.cursor() as cur:  # type: ignore[union-attr]
                cur.execute(
                    sql.SQL(
                        verb + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(user), sql.Literal(password))
                )
                cur.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(APP_GROUP_ROLE), sql.Identifier(user)
                    )
                )
    finally:
        engine.dispose()
