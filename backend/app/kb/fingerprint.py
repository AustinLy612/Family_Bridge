"""Manual-overlap check (Plan §5.3 step 9; proposal: users see only original paraphrases, D7).

`kb fingerprint` hashes every 12-character window of the manual (after normalisation) that
contains at least 10 CJK characters, and writes the sorted hashes to a committed file. The
manual text itself is never committed. `scripts/scan_repo.py` and the test suite then flag any
repository text that shares a run of COPY_RUN or more consecutive characters with the manual.

Standard library only: the repo-hygiene CI job runs this without the backend's dependencies.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

WINDOW = 12
MIN_CJK = 10
COPY_RUN = 20  # characters; a shared run this long is copying, not shared terminology
HASH_BYTES = 6
FINGERPRINT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "manual_fingerprint.txt"
HEADER = "# manual-fingerprint v1 window=12 min_cjk=10 hash=blake2b-48\n"


def _is_cjk(ch: str) -> bool:
    return "㐀" <= ch <= "鿿" or "豈" <= ch <= "﫿"


def canonical(text: str) -> str:
    """Letters/digits/CJK only, NFKC + casefolded, so punctuation changes don't hide a copy."""
    t = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in t if ch.isalnum())


def _h(window: str) -> str:
    return hashlib.blake2b(window.encode("utf-8"), digest_size=HASH_BYTES).hexdigest()


def windows(canon: str) -> Iterable[tuple[int, str]]:
    for i in range(len(canon) - WINDOW + 1):
        w = canon[i : i + WINDOW]
        if sum(map(_is_cjk, w)) >= MIN_CJK:
            yield i, _h(w)


def build(texts: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out.update(h for _, h in windows(canonical(t)))
    return out


def write(hashes: set[str], path: Path = FINGERPRINT_PATH) -> None:
    path.write_text(HEADER + "\n".join(sorted(hashes)) + "\n", encoding="utf-8", newline="\n")


def load(path: Path = FINGERPRINT_PATH) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    return frozenset(
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln and ln[0] != "#"
    )


@dataclass(frozen=True)
class Overlap:
    start: int  # offset in the canonical text
    length: int  # canonical characters shared with the manual
    excerpt: str  # the first characters of the run (from the checked text, not the manual)


def overlaps(text: str, fingerprint: frozenset[str], min_run: int = COPY_RUN) -> list[Overlap]:
    """Runs of >= min_run canonical characters covered by windows that occur in the manual."""
    canon = canonical(text)
    covered = [False] * len(canon)
    for i, h in windows(canon):
        if h in fingerprint:
            for j in range(i, i + WINDOW):
                covered[j] = True
    out: list[Overlap] = []
    i = 0
    while i < len(canon):
        if not covered[i]:
            i += 1
            continue
        j = i
        while j < len(canon) and covered[j]:
            j += 1
        if j - i >= min_run:
            out.append(Overlap(i, j - i, canon[i : min(j, i + 16)]))
        i = j
    return out


# Text files that could carry manual wording to users or into the repository.
SCAN_SUFFIXES = frozenset({".md", ".yaml", ".yml", ".json", ".ts", ".tsx", ".py", ".txt", ".html"})


def repo_files(root: Path) -> list[str]:
    """Everything git would commit: tracked plus untracked-but-not-ignored files."""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [f for f in out.split("\0") if f]


def scan_repo(root: Path, fingerprint: frozenset[str] | None = None) -> list[tuple[str, Overlap]]:
    fpr = load() if fingerprint is None else fingerprint
    if not fpr:
        return []
    found: list[tuple[str, Overlap]] = []
    for rel in repo_files(root):
        path = root / rel
        if path.suffix.lower() not in SCAN_SUFFIXES or path == FINGERPRINT_PATH:
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found += [(rel, o) for o in overlaps(text, fpr)]
    return found
