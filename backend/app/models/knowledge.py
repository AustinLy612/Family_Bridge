"""Knowledge base (Plan §4.1 KnowledgeDocument/KnowledgeChunk/RetrievalLog, §5.3; Phase 3).

Manual text lives only in this database, never in the repository (D7). Each ingestion run
creates a new KnowledgeDocument version; activating it supersedes the previous one and drops
the old chunks, so retrieval always reads exactly one version. Retrieval logs keep a hash of
the query, never its text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.entities import _enum, _now, _uuid_pk

EMBEDDING_DIM = 1024  # intfloat/multilingual-e5-large (D45)


class KnowledgeStatus(StrEnum):
    building = "building"
    active = "active"
    superseded = "superseded"
    failed = "failed"


class SourceQuality(StrEnum):
    pdf_text = "pdf_text"
    manual_transcription = "manual_transcription"  # diagram pages, transcribed by hand (D43)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(Integer, unique=True)
    source_name: Mapped[str] = mapped_column(String(200))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_pages: Mapped[int] = mapped_column(Integer)
    handout_index_version: Mapped[int] = mapped_column(Integer)
    embedding_model: Mapped[str] = mapped_column(String(120))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[KnowledgeStatus] = mapped_column(_enum(KnowledgeStatus, "knowledge_status"))
    # Counts and warnings only (per module/source quality, header cross-check results).
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_document.id", ondelete="CASCADE"), index=True
    )
    module: Mapped[str] = mapped_column(String(40))
    handout_id: Mapped[str] = mapped_column(String(16))
    handout_title_zh: Mapped[str] = mapped_column(String(200))
    skill_ids: Mapped[list[str]] = mapped_column(ARRAY(String(60)))
    pdf_page: Mapped[int] = mapped_column(Integer)
    pdf_pages: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    chunk_index: Mapped[int] = mapped_column(Integer)  # position within the handout
    source_quality: Mapped[SourceQuality] = mapped_column(_enum(SourceQuality, "source_quality"))
    is_worksheet: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    # jieba-segmented tokens in a 'simple' tsvector (D45).
    tokens: Mapped[str] = mapped_column(TSVECTOR)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    __table_args__ = (
        Index("ix_knowledge_chunk_tokens", "tokens", postgresql_using="gin"),
        Index("ix_knowledge_chunk_skill_ids", "skill_ids", postgresql_using="gin"),
        Index(
            "ix_knowledge_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class RetrievalLog(Base):
    """One row per search. Stores the SHA-256 of the query, never the text (Plan §5.3)."""

    __tablename__ = "retrieval_log"
    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = _now()
    caller: Mapped[str] = mapped_column(String(40))  # e.g. cli, eval, admin, lesson
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    query_sha256: Mapped[str] = mapped_column(String(64))
    query_chars: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    k: Mapped[int] = mapped_column(Integer)
    document_version: Mapped[int | None] = mapped_column(Integer)
    result_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    result_scores: Mapped[list[float]] = mapped_column(ARRAY(Float))
    top_score: Mapped[float | None] = mapped_column(Float)
    sufficient: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int] = mapped_column(Integer)
