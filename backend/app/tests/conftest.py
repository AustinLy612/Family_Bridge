"""Shared fixtures. DB fixtures run only against a guarded `test_*` database."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.db import alembic_config, make_engine
from app.core.test_db_guard import assert_safe_test_database
from app.main import create_app
from app.settings import Settings
from app.tests.factories import World, make_world


@pytest.fixture(scope="session")
def settings() -> Settings:
    base = Settings()
    # Tests never call DeepSeek or load a sentence-transformer, whatever .env says; security
    # limits are the production defaults even if a local .env raises them for E2E runs.
    return base.model_copy(
        update={
            "app_env": "test",
            "llm_provider": "mock",
            "embedding_provider": "hash",
            "code_ip_max_attempts": 20,
        }
    )


@pytest.fixture(scope="session")
def test_db_url(settings: Settings) -> str:
    try:
        assert_safe_test_database(settings.test_database_url, settings.database_url)
    except RuntimeError as exc:
        pytest.exit(str(exc), returncode=2)
    return settings.test_database_url


@pytest.fixture(scope="session")
def db_engine(test_db_url: str) -> Iterator[Engine]:
    """Create the test database if needed, migrate it to head, and yield an engine."""
    url = make_url(test_db_url)
    admin = make_engine(url.set(database="postgres").render_as_string(hide_password=False))
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    cfg = alembic_config(test_db_url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    engine = make_engine(test_db_url)
    yield engine
    engine.dispose()


def make_client(
    settings: Settings, engine: Engine | None = None, **overrides: object
) -> TestClient:
    s = settings.model_copy(update=overrides) if overrides else settings
    factory = (lambda: engine) if engine is not None else None
    return TestClient(create_app(s, engine_factory=factory))


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    d = tmp_path / "content"
    (d / "skills").mkdir(parents=True)
    return d


# --- Phase 1 fixtures -------------------------------------------------------------------------

# Everything except audit_log, which is append-only (trigger) and keeps growing across tests;
# its chain stays valid because tests never modify it permanently.
_TRUNCATE = (
    "TRUNCATE room_event, shared_completion_record, private_reflection, distress_rating, "
    "joint_session_response, joint_session, episode_approval, "
    "recruitment_count, task_completion, task, therapist_time, "
    "diary_share, diary_revision, diary_entry, "
    "quiz_attempt, practice_attempt, caregiver_lesson, skill_test_question, "
    "mood_record, skill_test, chat_message, teaching_session, group_skill_record, "
    "skill_progress, learner_profile, "
    "ai_cache_item, ai_interaction, ai_eval_run, "
    "retrieval_log, knowledge_chunk, knowledge_document, "
    "safety_event_note, safety_event, research_event, auth_session, setting, "
    "dyad_suitability, consent_record, invitation, family_member, family, group_therapist, "
    "dbt_group, app_user, site "
    "RESTART IDENTITY CASCADE"
)


@pytest.fixture
def clean_db(db_engine: Engine) -> Iterator[Engine]:
    from app.core.security import code_limiter, login_limiter

    with db_engine.begin() as conn:
        conn.execute(text(_TRUNCATE))
    login_limiter.reset()
    code_limiter.reset()
    yield db_engine


@pytest.fixture
def db(clean_db: Engine) -> Iterator[Session]:
    with Session(clean_db, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def world(db: Session) -> World:
    return make_world(db)


@pytest.fixture
def client(settings: Settings, clean_db: Engine) -> Iterator[TestClient]:
    with make_client(settings, clean_db) as c:
        yield c


@pytest.fixture
def new_client(settings: Settings, clean_db: Engine) -> Callable[[], TestClient]:
    """Extra independent browsers (separate cookie jars)."""
    return lambda: make_client(settings, clean_db)
