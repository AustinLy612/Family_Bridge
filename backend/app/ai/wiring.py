"""Connects the AI layer to the knowledge base and the safety service (Phase 4 tasks 6-7).

- `kb_retriever`: skill-scoped retrieval through `KnowledgeService.search` (Phase 3).
- `LLMRiskAssessor`: the `assess_risk` LLM channel for `SafetyService` (Plan §5.7). It runs only
  when the keyword channel fires. A valid answer decides (D49); when the provider is down or the
  answer is invalid it returns None and the keyword result applies (keyword-only degradation).
- `build_ai_service`: what `create_app` and the CLI use.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.ai.provider import GuardedProvider, build_provider
from app.ai.rules import SourceChunk
from app.ai.service import AIService, Retrieved, Retriever
from app.content.loader import ContentBundle
from app.kb import fingerprint as fp
from app.kb.retrieval import KnowledgeService
from app.safety.screening import Assessment, RiskLevel, Tier
from app.settings import Settings


def kb_retriever(knowledge: KnowledgeService) -> Retriever:
    def retrieve(
        db: Session,
        function: str,
        query: str,
        language: str,
        skill_ids: list[str],
        actor_id: uuid.UUID | None,
    ) -> Retrieved:
        res = knowledge.search(
            db,
            query,
            language=language,
            caller=f"ai:{function}"[:40],
            skill_ids=skill_ids,
            actor_id=actor_id,
        )
        chunks = [
            SourceChunk(
                label=f"S{i}",
                chunk_id=str(h.chunk_id),
                text=h.text,
                handout_id=h.handout_id,
                title=h.handout_title_zh,
                module=h.module,
            )
            for i, h in enumerate(res.hits, 1)
        ]
        # Skill-scoped: every hit belongs to the skill, so any hit grounds it (D51).
        sufficient = bool(chunks) if skill_ids else res.sufficient
        return Retrieved(chunks, sufficient, res.document_version)

    return retrieve


class LLMRiskAssessor:
    def __init__(self, ai: AIService) -> None:
        self.ai = ai

    def assess(
        self,
        text: str,
        recent: Sequence[str],
        language: str,
        hits: Mapping[Tier, Sequence[str]] | None = None,
    ) -> Assessment | None:
        hits = hits or {}
        tier = next((t.value for t in Tier if hits.get(t)), None)
        terms = [t for tier_ in Tier for t in hits.get(tier_, ())][:20]
        try:
            res = self.ai.run(
                None,
                "assess_risk",
                {
                    "message": text[:2000],
                    "recent": [r[:2000] for r in recent[-3:] if r.strip()],
                    "keyword_terms": [t[:60] for t in terms],
                },
                role="any",
                language=language if language in ("zh-CN", "en") else "zh-CN",
                caller="safety",
                hints={"keyword_tier": tier},
            )
        except Exception:
            return None
        out = res.output
        if out is None:
            return None
        return Assessment(
            level=RiskLevel(out["risk_level"]),
            should_stop=bool(out["should_stop"]),
            risk_type=", ".join(out.get("categories") or [])[:200],
            reasoning=str(out.get("reasoning") or "")[:400],
        )


def build_ai_service(
    content: ContentBundle,
    settings: Settings,
    *,
    provider: GuardedProvider | None = None,
    knowledge: KnowledgeService | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> AIService:
    fingerprint = fp.load() if fp.FINGERPRINT_PATH.is_file() else None
    if knowledge is None:
        knowledge = KnowledgeService(settings)
        knowledge.prepare_tokenizer(content.taxonomy)
    return AIService(
        content,
        settings,
        provider or build_provider(settings),
        retriever=kb_retriever(knowledge),
        fingerprint=fingerprint,
        session_factory=session_factory,
    )
