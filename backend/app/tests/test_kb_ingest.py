"""Ingestion and retrieval on a synthetic manual (Plan §5.3; Phase 3 tasks 2-6, 8).

Uses the offline hash embedder, so no model download. Checks: boilerplate never reaches the
index, diagram pages come from transcriptions and are flagged, segmentation follows the
committed index (headers are only cross-checked), versions supersede cleanly, filters work,
retrieval logs hold a query hash but never the query, and `sufficient` follows the threshold.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content.loader import load_content
from app.kb import ingest as kbi
from app.kb.embedder import HashEmbedder
from app.kb.retrieval import KnowledgeService
from app.models import AuditLog
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeStatus,
    RetrievalLog,
    SourceQuality,
)
from app.settings import Settings
from app.tests.kb_fixtures import handout_index, write_pdf, write_transcriptions

pytestmark = pytest.mark.db


@pytest.fixture
def manual(tmp_path: Path) -> tuple[list[str], Path]:
    pdf = write_pdf(tmp_path / "synthetic.pdf")
    return kbi.read_pdf(pdf), write_transcriptions(tmp_path / "transcriptions")


def _ingest(db: Session, settings: Settings, manual: tuple[list[str], Path]) -> KnowledgeDocument:
    pages, tdir = manual
    index = handout_index()
    doc = kbi.ingest(
        db,
        raw_pages=pages,
        source_name="synthetic.pdf",
        source_sha256="0" * 64,
        index=index,
        taxonomy=load_content(settings.content_dir).taxonomy,
        transcriptions=kbi.load_transcriptions(tdir, index),
        embedder=HashEmbedder(),
    )
    db.commit()
    return doc


def _chunks(db: Session) -> list[KnowledgeChunk]:
    return list(
        db.execute(
            select(KnowledgeChunk).order_by(KnowledgeChunk.pdf_page, KnowledgeChunk.chunk_index)
        ).scalars()
    )


def test_ingest_builds_an_active_version_with_metadata(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    doc = _ingest(db, settings, manual)
    assert doc.version == 1 and doc.status == KnowledgeStatus.active
    chunks = _chunks(db)
    assert doc.chunk_count == len(chunks) >= 5
    assert {c.handout_id for c in chunks} == {"ori.h1", "mf.h1", "mf.h2", "ie.h1"}
    mf1 = [c for c in chunks if c.handout_id == "mf.h1"]
    assert len(mf1) >= 2  # long handout -> several chunks
    assert [c.chunk_index for c in mf1] == list(range(len(mf1)))
    assert all(c.module == "mindfulness" and c.skill_ids == ["mf.what_skills"] for c in mf1)
    assert {p for c in mf1 for p in c.pdf_pages} == {4, 5}  # chunks may span the page break
    # Titles come from the PDF's own table of contents.
    assert {c.handout_id: c.handout_title_zh for c in chunks}["ie.h1"] == "提出请求的方法"
    assert all(len(c.embedding) == 1024 for c in chunks)


def test_boilerplate_and_furniture_never_reach_the_index(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    _ingest(db, settings, manual)
    text = "\n".join(c.text for c in _chunks(db))
    for banned in ("影印", "版权", "Copyright", "完成日", "续下页", "\n走\n"):
        assert banned not in text


def test_diagram_page_is_read_from_the_transcription_and_flagged(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    doc = _ingest(db, settings, manual)
    mf2 = [c for c in _chunks(db) if c.handout_id == "mf.h2"]
    assert len(mf2) == 1
    assert mf2[0].source_quality == SourceQuality.manual_transcription
    assert "重叠的区域" in mf2[0].text
    others = [c for c in _chunks(db) if c.handout_id != "mf.h2"]
    assert all(c.source_quality == SourceQuality.pdf_text for c in others)
    assert doc.stats["transcribed_pages"] == [6]
    assert doc.stats["chunks_by_source_quality"]["manual_transcription"] == 1


def test_header_misprints_are_reported_but_the_index_wins(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    doc = _ingest(db, settings, manual)
    assert doc.stats["header_mismatches"] == [{"page": 7, "found": "ie.h3", "expected": "ie.h1"}]
    assert {c.handout_id for c in _chunks(db) if 7 in c.pdf_pages} == {"ie.h1"}


def test_missing_or_mislabelled_transcription_fails(tmp_path: Path) -> None:
    index = handout_index()
    with pytest.raises(kbi.IngestError, match=r"missing transcription p006.md"):
        kbi.load_transcriptions(tmp_path, index)
    (tmp_path / "p006.md").write_text("---\npage: 6\nhandout: mf.h1\n---\n文字\n", encoding="utf-8")
    with pytest.raises(kbi.IngestError, match="front matter"):
        kbi.load_transcriptions(tmp_path, index)


def test_wrong_page_count_is_rejected(manual: tuple[list[str], Path]) -> None:
    pages, tdir = manual
    index = handout_index()
    with pytest.raises(kbi.IngestError, match="wrong file or edition"):
        kbi.segment(pages[:-1], index, kbi.load_transcriptions(tdir, index))


def test_reingest_supersedes_and_drops_old_chunks(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    first = _ingest(db, settings, manual)
    second = _ingest(db, settings, manual)
    db.refresh(first)
    assert (first.status, second.status) == (KnowledgeStatus.superseded, KnowledgeStatus.active)
    assert second.version == 2
    doc_ids = set(db.execute(select(KnowledgeChunk.document_id)).scalars())
    assert doc_ids == {second.id}  # retrieval can only ever see one version
    actions = list(
        db.execute(
            select(AuditLog.action)
            .where(AuditLog.target_id == str(second.id))
            .order_by(AuditLog.id)
        ).scalars()
    )
    assert actions == ["kb.document_ingested", "kb.document_activated"]


# --- retrieval --------------------------------------------------------------------------------


def _service(settings: Settings, **overrides: float) -> KnowledgeService:
    return KnowledgeService(settings.model_copy(update=overrides), embedder=HashEmbedder())


def test_search_finds_the_right_handout(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    _ingest(db, settings, manual)
    svc = _service(settings)
    res = svc.search(db, "注意呼吸时身体的感觉", language="zh-CN", caller="test")
    assert res.hits[0].handout_id == "mf.h1"
    assert res.document_version == 1
    assert len({h.handout_id for h in res.hits}) == len(res.hits)  # one hit per handout
    en = svc.search(db, "asking for things with DEAR MAN", language="en", caller="test")
    assert en.hits[0].handout_id == "ie.h1"
    assert en.hits[0].keyword_rank == 1


def test_search_filters_by_skill_and_module(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    _ingest(db, settings, manual)
    svc = _service(settings)
    by_skill = svc.search(
        db, "注意呼吸", language="zh-CN", caller="test", skill_ids=["mf.states_of_mind"]
    )
    assert {h.handout_id for h in by_skill.hits} == {"mf.h2"}
    by_module = svc.search(
        db, "注意呼吸", language="zh-CN", caller="test", module="interpersonal_effectiveness"
    )
    assert {h.handout_id for h in by_module.hits} == {"ie.h1"}


def test_retrieval_log_keeps_a_hash_never_the_query(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    _ingest(db, settings, manual)
    query = "注意呼吸时身体的感觉"
    _service(settings).search(
        db, query, language="zh-CN", caller="test", skill_ids=["mf.what_skills"]
    )
    db.commit()
    log = db.execute(select(RetrievalLog)).scalar_one()
    assert log.query_sha256 == hashlib.sha256(query.encode()).hexdigest()
    assert log.query_chars == len(query)
    assert log.caller == "test" and log.document_version == 1 and log.k == 5
    assert log.filters == {"skill_ids": ["mf.what_skills"], "module": None}
    row = {c.name: getattr(log, c.key) for c in RetrievalLog.__table__.columns}
    assert all(query not in str(v) for v in row.values())


def test_sufficient_follows_the_language_threshold(
    db: Session, settings: Settings, manual: tuple[list[str], Path]
) -> None:
    _ingest(db, settings, manual)
    q = "注意呼吸时身体的感觉"
    assert (
        _service(settings, rag_min_score_zh=0.0)
        .search(db, q, language="zh-CN", caller="t")
        .sufficient
    )
    strict = _service(settings, rag_min_score_zh=0.999, rag_min_score_en=0.0)
    assert not strict.search(db, q, language="zh-CN", caller="t").sufficient
    assert strict.search(db, q, language="en", caller="t").sufficient


def test_empty_knowledge_base_returns_nothing_and_is_logged(
    db: Session, settings: Settings
) -> None:
    res = _service(settings).search(db, "任何问题", language="zh-CN", caller="test")
    assert res.hits == [] and not res.sufficient and res.document_version is None
    db.commit()
    assert db.execute(select(func.count()).select_from(RetrievalLog)).scalar() == 1
