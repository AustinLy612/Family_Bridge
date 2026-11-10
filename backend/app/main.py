"""FastAPI application factory (Plan Phase 0 task 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ai.provider import GuardedProvider
from app.ai.wiring import LLMRiskAssessor, build_ai_service
from app.api import (
    admin,
    ai,
    auth,
    diary,
    groups,
    health,
    joint,
    kb,
    learning,
    me,
    meta,
    onboarding,
    research,
    safety,
    therapist,
)
from app.content.loader import ContentBundle, load_content
from app.core.db import get_engine
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.joint.hub import Hub
from app.safety.service import SafetyService
from app.settings import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    *,
    engine_factory: Callable[[], Engine] | None = None,
    llm_provider: GuardedProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(json_output=settings.app_env != "development")
    log = get_logger("startup")

    # Fail fast: invalid content stops the app from starting (Plan Phase 0 task 6).
    content: ContentBundle = load_content(settings.content_dir)
    log.info("content_loaded", files=len(content.files), version=content.aggregate_hash)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if engine_factory is None:
            get_engine().dispose()

    app = FastAPI(
        title="FamilyBridge API",
        version="0.0.1",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.content = content
    app.state.engine_factory = engine_factory or get_engine

    def session_factory() -> Session:
        return Session(app.state.engine_factory(), expire_on_commit=False)

    app.state.session_factory = session_factory

    # AI layer (Plan §5.4): provider behind a circuit breaker, prompts, rules, fallbacks, logs.
    app.state.ai = build_ai_service(
        content, settings, provider=llm_provider, session_factory=session_factory
    )
    # Safety screening hooks for lessons, diary and joint sessions (Plan §5.7), with the
    # assess_risk LLM channel (D49; keyword-only when the model is unavailable).
    app.state.safety = SafetyService(content, settings, LLMRiskAssessor(app.state.ai))
    # Joint rooms (Plan §5.9): live connections only; room state is persisted in Postgres.
    app.state.joint_hub = Hub(content, session_factory, settings.room_disconnect_pause_seconds)

    # Order: last added runs first. Request id wraps everything.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router)
    app.include_router(meta.router)
    for r in (
        auth.router,
        me.router,
        onboarding.router,
        admin.router,
        groups.router,
        safety.router,
        kb.router,
        ai.router,
        learning.router,
        diary.router,
        therapist.router,
        joint.router,
        research.router,
    ):
        app.include_router(r)
    return app
