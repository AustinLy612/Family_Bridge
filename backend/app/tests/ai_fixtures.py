"""Helpers for AI-layer tests: a mock provider, a fake retriever with fictional chunks."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.ai.provider import CircuitBreaker, GuardedProvider, MockProvider
from app.ai.rules import SourceChunk
from app.ai.service import AIService, Retrieved
from app.content.loader import ContentBundle
from app.settings import Settings

# Fictional "manual" passages (not manual text). Long enough for the overlap rule.
CHUNK_ZH = (
    "停下来的时候先把双手放在膝盖上，慢慢数到五，再看看周围有哪三样蓝色的东西，"
    "然后才决定下一步要说什么话。"
)
CHUNK_EN = (
    "When the wave rises, plant both feet on the floor, count five slow breaths, name three "
    "blue things you can see, and only then decide what you want to say next."
)
CHUNK_IDS = (str(uuid.UUID(int=1)), str(uuid.UUID(int=2)))


def chunks() -> list[SourceChunk]:
    return [
        SourceChunk("S1", CHUNK_IDS[0], CHUNK_ZH, "dt.h6", "测试讲义", "distress_tolerance"),
        SourceChunk("S2", CHUNK_IDS[1], CHUNK_EN, "dt.h6", "Test handout", "distress_tolerance"),
    ]


class FakeRetriever:
    def __init__(self, sufficient: bool = True, empty: bool = False) -> None:
        self.sufficient = sufficient
        self.empty = empty
        self.calls: list[tuple[str, str, list[str]]] = []

    def __call__(
        self,
        db: Session,
        function: str,
        query: str,
        language: str,
        skill_ids: list[str],
        actor_id: uuid.UUID | None,
    ) -> Retrieved:
        self.calls.append((function, query, skill_ids))
        return Retrieved([] if self.empty else chunks(), self.sufficient, 1)


def make_ai(
    content: ContentBundle,
    settings: Settings,
    *,
    mock: MockProvider | None = None,
    retriever: FakeRetriever | None = None,
    breaker: CircuitBreaker | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[AIService, MockProvider]:
    mock = mock or MockProvider()
    provider = GuardedProvider(mock, breaker or CircuitBreaker(50, 60))
    ai = AIService(
        content,
        settings,
        provider,
        retriever=retriever if retriever is not None else FakeRetriever(),
        session_factory=session_factory,
    )
    return ai, mock
