"""Text handling for the knowledge base (Plan §5.3 steps 2, 4, 5): page cleaning, line merging,
chunking and keyword tokenisation. Pure functions; no manual text is stored in code.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# --- page cleaning -------------------------------------------------------------------------

# Copyright/permission footers printed on every page (Chinese and English variants).
BOILERPLATE = re.compile(
    r"版权|Copyright|Guilford|吉尔福德|Rathus|Linehan|影印|复印|个人用途|个人使用|经许可|已获得授权"
    r"|经授权|Skills Manual|Handouts and Worksheets|DBT® Skills|[Ff]rom DBT|Second Edition"
    r"|册仅供|^本手|Permission to photocopy|^details\)\.?$|有关版权约定"
)
# Worksheet furniture that carries no meaning.
FURNITURE = re.compile(r"^(完成日[:：]?\s*_*|[（(]?续下页[）)]?|_{3,}|[_\s]+)$")
FREQUENT_MIN_LEN = 8  # frequency filter only drops long repeated lines (never "1." etc.)
FREQUENT_MIN_PAGES = 6
SIDE_TAB_RUN = 3  # a run of >= 3 one/two-character lines is a vertical side tab
_NUMBER = re.compile(r"\d{1,2}[ab]?")


def frequent_lines(pages: Sequence[str]) -> set[str]:
    """Long lines that repeat on many pages are running footers, not content."""
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({ln.strip() for ln in page.splitlines() if ln.strip()})
    return {
        ln for ln, c in counts.items() if c >= FREQUENT_MIN_PAGES and len(ln) >= FREQUENT_MIN_LEN
    }


def clean_page(text: str, frequent: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Return the content lines of one page: no footers, side tabs or form furniture."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [
        ln
        for ln in lines
        if ln and ln not in frequent and not BOILERPLATE.search(ln) and not FURNITURE.match(ln)
    ]
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if len(run) < SIDE_TAB_RUN:
            out.extend(run)
        else:
            # A vertical side tab may spell the handout header: module name, then its number
            # (some tabs repeat the number, so take the first one only).
            name = ""
            for i, ch in enumerate(run[:-1]):
                name += ch
                if name in MODULE_ZH and _NUMBER.fullmatch(run[i + 1]):
                    out.append(name + run[i + 1])
                    break
        run.clear()

    for ln in lines:
        if len(ln) <= 2 and not ln.endswith("."):
            run.append(ln)
            continue
        flush()
        out.append(ln)
    flush()
    return out


_SENTENCE_END = "。！？!?：:；;…”」』）)"
_LIST_START = re.compile(r"^(\d{1,2}[.、)]|[•●○◆■\-*]|[（(]\d{1,2}[)）]|[A-Z][a-z]+\b)")


def _is_cjk(ch: str) -> bool:
    return "㐀" <= ch <= "鿿" or "豈" <= ch <= "﫿"


def merge_lines(lines: Iterable[str]) -> list[str]:
    """Re-join lines the PDF wrapped mid-sentence; keep real line breaks (headings, list items)."""
    merged: list[str] = []
    for ln in lines:
        if (
            merged
            and merged[-1][-1] not in _SENTENCE_END
            and len(merged[-1]) >= 20  # short lines are headings/labels, keep them separate
            and not _LIST_START.match(ln)
            and (_is_cjk(merged[-1][-1]) or merged[-1][-1] in "，、,")
        ):
            merged[-1] += ln
        else:
            merged.append(ln)
    return merged


# --- handout headers ------------------------------------------------------------------------

MODULE_ZH = {
    "导论": "ori",
    "正念": "mf",
    "痛苦忍受": "dt",
    "走在中道上": "wmp",
    "情绪调节": "er",
    "人际效能": "ie",
}
# Page headers come as "<module>讲义N", "<module>手册（可选）N", a bare "<module>N", or a vertical
# side tab of single characters (the scan is not consistent), sometimes followed by the title.
_MODULES = "|".join(MODULE_ZH)
HEADER = re.compile(
    rf"^({_MODULES})(?:(?:讲义|手册|工作表)(?:[（(]可选[)）])?(\d{{1,2}}[ab]?)|(\d{{1,2}}[ab]?)$)"
)
INDEX_ENTRY = re.compile(rf"^({_MODULES})讲义(\d{{1,2}}[ab]?)[:：](.+)$")
HEADER_SEARCH_LINES = 8  # text order puts the header after a few body lines on some pages


def find_header(lines: Sequence[str], within: int = HEADER_SEARCH_LINES) -> tuple[str, int] | None:
    """(handout id, line index) of a handout header near the top of a page."""
    for i, ln in enumerate(lines[:within]):
        m = HEADER.match(ln.replace(" ", ""))
        if m:
            return f"{MODULE_ZH[m.group(1)]}.h{m.group(2) or m.group(3)}", i
    return None


def index_titles(index_page_lines: Iterable[str]) -> dict[str, str]:
    """Chinese handout titles from the manual's own table of contents ("<module>讲义N：title")."""
    out: dict[str, str] = {}
    for ln in index_page_lines:
        m = INDEX_ENTRY.match(ln.replace(" ", ""))
        if m:
            out[f"{MODULE_ZH[m.group(1)]}.h{m.group(2)}"] = m.group(3).strip()[:200]
    return out


def handout_title(lines: Sequence[str]) -> str:
    """Fallback title from a handout's first page: the line after the header, else the first."""
    found = find_header(lines)
    if found:
        _, i = found
        rest = HEADER.sub("", lines[i].replace(" ", "")).strip(" ：:")
        title = rest or (lines[i + 1] if i + 1 < len(lines) else "")
    else:
        title = lines[0] if lines else ""
    title = re.sub(r"[（(]\d/\d页[)）]$", "", title).strip()
    return title[:200]


# --- chunking -------------------------------------------------------------------------------

CHUNK_MIN = 300
CHUNK_MAX = 600
OVERLAP_MAX = 120  # carry the previous chunk's last unit forward if it is this short
_SPLIT = re.compile(r"(?<=[。！？!?；;])")


@dataclass(frozen=True)
class Unit:
    text: str
    page: int


def _units(paragraphs: Sequence[tuple[str, int]]) -> list[Unit]:
    out: list[Unit] = []
    for text, page in paragraphs:
        if len(text) <= CHUNK_MAX:
            out.append(Unit(text, page))
            continue
        buf = ""
        for sent in filter(None, _SPLIT.split(text)):
            while len(sent) > CHUNK_MAX:  # no sentence end in sight: hard split
                out.append(Unit(sent[:CHUNK_MAX], page))
                sent = sent[CHUNK_MAX:]
            if buf and len(buf) + len(sent) > CHUNK_MAX:
                out.append(Unit(buf, page))
                buf = ""
            buf += sent
        if buf:
            out.append(Unit(buf, page))
    return out


@dataclass(frozen=True)
class Chunk:
    text: str
    pages: tuple[int, ...]


def chunk_handout(paragraphs: Sequence[tuple[str, int]]) -> list[Chunk]:
    """Pack (paragraph, page) pairs into chunks of about CHUNK_MIN-CHUNK_MAX characters.

    Chunks never cross handouts (callers pass one handout at a time). Consecutive chunks share
    the previous chunk's last unit when it is short, so a list item is not cut from its lead-in.
    """
    units = _units(paragraphs)
    groups: list[list[Unit]] = []
    cur: list[Unit] = []
    size = 0
    for u in units:
        if cur and size + len(u.text) + 1 > CHUNK_MAX and size >= CHUNK_MIN // 2:
            groups.append(cur)
            tail = cur[-1]
            cur = [tail] if len(tail.text) <= OVERLAP_MAX and len(cur) > 1 else []
            size = sum(len(x.text) + 1 for x in cur)
        cur.append(u)
        size += len(u.text) + 1
    if cur:
        # A short remainder joins the previous chunk instead of standing alone.
        if groups and size < CHUNK_MIN // 2:
            prev = groups[-1]
            groups[-1] = prev + [u for u in cur if u not in prev]
        else:
            groups.append(cur)
    return [Chunk("\n".join(u.text for u in g), tuple(sorted({u.page for u in g}))) for g in groups]


# --- keyword tokens (jieba, D45) ------------------------------------------------------------

_jieba_lock = threading.Lock()
_jieba_ready = False
_TOKEN_OK = re.compile(r"[0-9a-z㐀-鿿]")
STOP = frozenset(
    [
        "的",
        "了",
        "和",
        "是",
        "在",
        "我",
        "你",
        "他",
        "她",
        "它",
        "们",
        "这",
        "那",
        "就",
        "也",
        "都",
        "而",
        "及",
        "与",
        "或",
        "一个",
        "什么",
        "怎么",
        "如何",
    ]
)


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def init_tokenizer(extra_words: Iterable[str] = ()) -> None:
    """Load jieba once; teach it the DBT terms so they stay single tokens."""
    global _jieba_ready
    with _jieba_lock:
        import jieba

        if not _jieba_ready:
            jieba.setLogLevel(logging.WARNING)
            jieba.initialize()
            _jieba_ready = True
        for w in extra_words:
            w = normalise(w).strip()
            if len(w) >= 2:
                jieba.add_word(w, freq=20000)


def tokens(text: str) -> list[str]:
    """Search tokens: jieba search-mode segmentation over normalised text, minus stop words."""
    import jieba

    if not _jieba_ready:
        init_tokenizer()
    out: list[str] = []
    for tok in jieba.cut_for_search(normalise(text)):
        tok = re.sub(r"[^0-9a-z㐀-鿿]", "", tok)
        if tok and _TOKEN_OK.search(tok) and tok not in STOP:
            out.append(tok)
    return out


_ACRONYM = re.compile(r"\b[A-Z]{3,}\b")


def query_tokens(query: str, language: str) -> list[str]:
    """Keyword-channel tokens for a query.

    The manual is Chinese; the only English in it is skill acronyms and stray labels. So an
    English query contributes only its acronyms (DEAR MAN, TIPP, ...) to keyword search and
    relies on the cross-lingual semantic channel for everything else.
    """
    if language == "en":
        return [normalise(a) for a in _ACRONYM.findall(query)]
    return tokens(query)


def tsquery_text(query_tokens: Sequence[str]) -> str:
    """An OR tsquery over sanitised tokens (tokens only contain [0-9a-z] and CJK)."""
    uniq = list(dict.fromkeys(query_tokens))
    return " | ".join(f"'{t}'" for t in uniq)
