"""Forbidden-phrase scan for safety, help and consent copy (Plan §7.2; Phase 2 acceptance).

FamilyBridge must never promise real-time monitoring, rescue or contact (§9.1F). The patterns
live in `content/safety/forbidden_phrases.yaml`; this module applies them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.content.models import ForbiddenPhrases


def normalise(text: str) -> str:
    """NFKC (full-width -> half-width), case-fold, straight apostrophes, single spaces."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub("[\u200b-\u200d\ufeff]", "", t)  # zero-width characters
    return re.sub(r"\s+", " ", t).strip()


def forbidden_hits(rules: ForbiddenPhrases, language: str, texts: Iterable[str]) -> list[str]:
    """Return 'pattern -> matched text' for every forbidden phrase found."""
    lang = rules.languages[language]
    hits: list[str] = []
    for text in texts:
        norm = normalise(text)
        for pattern in lang.forbidden:
            m = re.search(pattern, norm, flags=re.IGNORECASE)
            if m:
                hits.append(f"{m.group(0)!r} (pattern {pattern!r})")
    return hits


def missing_required(rules: ForbiddenPhrases, language: str, texts: Iterable[str]) -> list[str]:
    joined = " ".join(normalise(t) for t in texts)
    return [p for p in rules.languages[language].required_in_help if normalise(p) not in joined]
