"""Checks against the real manual (Plan §5.3; Appendix A). Skipped when the PDF or the
diagram transcriptions are not on this machine (always the case in CI: the manual is never
committed, D7). Nothing here prints or stores manual text: the fixture hides its contents from
pytest's failure output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.content.loader import load_content
from app.content.models import HandoutIndex
from app.kb import fingerprint as fp
from app.kb import ingest as kbi
from app.kb import text as kbtext
from app.settings import get_settings

# Printed handout numbers that disagree with the manual's own index (Appendix A).
KNOWN_MISPRINTS = {106: "ie.h8", 111: "ie.h11", 112: "ie.h11", 113: "ie.h11"}
MAX_PAGES_WITHOUT_HEADER = 15  # some first pages print no handout header at all


@dataclass(frozen=True)
class Manual:
    pages: list[str] = field(repr=False)
    transcriptions: dict[int, kbi.Transcription] = field(repr=False)
    index: HandoutIndex = field(repr=False)

    def __repr__(self) -> str:
        return "<manual text hidden>"


def _manual_pdf() -> Path | None:
    found = sorted(get_settings().knowledge_source_dir.glob("*DBT*手册*.pdf"))
    return found[0] if found else None


@pytest.fixture(scope="module")
def real() -> Manual:
    pytest.importorskip("pymupdf")
    pdf = _manual_pdf()
    if pdf is None:
        pytest.skip("manual PDF not present (expected in CI)")
    index = load_content(get_settings().content_dir).handouts
    assert index is not None
    tdir = get_settings().knowledge_work_dir / "transcriptions"
    try:
        transcriptions = kbi.load_transcriptions(tdir, index)
    except kbi.IngestError:
        pytest.skip("diagram transcriptions not present")
    return Manual(kbi.read_pdf(pdf), transcriptions, index)


def test_segmentation_matches_the_committed_index(real: Manual) -> None:
    seg = kbi.segment(real.pages, real.index, real.transcriptions)
    assert len(seg.handouts) == len(real.index.handouts) == 86
    assert seg.warnings["titles_not_in_index"] == []
    assert seg.warnings["sparse_pages"] == []
    assert len(seg.warnings["pages_without_header"]) <= MAX_PAGES_WITHOUT_HEADER
    found = {m["page"]: m["found"] for m in seg.warnings["header_mismatches"]}
    assert found == KNOWN_MISPRINTS
    assert all(h.title_zh for h in seg.handouts)


def test_real_chunks_are_clean_and_sized(real: Manual) -> None:
    chunks = kbi.prepare_chunks(kbi.segment(real.pages, real.index, real.transcriptions))
    assert {c.handout.id for c in chunks} == {h.id for h in real.index.handouts}
    oversized = [
        c.handout.id for c in chunks if len(c.text) > kbtext.CHUNK_MAX + kbtext.OVERLAP_MAX
    ]
    footers = [c.handout.id for c in chunks if kbtext.BOILERPLATE.search(c.text)]
    assert oversized == [] and footers == []
    diagram = {c.handout.id for c in chunks if c.quality.value == "manual_transcription"}
    assert diagram == {h.id for h in real.index.handouts if h.diagram_pages}


def test_committed_fingerprint_is_current(real: Manual) -> None:
    frequent = kbtext.frequent_lines(real.pages)
    texts = ["\n".join(kbtext.clean_page(p, frequent)) for p in real.pages]
    texts += ["\n".join(t.lines) for t in real.transcriptions.values()]
    current = fp.build(texts) == set(fp.load())
    assert current, "run `python -m app.cli kb fingerprint`"
