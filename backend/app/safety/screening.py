"""Risk screening of participant free text (Plan §5.7; Phase 2 tasks 2 and 4).

Two channels, as in DBT_Revised (D1):
1. Keyword channel: bilingual lists from `content/safety/risk_keywords.yaml`.
2. LLM channel (`RiskAssessor`), run only when the keyword channel or a concern indicator
   fires. It is plugged in during Phase 4. Until then, and whenever it is unavailable, the
   keyword decision stands: a high-risk term is a stop condition; anything else that fired is
   medium.

Multi-turn disclosures: the caller passes the same user's recent messages from the same
activity. Terms that only appear once the turns are joined (a phrase split across two
messages) count as new hits; terms that were already present before this message do not,
so an earlier flag is not raised again on every later turn.

This module is pure (no database). `app/safety/service.py` turns a result into actions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.content.models import RiskKeywords
from app.content.phrases import normalise

RECENT_TURNS = 3  # earlier messages of the same user joined with the current one


class RiskLevel(StrEnum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class Tier(StrEnum):
    high = "high"
    moderate = "moderate"
    concern = "concern"


@dataclass(frozen=True)
class Assessment:
    """What the LLM channel returns (Phase 4)."""

    level: RiskLevel
    should_stop: bool
    risk_type: str = ""
    reasoning: str = ""


class RiskAssessor(Protocol):
    def assess(
        self,
        text: str,
        recent: Sequence[str],
        language: str,
        hits: Mapping[Tier, Sequence[str]] | None = None,
    ) -> Assessment | None:
        """Return None when the model is unavailable or its answer is invalid."""


class NoAssessor:
    """Keyword-only mode: no LLM channel (tests, or when the AI layer is not wired)."""

    def assess(
        self,
        text: str,
        recent: Sequence[str],
        language: str,
        hits: Mapping[Tier, Sequence[str]] | None = None,
    ) -> Assessment | None:
        return None


@dataclass(frozen=True)
class ScreenResult:
    level: RiskLevel
    should_stop: bool
    channel: str | None  # "keyword" | "llm" | None
    hits: dict[Tier, tuple[str, ...]] = field(default_factory=dict)
    assessment: Assessment | None = None

    @property
    def terms(self) -> list[str]:
        return [t for tier in Tier for t in self.hits.get(tier, ())]


_CJK = re.compile("[\u3000-\u9fff\uf900-\ufaff]")  # CJK punctuation, ideographs


def _is_cjk(term: str) -> bool:
    return bool(_CJK.search(term))


def _word_pattern(term: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in term.split())
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


class KeywordMatcher:
    """Compiled keyword lists. Every language's lists apply to every user."""

    def __init__(self, keywords: RiskKeywords) -> None:
        self.version = keywords.version
        self._cjk: dict[Tier, list[str]] = {t: [] for t in Tier}
        self._words: dict[Tier, list[tuple[str, re.Pattern[str]]]] = {t: [] for t in Tier}
        benign_cjk: list[str] = []
        benign_words: list[re.Pattern[str]] = []
        for terms in keywords.languages.values():
            for tier in Tier:
                for term in getattr(terms, tier.value):
                    norm = normalise(term)
                    if _is_cjk(norm):
                        self._cjk[tier].append(re.sub(r"\s+", "", norm))
                    else:
                        self._words[tier].append((term, _word_pattern(norm)))
            for term in terms.benign:
                norm = normalise(term)
                if _is_cjk(norm):
                    benign_cjk.append(re.sub(r"\s+", "", norm))
                else:
                    benign_words.append(_word_pattern(norm))
        # Longest first, so "想死你了" is removed before anything shorter can overlap it.
        self._benign_cjk = sorted(set(benign_cjk), key=len, reverse=True)
        self._benign_words = benign_words

    def hits(self, text: str) -> dict[Tier, set[str]]:
        spaced = normalise(text)
        for pattern in self._benign_words:
            spaced = pattern.sub(" ", spaced)
        compact = re.sub(r"\s+", "", spaced)
        for phrase in self._benign_cjk:
            compact = compact.replace(phrase, "|")
        found: dict[Tier, set[str]] = {t: set() for t in Tier}
        for tier in Tier:
            found[tier].update(term for term in self._cjk[tier] if term in compact)
            found[tier].update(term for term, pat in self._words[tier] if pat.search(spaced))
        return found


def _new_hits(matcher: KeywordMatcher, text: str, recent: Sequence[str]) -> dict[Tier, set[str]]:
    current = matcher.hits(text)
    prior = [m for m in recent[-RECENT_TURNS:] if m]
    if not prior:
        return current
    before = matcher.hits(" ".join(prior))
    joined = matcher.hits(" ".join([*prior, text]))
    return {t: current[t] | (joined[t] - before[t]) for t in Tier}


def screen(
    matcher: KeywordMatcher,
    text: str,
    *,
    recent: Sequence[str] = (),
    language: str = "zh-CN",
    assessor: RiskAssessor | None = None,
) -> ScreenResult:
    found = _new_hits(matcher, text, recent)
    hits = {tier: tuple(sorted(terms)) for tier, terms in found.items() if terms}
    if not hits:
        return ScreenResult(RiskLevel.none, should_stop=False, channel=None)

    # D49: a valid LLM verdict decides, in both directions; keywords decide only without one.
    assessment = (assessor or NoAssessor()).assess(text, list(recent), language, hits)
    if assessment is not None:
        return ScreenResult(
            assessment.level,
            should_stop=assessment.should_stop or assessment.level is RiskLevel.high,
            channel="llm",
            hits=hits,
            assessment=assessment,
        )
    if Tier.high in hits:
        return ScreenResult(RiskLevel.high, should_stop=True, channel="keyword", hits=hits)
    return ScreenResult(RiskLevel.medium, should_stop=False, channel="keyword", hits=hits)
