"""Hybrid retrieval over the active knowledge-base version (Plan §5.3 step 7; Phase 3 task 5).

Semantic search (e5 cosine, pgvector HNSW) and keyword search (jieba tokens, tsvector) are
fused with Reciprocal Rank Fusion (k=60). Optional skill/module filters apply to both. Every
search is logged with a SHA-256 of the query, never the text. `sufficient` tells callers
whether the best match is close enough to ground an answer (RAG_MIN_SCORE_ZH/_EN, calibrated
with `kb eval`, D46); when it is False, AI features must say they cannot find it in the materials.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, cast, func, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from app.kb import text as kbtext
from app.kb.embedder import Embedder, get_embedder
from app.kb.ingest import active_document, tokenizer_vocabulary
from app.models.knowledge import KnowledgeChunk, RetrievalLog
from app.settings import Settings

RRF_K = 60
CANDIDATES = 30  # per channel, before fusion
MAX_PER_HANDOUT = 1  # top k = k different handouts; callers can load a whole handout


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    handout_id: str
    handout_title_zh: str
    module: str
    skill_ids: list[str]
    pdf_pages: list[int]
    source_quality: str
    is_worksheet: bool
    text: str
    score: float  # fused RRF score
    similarity: float  # cosine similarity of query and chunk
    semantic_rank: int | None
    keyword_rank: int | None


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    document_version: int | None
    top_similarity: float | None
    sufficient: bool
    latency_ms: int


class KnowledgeService:
    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self.settings = settings
        self._embedder = embedder
        self._vocab_ready = False

    def min_score(self, language: str) -> float:
        s = self.settings
        return s.rag_min_score_en if language == "en" else s.rag_min_score_zh

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder(self.settings)
        return self._embedder

    def prepare_tokenizer(self, taxonomy: object | None) -> None:
        from app.content.models import SkillTaxonomy

        tax = taxonomy if isinstance(taxonomy, SkillTaxonomy) else None
        kbtext.init_tokenizer(tokenizer_vocabulary(tax))
        self._vocab_ready = True

    def search(
        self,
        db: Session,
        query: str,
        *,
        language: str,
        caller: str,
        skill_ids: Sequence[str] = (),
        module: str | None = None,
        k: int | None = None,
        actor_id: uuid.UUID | None = None,
        log: bool = True,
    ) -> SearchResult:
        started = time.perf_counter()
        k = k or self.settings.rag_top_k
        query = query.strip()
        doc = active_document(db)
        hits: list[Hit] = []
        if doc is not None and query:
            hits = self._search(db, doc.id, query, language, list(skill_ids), module, k)
        top = max((h.similarity for h in hits), default=None)
        sufficient = top is not None and top >= self.min_score(language)
        latency = round((time.perf_counter() - started) * 1000)
        if log:
            db.add(
                RetrievalLog(
                    caller=caller,
                    actor_id=actor_id,
                    query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
                    query_chars=len(query),
                    language=language,
                    filters={"skill_ids": list(skill_ids), "module": module},
                    k=k,
                    document_version=doc.version if doc else None,
                    result_chunk_ids=[h.chunk_id for h in hits],
                    result_scores=[round(h.similarity, 4) for h in hits],
                    top_score=top,
                    sufficient=sufficient,
                    latency_ms=latency,
                )
            )
            db.flush()
        return SearchResult(hits, doc.version if doc else None, top, sufficient, latency)

    def _filtered(
        self,
        stmt: Select[Any],
        doc_id: uuid.UUID,
        skills: list[str],
        module: str | None,
    ) -> Select[Any]:
        stmt = stmt.where(KnowledgeChunk.document_id == doc_id)
        if skills:
            stmt = stmt.where(KnowledgeChunk.skill_ids.overlap(skills))
        if module:
            stmt = stmt.where(KnowledgeChunk.module == module)
        return stmt

    def _search(
        self,
        db: Session,
        doc_id: uuid.UUID,
        query: str,
        language: str,
        skills: list[str],
        module: str | None,
        k: int,
    ) -> list[Hit]:
        qvec = self.embedder.embed_query(query)
        distance = KnowledgeChunk.embedding.cosine_distance(qvec)
        # Exact order even with filters (pgvector >= 0.8 iterative index scans).
        db.execute(text("SET LOCAL hnsw.ef_search = 100"))
        db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        sem = db.execute(
            self._filtered(select(KnowledgeChunk.id, distance), doc_id, skills, module)
            .order_by(distance)
            .limit(CANDIDATES)
        ).all()

        if not self._vocab_ready:
            kbtext.init_tokenizer()
        toks = kbtext.query_tokens(query, language)
        kw: list[tuple[uuid.UUID, float]] = []
        if toks:
            tsq = func.to_tsquery(cast("simple", REGCONFIG), kbtext.tsquery_text(toks))
            rank = func.ts_rank_cd(KnowledgeChunk.tokens, tsq)
            kw = [
                (r[0], r[1])
                for r in db.execute(
                    self._filtered(select(KnowledgeChunk.id, rank), doc_id, skills, module)
                    .where(KnowledgeChunk.tokens.op("@@")(tsq))
                    .order_by(rank.desc())
                    .limit(CANDIDATES)
                ).all()
            ]

        fused: dict[uuid.UUID, float] = defaultdict(float)
        sem_rank: dict[uuid.UUID, int] = {}
        kw_rank: dict[uuid.UUID, int] = {}
        for i, (cid, _) in enumerate(sem, 1):
            fused[cid] += 1.0 / (RRF_K + i)
            sem_rank[cid] = i
        for i, (cid, _) in enumerate(kw, 1):
            fused[cid] += 1.0 / (RRF_K + i)
            kw_rank[cid] = i
        if not fused:
            return []
        order = sorted(fused, key=lambda c: fused[c], reverse=True)
        rows = {
            r[0].id: (r[0], float(r[1]))
            for r in db.execute(
                select(KnowledgeChunk, distance).where(KnowledgeChunk.id.in_(order))
            ).all()
        }
        out: list[Hit] = []
        per_handout: dict[str, int] = defaultdict(int)
        seen_text: set[str] = set()
        for cid in order:
            if cid not in rows:
                continue
            c, dist = rows[cid]
            if per_handout[c.handout_id] >= MAX_PER_HANDOUT or c.text in seen_text:
                continue
            per_handout[c.handout_id] += 1
            seen_text.add(c.text)
            out.append(
                Hit(
                    chunk_id=c.id,
                    handout_id=c.handout_id,
                    handout_title_zh=c.handout_title_zh,
                    module=c.module,
                    skill_ids=list(c.skill_ids),
                    pdf_pages=list(c.pdf_pages),
                    source_quality=c.source_quality.value,
                    is_worksheet=c.is_worksheet,
                    text=c.text,
                    score=fused[cid],
                    similarity=1.0 - dist,
                    semantic_rank=sem_rank.get(cid),
                    keyword_rank=kw_rank.get(cid),
                )
            )
            if len(out) == k:
                break
        return out
