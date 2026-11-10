"""Admin AI-layer status (Plan §5.4, §7.3; Phase 4). Read-only.

Provider, model and circuit-breaker state; prompt registry versions and approval; call counts,
fallbacks and rule-check failure codes over the last 7 days; cache size; recent evaluation runs.
Never returns prompts' rendered text, participant input or model output.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai.schemas import FUNCTIONS
from app.ai.service import AIService
from app.api.deps import AdminUser, Db
from app.content.models import FallbackDoc, PromptTemplate
from app.core.sessions import utcnow
from app.models.ai import AICacheItem, AIEvalRun, AIInteraction, AIOutcome

router = APIRouter(prefix="/api/v1/admin/ai", tags=["admin"])

WINDOW_DAYS = 7


class FunctionStats(BaseModel):
    function: str
    calls: int
    fallbacks: int
    repaired: int
    retried: int
    general: int  # answered as labelled general knowledge
    median_latency_ms: int | None


class PromptInfo(BaseModel):
    function: str
    role: str
    language: str
    version: int
    approval: str


class EvalRunInfo(BaseModel):
    kind: str
    created_at: datetime
    provider: str
    model: str
    passed: bool
    headline: dict[str, Any]


class AiStatus(BaseModel):
    provider: str
    model: str
    breaker: str
    days: int
    calls: int
    fallbacks: int
    functions: list[FunctionStats]
    failure_codes: dict[str, int]
    prompts: list[PromptInfo]
    fallback_files: int
    cache_items: int
    cache_by_review: dict[str, int]
    eval_runs: list[EvalRunInfo]


@router.get("", response_model=AiStatus)
def ai_status(request: Request, db: Db, _admin: AdminUser) -> AiStatus:
    ai: AIService = request.app.state.ai
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    rows = db.execute(
        select(
            AIInteraction.function,
            AIInteraction.outcome,
            AIInteraction.source,
            AIInteraction.latency_ms,
            AIInteraction.failures,
            AIInteraction.cache_hit,
        ).where(AIInteraction.created_at >= since)
    ).all()
    by_fn: dict[str, list[Any]] = {}
    codes: Counter[str] = Counter()
    for r in rows:
        by_fn.setdefault(r.function, []).append(r)
        codes.update(r.failures or [])
    functions = []
    for name in FUNCTIONS:
        fr = by_fn.get(name, [])
        lat = [r.latency_ms for r in fr if not r.cache_hit]
        functions.append(
            FunctionStats(
                function=name,
                calls=len(fr),
                fallbacks=sum(r.outcome == AIOutcome.fallback for r in fr),
                repaired=sum(r.outcome == AIOutcome.repaired for r in fr),
                retried=sum(r.outcome == AIOutcome.retried for r in fr),
                general=sum(r.source == "ai_general" for r in fr),
                median_latency_ms=round(median(lat)) if lat else None,
            )
        )
    content = ai.content
    # Only the version in use (the latest) for each function x role x language.
    latest: dict[tuple[str, str, str], PromptTemplate] = {}
    for f in content.files.values():
        m = f.model
        if isinstance(m, PromptTemplate):
            key = (m.function, m.role, m.language)
            if key not in latest or m.version > latest[key].version:
                latest[key] = m
    prompts = [
        PromptInfo(
            function=m.function,
            role=m.role,
            language=m.language,
            version=m.version,
            approval=m.approval.status.value,
        )
        for _, m in sorted(latest.items())
    ]
    review = dict(
        db.execute(select(AICacheItem.review, func.count()).group_by(AICacheItem.review)).all()
    )
    runs = db.scalars(select(AIEvalRun).order_by(AIEvalRun.created_at.desc()).limit(6)).all()
    return AiStatus(
        provider=ai.provider.name,
        model=ai.provider.model,
        breaker=ai.provider.breaker.state,
        days=WINDOW_DAYS,
        calls=len(rows),
        fallbacks=sum(r.outcome == AIOutcome.fallback for r in rows),
        functions=functions,
        failure_codes=dict(codes.most_common(12)),
        prompts=prompts,
        fallback_files=sum(isinstance(f.model, FallbackDoc) for f in content.files.values()),
        cache_items=sum(review.values()),
        cache_by_review={str(k.value if hasattr(k, "value") else k): v for k, v in review.items()},
        eval_runs=[
            EvalRunInfo(
                kind=r.kind,
                created_at=r.created_at,
                provider=r.provider,
                model=r.model,
                passed=r.passed,
                headline={k: v for k, v in r.summary.items() if k != "cases"},
            )
            for r in runs
        ],
    )
