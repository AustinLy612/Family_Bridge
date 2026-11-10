"""Admin knowledge-base status (Plan §5.3, §6.1 admin "Knowledge base"; Phase 3 task 7).

Read-only: versions, chunk counts, ingestion warnings, the last recorded evaluation and
retrieval-log totals. No manual text is ever returned (D7); ingestion runs from the CLI.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import AdminUser, AppSettings, Db
from app.core.sessions import utcnow
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus, RetrievalLog

router = APIRouter(prefix="/api/v1/admin/kb", tags=["admin"])

RETRIEVAL_WINDOW_DAYS = 7


class EvalBucket(BaseModel):
    queries: int
    recall: float
    mrr: float


class EvalSummary(BaseModel):
    passed: bool
    k: int
    target_recall: float
    eval_set_version: int | None
    overall: EvalBucket
    by_language: dict[str, EvalBucket]
    misses: int


class HeaderMismatch(BaseModel):
    page: int
    found: str
    expected: str


class KbVersion(BaseModel):
    version: int
    status: KnowledgeStatus
    created_at: datetime
    activated_at: datetime | None
    chunk_count: int
    embedding_model: str
    source_pages: int
    handout_index_version: int
    handouts: int
    chunks_by_module: dict[str, int]
    chunks_by_source_quality: dict[str, int]
    transcribed_pages: list[int]
    header_mismatches: list[HeaderMismatch]
    eval: EvalSummary | None


class KbHistoryItem(BaseModel):
    version: int
    status: KnowledgeStatus
    chunk_count: int
    created_at: datetime


class RetrievalTotals(BaseModel):
    days: int
    searches: int
    insufficient: int
    median_latency_ms: int | None


class KbStatus(BaseModel):
    active: KbVersion | None
    history: list[KbHistoryItem]
    retrieval: RetrievalTotals
    min_score: dict[str, float]


def _eval(stats: dict[str, Any]) -> EvalSummary | None:
    ev = stats.get("eval")
    if not isinstance(ev, dict):
        return None
    return EvalSummary(
        passed=bool(ev.get("passed")),
        k=int(ev.get("k", 5)),
        target_recall=float(ev.get("target_recall", 0.85)),
        eval_set_version=ev.get("eval_set_version"),
        overall=EvalBucket(**ev["overall"]),
        by_language={k: EvalBucket(**v) for k, v in ev.get("by_language", {}).items()},
        misses=len(ev.get("misses", [])),
    )


def _version(d: KnowledgeDocument) -> KbVersion:
    s = d.stats or {}
    return KbVersion(
        version=d.version,
        status=d.status,
        created_at=d.created_at,
        activated_at=d.activated_at,
        chunk_count=d.chunk_count,
        embedding_model=d.embedding_model,
        source_pages=d.source_pages,
        handout_index_version=d.handout_index_version,
        handouts=int(s.get("handouts", 0)),
        chunks_by_module=dict(s.get("chunks_by_module", {})),
        chunks_by_source_quality=dict(s.get("chunks_by_source_quality", {})),
        transcribed_pages=list(s.get("transcribed_pages", [])),
        header_mismatches=[HeaderMismatch(**m) for m in s.get("header_mismatches", [])],
        eval=_eval(s),
    )


@router.get("")
def kb_status(admin: AdminUser, db: Db, settings: AppSettings) -> KbStatus:
    docs = list(
        db.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.version.desc())).scalars()
    )
    active = next((d for d in docs if d.status == KnowledgeStatus.active), None)
    since = utcnow() - timedelta(days=RETRIEVAL_WINDOW_DAYS)
    searches, insufficient, median = db.execute(
        select(
            func.count(),
            func.count().filter(RetrievalLog.sufficient.is_(False)),
            func.percentile_cont(0.5).within_group(RetrievalLog.latency_ms),
        ).where(RetrievalLog.created_at >= since)
    ).one()
    return KbStatus(
        active=_version(active) if active else None,
        history=[
            KbHistoryItem(
                version=d.version,
                status=d.status,
                chunk_count=d.chunk_count,
                created_at=d.created_at,
            )
            for d in docs[:10]
        ],
        retrieval=RetrievalTotals(
            days=RETRIEVAL_WINDOW_DAYS,
            searches=searches,
            insufficient=insufficient,
            median_latency_ms=round(median) if median is not None else None,
        ),
        min_score={"zh-CN": settings.rag_min_score_zh, "en": settings.rag_min_score_en},
    )
