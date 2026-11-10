"""Application settings (Plan Phase 0 task 2; Appendix D).

All values come from environment variables / `.env`. Defaults are safe for local
development with demo data only. Placeholder clinical values (thresholds, SLAs,
lesson limits) are NOT clinically validated — see Plan §8 (O3, O12, O21).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env first, then backend/.env overrides (both optional, both git-ignored).
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: Literal["development", "test", "production"] = "development"
    secret_key: SecretStr = SecretStr("change-me")
    field_encryption_key: SecretStr = SecretStr("change-me-32-byte-base64")
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    password_min_length: int = Field(default=10, ge=10)
    login_max_failures: int = 5  # then lock with exponential backoff
    login_lockout_base_seconds: int = 60
    login_lockout_max_seconds: int = 900
    login_ip_max_attempts: int = 30  # per IP per window (in-process limiter, Stage 1)
    login_ip_window_seconds: int = 300
    # Invitation/reset code checks per IP per window. Raise only on a local dev stack for the
    # full E2E suite (it redeems more codes than this from one address).
    code_ip_max_attempts: int = Field(default=20, ge=1)
    code_ip_window_seconds: int = 300
    invitation_ttl_days: int = 14
    reset_code_ttl_hours: int = 48

    # Database
    database_url: str = "postgresql+psycopg://familybridge:change-me@localhost:5432/familybridge"
    test_database_url: str = (
        "postgresql+psycopg://familybridge:change-me@localhost:5432/test_familybridge"
    )
    # Least privilege (Plan §5.12): migrations run as the owner (MIGRATION_DATABASE_URL, falls
    # back to DATABASE_URL); the API connects as APP_DB_USER, which has DML only and cannot
    # UPDATE/DELETE the audit log. `migrate` creates or updates that login role when
    # APP_DB_PASSWORD is set.
    migration_database_url: str | None = None
    app_db_user: str = Field(default="familybridge_app", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    app_db_password: SecretStr = SecretStr("")

    # Content
    content_dir: Path = REPO_ROOT / "content"

    # LLM (DeepSeek) — key only ever read from the environment (.env)
    llm_provider: Literal["deepseek", "mock"] = "deepseek"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"  # D48 (thinking mode disabled)
    llm_timeout_seconds: int = 30
    llm_max_output_tokens: int = 2048
    llm_temperature: float = Field(default=0.4, ge=0, le=1.5)
    llm_max_retries: int = Field(default=2, ge=0, le=5)  # on 429/5xx/timeouts, with jitter
    llm_breaker_failures: int = Field(default=5, ge=1)  # consecutive failures that open it
    llm_breaker_cooldown_seconds: int = Field(default=60, ge=1)

    # Knowledge base
    knowledge_source_dir: Path = REPO_ROOT / "docs"
    # Local, git-ignored working area: model cache, page renders, diagram transcriptions (D43).
    knowledge_work_dir: Path = REPO_ROOT / "knowledge"
    embedding_provider: Literal["fastembed", "hash"] = "fastembed"  # "hash" = offline test fake
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_cache_dir: Path = REPO_ROOT / "knowledge" / "models"
    rag_top_k: int = 5
    # Top cosine similarity needed to call retrieval "sufficient", per query language.
    # Calibrated for multilingual-e5-large with `kb eval` (D46); re-calibrate if the model changes.
    rag_min_score_zh: float = 0.83
    rag_min_score_en: float = 0.775

    # Safety (placeholders — O3, O12)
    diary_urge_threshold: int = Field(default=7, ge=1, le=10)
    safety_ack_sla_hours: int = 24

    # Joint sessions
    room_disconnect_pause_seconds: int = 60

    # Adolescent lessons (placeholders — O21)
    lesson_message_max_chars: int = 500
    lesson_max_turns: int = 30
    skill_repeat_window: int = 3
    skill_test_mastery_correct: int = 4
    skill_test_max_output_tokens: int = 8192

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator(
        "content_dir",
        "knowledge_source_dir",
        "knowledge_work_dir",
        "embedding_cache_dir",
        mode="after",
    )
    @classmethod
    def _resolve_relative_to_backend(cls, v: Path) -> Path:
        # Relative paths in .env (e.g. KNOWLEDGE_SOURCE_DIR=../docs) are relative to backend/.
        return v if v.is_absolute() else (BACKEND_DIR / v).resolve()

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
