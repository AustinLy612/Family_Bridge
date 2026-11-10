"""Manual ingestion (Plan §5.3 steps 1-7; Phase 3 tasks 2-4).

PDF pages -> boilerplate removal -> diagram pages replaced by manual transcriptions (D43) ->
segmentation by the committed handout index (D44), cross-checked against the page headers we
can read -> chunks of ~300-600 characters that never cross handouts -> e5 embeddings + jieba
tokens -> a new KnowledgeDocument version, activated in the same transaction.

PyMuPDF (AGPL) is only imported here, inside `read_pdf`, and is not installed in the API
image (D45). Manual text goes to the database only (D7).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter
from sqlalchemy import cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from app.content.models import Handout, HandoutIndex, SkillTaxonomy
from app.core import audit
from app.core.sessions import utcnow
from app.kb import text as kbtext
from app.kb.embedder import Embedder
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeStatus, SourceQuality

SPARSE_PAGE_CHARS = 20  # a non-diagram page with less text than this probably needs transcribing
EMBED_BATCH = 32


class IngestError(Exception):
    pass


def read_pdf(path: Path) -> list[str]:
    """Raw text of every page (index 0 = page 1)."""
    import pymupdf

    with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
        return [page.get_text() for page in doc]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Transcription:
    page: int
    handout: str
    lines: list[str]


def load_transcriptions(directory: Path, index: HandoutIndex) -> dict[int, Transcription]:
    """Read `pNNN.md` for every diagram page; each must name its page and handout."""
    out: dict[int, Transcription] = {}
    problems: list[str] = []
    for h in index.handouts:
        for p in h.diagram_pages:
            path = directory / f"p{p:03d}.md"
            if not path.is_file():
                problems.append(f"missing transcription {path.name} (page {p}, {h.id})")
                continue
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            meta = post.metadata
            if meta.get("page") != p or meta.get("handout") != h.id:
                problems.append(f"{path.name}: front matter must say page: {p}, handout: {h.id}")
            elif meta.get("source_quality") != SourceQuality.manual_transcription.value:
                problems.append(f"{path.name}: source_quality must be manual_transcription")
            lines = [ln.strip() for ln in post.content.splitlines() if ln.strip()]
            if not lines:
                problems.append(f"{path.name}: empty transcription")
            out[p] = Transcription(p, h.id, lines)
    if problems:
        raise IngestError("; ".join(problems))
    return out


@dataclass
class HandoutText:
    handout: Handout
    title_zh: str
    paragraphs: list[tuple[str, int]]
    diagram_pages: set[int]


@dataclass
class Segmentation:
    handouts: list[HandoutText]
    warnings: dict[str, list[Any]] = field(default_factory=dict)


def segment(
    raw_pages: Sequence[str], index: HandoutIndex, transcriptions: dict[int, Transcription]
) -> Segmentation:
    if len(raw_pages) != index.source.pdf_pages:
        raise IngestError(
            f"the PDF has {len(raw_pages)} pages but handouts.yaml expects "
            f"{index.source.pdf_pages}: wrong file or edition"
        )
    frequent = kbtext.frequent_lines(raw_pages)
    mismatches: list[dict[str, Any]] = []
    no_header: list[int] = []
    sparse: list[int] = []
    out: list[HandoutText] = []
    titles = kbtext.index_titles(
        ln for p in index.source.index_pages for ln in kbtext.clean_page(raw_pages[p - 1])
    )
    for h in index.handouts:
        paragraphs: list[tuple[str, int]] = []
        title = ""
        for n, p in enumerate(h.pages):
            if p in h.diagram_pages:
                lines = transcriptions[p].lines
            else:
                lines = kbtext.clean_page(raw_pages[p - 1], frequent)
                if sum(map(len, lines)) < SPARSE_PAGE_CHARS:
                    sparse.append(p)
            found = kbtext.find_header(lines)
            if found and found[0] != h.id:
                mismatches.append({"page": p, "found": found[0], "expected": h.id})
            if n == 0:
                if not found:
                    no_header.append(p)
                title = titles.get(h.id) or kbtext.handout_title(lines)
            paragraphs += [(ln, p) for ln in kbtext.merge_lines(lines)]
        if not paragraphs:
            raise IngestError(f"{h.id}: no text on pages {h.pages}")
        out.append(HandoutText(h, title or h.title_en, paragraphs, set(h.diagram_pages)))
    return Segmentation(
        out,
        {
            "header_mismatches": mismatches,
            "pages_without_header": no_header,
            "sparse_pages": sparse,
            "titles_not_in_index": [h.id for h in index.handouts if h.id not in titles],
        },
    )


@dataclass(frozen=True)
class PreparedChunk:
    handout: Handout
    title_zh: str
    chunk_index: int
    text: str
    pages: tuple[int, ...]
    quality: SourceQuality

    def embedding_text(self, module: tuple[str, str]) -> str:
        # Context prefix so a chunk from the middle of a handout still says what it is about.
        # The English module name and handout title (developer-written, D44) give English
        # queries a cross-lingual anchor.
        zh, en = module
        return f"{zh} {self.title_zh} / {en}: {self.handout.title_en}\n{self.text}"


def prepare_chunks(seg: Segmentation) -> list[PreparedChunk]:
    out: list[PreparedChunk] = []
    for ht in seg.handouts:
        for i, c in enumerate(kbtext.chunk_handout(ht.paragraphs)):
            quality = (
                SourceQuality.manual_transcription
                if set(c.pages) & ht.diagram_pages
                else SourceQuality.pdf_text
            )
            out.append(PreparedChunk(ht.handout, ht.title_zh, i, c.text, c.pages, quality))
    return out


def module_names(taxonomy: SkillTaxonomy | None) -> dict[str, tuple[str, str]]:
    """Module id -> (Chinese name, English name)."""
    if taxonomy is None:
        return {}
    return {m.id: (m.name.zh_CN, m.name.en) for m in taxonomy.modules if m.name is not None}


def tokenizer_vocabulary(taxonomy: SkillTaxonomy | None) -> list[str]:
    """DBT terms jieba should keep whole: module and skill names (developer-written, D44)."""
    if taxonomy is None:
        return []
    words: list[str] = []
    for m in taxonomy.modules:
        if m.name:
            words.append(m.name.zh_CN)
        for s in m.skills:
            if s.name:
                words.append(s.name.zh_CN.split("（")[0])
    return [*words, "智慧心念", "情绪心念", "理性心念", "相反行为", "检查事实", "利弊分析"]


def ingest(
    db: Session,
    *,
    raw_pages: Sequence[str],
    source_name: str,
    source_sha256: str,
    index: HandoutIndex,
    taxonomy: SkillTaxonomy | None,
    transcriptions: dict[int, Transcription],
    embedder: Embedder,
    progress: Callable[[int, int], None] | None = None,
) -> KnowledgeDocument:
    """Build and activate a new knowledge-base version inside the caller's transaction."""
    seg = segment(raw_pages, index, transcriptions)
    chunks = prepare_chunks(seg)
    names = module_names(taxonomy)
    kbtext.init_tokenizer(tokenizer_vocabulary(taxonomy))

    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        vectors += embedder.embed_passages(
            [c.embedding_text(names.get(c.handout.module, ("", ""))) for c in batch]
        )
        if progress:
            progress(len(vectors), len(chunks))

    version = (db.execute(select(func.max(KnowledgeDocument.version))).scalar() or 0) + 1
    by_module = Counter(c.handout.module for c in chunks)
    by_quality = Counter(c.quality.value for c in chunks)
    doc = KnowledgeDocument(
        version=version,
        source_name=source_name[:200],
        source_sha256=source_sha256,
        source_pages=len(raw_pages),
        handout_index_version=index.version,
        embedding_model=embedder.name,
        embedding_dim=embedder.dim,
        chunk_count=len(chunks),
        status=KnowledgeStatus.building,
        stats={
            "handouts": len(seg.handouts),
            "chunks_by_module": dict(sorted(by_module.items())),
            "chunks_by_source_quality": dict(sorted(by_quality.items())),
            "transcribed_pages": sorted(transcriptions),
            "avg_chunk_chars": round(sum(len(c.text) for c in chunks) / max(len(chunks), 1)),
            **seg.warnings,
        },
    )
    db.add(doc)
    db.flush()
    simple = cast("simple", REGCONFIG)
    for c, vec in zip(chunks, vectors, strict=True):
        module_zh = names.get(c.handout.module, ("", ""))[0]
        toks = kbtext.tokens(f"{module_zh} {c.title_zh} {c.text}")
        db.add(
            KnowledgeChunk(
                document_id=doc.id,
                module=c.handout.module,
                handout_id=c.handout.id,
                handout_title_zh=c.title_zh,
                skill_ids=list(c.handout.skill_ids),
                pdf_page=c.pages[0],
                pdf_pages=list(c.pages),
                chunk_index=c.chunk_index,
                source_quality=c.quality,
                is_worksheet=c.handout.is_worksheet,
                text=c.text,
                char_count=len(c.text),
                tokens=func.to_tsvector(simple, " ".join(toks)),
                embedding=vec,
            )
        )
    db.flush()
    audit.record(
        db,
        "kb.document_ingested",
        target_type="knowledge_document",
        target_id=doc.id,
        details={"version": version, "chunks": len(chunks), "embedding_model": embedder.name},
    )
    activate(db, doc)
    return doc


def activate(db: Session, doc: KnowledgeDocument) -> None:
    """Make `doc` the only active version; older versions keep their record but lose chunks."""
    old = list(
        db.execute(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.status == KnowledgeStatus.active, KnowledgeDocument.id != doc.id
            )
        ).scalars()
    )
    if old:
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(old)))
        db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id.in_(old))
            .values(status=KnowledgeStatus.superseded)
        )
    doc.status = KnowledgeStatus.active
    doc.activated_at = utcnow()
    db.flush()
    audit.record(
        db,
        "kb.document_activated",
        target_type="knowledge_document",
        target_id=doc.id,
        details={"version": doc.version, "superseded": len(old)},
    )


def active_document(db: Session) -> KnowledgeDocument | None:
    return db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.status == KnowledgeStatus.active)
    ).scalar_one_or_none()
