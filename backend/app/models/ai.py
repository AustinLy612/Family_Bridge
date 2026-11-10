"""AI layer records (Plan §4.1 AIInteraction, §5.4 caching, §7.3 evaluation; Phase 4 task 7).

- `AIInteraction`: one row per AI function call. Stores the output text (encrypted) and a hash of
  the input, never the raw participant input (Plan §4.1). Prompt id/version/hash, model, KB
  version, retrieved and cited chunk ids, grounding, validation and rule-check results,
  fallback use, latency and token counts.
- `AICacheItem`: caregiver explanations, practice items and quizzes, cached per (function, skill,
  role, language, prompt version, KB version) and reviewable by clinicians (Plan §5.8).
- `AIEvalRun`: results of `ai eval` / `ai sweep` runs (golden, adversarial, sweep).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedText
from app.core.db import Base
from app.models.entities import _enum, _now, _uuid_pk


class AIOutcome(StrEnum):
    ok = "ok"  # valid on the first attempt, no repair
    repaired = "repaired"  # JSON repair / alias remap needed
    retried = "retried"  # valid after the single regeneration
    fallback = "fallback"  # authored fallback served
    stopped = "stopped"  # streamed turn stopped by the model's own risk flag


class ContentSource(StrEnum):
    """What the participant's label says (Plan §5.4, Phase 4 task 5)."""

    ai_manual = "ai_manual"  # AI-generated, grounded in the manual
    ai_general = "ai_general"  # AI-generated, general DBT knowledge (labelled, D6)
    authored = "authored"  # static fallback / authored content
    none = "none"  # internal (e.g. risk assessment)


class AIInteraction(Base):
    __tablename__ = "ai_interaction"
    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = _now()
    function: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(8))
    caller: Mapped[str] = mapped_column(String(40))  # e.g. "lesson", "eval", "sweep", "safety"
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    skill_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_id: Mapped[str] = mapped_column(String(80))  # function/role/lang
    prompt_version: Mapped[int] = mapped_column(Integer)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    kb_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    injection_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(ARRAY(String(36)), default=list)
    cited_chunk_ids: Mapped[list[str]] = mapped_column(ARRAY(String(36)), default=list)
    retrieval_sufficient: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    grounding: Mapped[str] = mapped_column(String(10))
    source: Mapped[ContentSource] = mapped_column(_enum(ContentSource, "ai_content_source"))
    outcome: Mapped[AIOutcome] = mapped_column(_enum(AIOutcome, "ai_outcome"))
    attempts: Mapped[int] = mapped_column(Integer)
    # e.g. ["schema", "pattern:blame_shame", "provider:timeout"]; codes only, never text
    failures: Mapped[list[str]] = mapped_column(ARRAY(String(80)), default=list)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    output_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)  # JSON
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_ai_interaction_created", "created_at"),
        Index("ix_ai_interaction_function", "function", "created_at"),
    )


class CacheReview(StrEnum):
    unreviewed = "unreviewed"
    reviewed = "reviewed"
    needs_change = "needs_change"  # purged from serving; regenerated or replaced by fallback


class AICacheItem(Base):
    __tablename__ = "ai_cache_item"
    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = _now()
    function: Mapped[str] = mapped_column(String(40))
    skill_id: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(8))
    variant: Mapped[str] = mapped_column(String(20), default="standard")
    prompt_version: Mapped[int] = mapped_column(Integer)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    kb_version: Mapped[int] = mapped_column(Integer)  # 0 = no active knowledge base
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)  # authored-quality teaching text only
    source: Mapped[ContentSource] = mapped_column(_enum(ContentSource, "ai_content_source"))
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_interaction.id", ondelete="SET NULL"), nullable=True
    )
    review: Mapped[CacheReview] = mapped_column(
        _enum(CacheReview, "ai_cache_review"), default=CacheReview.unreviewed
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)

    # Unique among servable items only: an item marked "needs change" leaves the key free, so the
    # next request regenerates it and the new version comes up for review (Plan §5.8, D71).
    __table_args__ = (
        Index(
            "uq_ai_cache_key",
            "function",
            "skill_id",
            "role",
            "language",
            "variant",
            "prompt_sha256",
            "kb_version",
            unique=True,
            postgresql_where=text("review <> 'needs_change'"),
        ),
    )


class AIEvalRun(Base):
    __tablename__ = "ai_eval_run"
    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = _now()
    kind: Mapped[str] = mapped_column(String(20))  # golden | adversarial | sweep
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    passed: Mapped[bool] = mapped_column(Boolean)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)  # counts, per-case results, no PII
