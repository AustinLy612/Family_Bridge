"""Deterministic rule checks after generation (Plan §5.4 "Rule checks"; Phase 4 task 4).

1. Citation integrity: every cited label was given to the model; `grounding=manual` cites >= 1;
   `grounding=manual` is not allowed when retrieval was insufficient or empty (D6).
2. Verbatim overlap (D7): no run of >= 20 identical characters (or 12 English words) shared with
   a retrieved chunk, nor with the manual fingerprint (scripts/manual_fingerprint.txt).
3. Language: participant-facing text is in the participant's language.
4. Length bounds: enforced by the output schemas (app/ai/schemas.py) during validation.
5. Output patterns: `content/safety/output_rules.yaml` categories plus the crisis-promise
   patterns of `content/safety/forbidden_phrases.yaml`.
6. Medical caution: teaching TIPP temperature / intense exercise needs the health caution.
Plus: `select_skill` must name taxonomy ids (Plan §5.4 table).

A check returns `Violation`s with a code and, for logs, the rule/category name only; the
offending text is never logged here.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property

from app.ai.schemas import prose
from app.content.models import ForbiddenPhrases, OutputRules
from app.content.phrases import normalise
from app.kb import fingerprint as fp

_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[a-z0-9']+")
# Quoted spans: straight/curly double quotes, CJK quotes, and single quotes used as quote marks
# (not apostrophes: the opening one follows a non-word character, the closing one precedes one).
_QUOTED = re.compile(
    '"[^"\\n]{1,240}"'
    "|\u201c[^\u201d\\n]{1,240}\u201d|「[^」\\n]{1,240}」"
    "|『[^』\\n]{1,240}』|\u2018[^\u2019\\n]{1,240}\u2019"
    r"|(?<!\w)'(?:[^'\n]|'(?=\w)){1,240}?'(?!\w)"
)


def strip_quoted(text: str) -> str:
    return _QUOTED.sub(" ", text)


@dataclass(frozen=True)
class Violation:
    code: str  # citation | overlap | language | pattern | medical_caution | taxonomy
    rule: str  # category / sub-rule name, safe to log

    def __str__(self) -> str:
        return f"{self.code}:{self.rule}"


@dataclass(frozen=True)
class SourceChunk:
    label: str  # "S1".."Sk": what the model sees and cites
    chunk_id: str
    text: str
    handout_id: str
    title: str
    module: str


def _canon(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in t if ch.isalnum())


def shared_run(text: str, source: str, min_len: int) -> int:
    """Length of the longest common run (canonical characters) if >= min_len, else 0."""
    a, b = _canon(text), _canon(source)
    if len(a) < min_len or len(b) < min_len:
        return 0
    grams = {b[i : i + min_len] for i in range(len(b) - min_len + 1)}
    best = 0
    i = 0
    while i <= len(a) - min_len:
        if a[i : i + min_len] in grams:
            n = min_len
            while i + n < len(a) and a[i : i + n + 1] in b:
                n += 1
            best = max(best, n)
            i += n - min_len + 1
        else:
            i += 1
    return best


def shared_words(text: str, source: str, min_words: int) -> bool:
    a = _WORD.findall(normalise(text))
    b = _WORD.findall(normalise(source))
    if len(a) < min_words or len(b) < min_words:
        return False
    grams = {tuple(b[i : i + min_words]) for i in range(len(b) - min_words + 1)}
    return any(tuple(a[i : i + min_words]) in grams for i in range(len(a) - min_words + 1))


def cjk_ratio(texts: Iterable[str]) -> float | None:
    joined = "".join(texts)
    cjk = len(_CJK.findall(joined))
    latin = len(_LATIN.findall(joined))
    total = cjk + latin
    return None if total == 0 else cjk / total


class RuleChecker:
    def __init__(
        self,
        rules: OutputRules,
        phrases: ForbiddenPhrases | None = None,
        fingerprint: frozenset[str] | None = None,
    ) -> None:
        self.rules = rules
        self.phrases = phrases
        self.fingerprint = fingerprint

    @cached_property
    def _categories(self) -> list[tuple[str, re.Pattern[str]]]:
        out = [
            (name, re.compile(p, re.IGNORECASE))
            for name, pats in self.rules.categories.items()
            for p in pats.all()
        ]
        if self.phrases is not None:
            out += [
                ("crisis_promise", re.compile(p, re.IGNORECASE))
                for lang in self.phrases.languages.values()
                for p in lang.forbidden
            ]
        return out

    @cached_property
    def _caution(self) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
        mc = self.rules.medical_caution
        return (
            [re.compile(p, re.IGNORECASE) for p in mc.triggers.all()],
            [re.compile(p, re.IGNORECASE) for p in mc.required_any.all()],
        )

    # --- individual rules -----------------------------------------------------------------

    def citations(
        self, cited: Sequence[str], grounding: str, sources: Sequence[SourceChunk], sufficient: bool
    ) -> list[Violation]:
        labels = {s.label for s in sources}
        out: list[Violation] = []
        if any(c not in labels for c in cited):
            out.append(Violation("citation", "unknown_label"))
        if grounding == "manual":
            if not cited:
                out.append(Violation("citation", "manual_without_citation"))
            if not sources or not sufficient:
                out.append(Violation("citation", "manual_without_sufficient_retrieval"))
        return out

    def overlap(self, texts: Sequence[str], sources: Sequence[SourceChunk]) -> list[Violation]:
        limit = self.rules.overlap.max_shared_chars + 1
        words = self.rules.overlap.max_shared_en_words + 1
        joined = "\n".join(texts)
        for s in sources:
            if shared_run(joined, s.text, limit) or shared_words(joined, s.text, words):
                return [Violation("overlap", "retrieved_chunk")]
        if self.fingerprint and fp.overlaps(joined, self.fingerprint):
            return [Violation("overlap", "manual_fingerprint")]
        return []

    def language(self, texts: Sequence[str], language: str) -> list[Violation]:
        ratio = cjk_ratio(texts)
        if ratio is None:
            return []
        lim = self.rules.language
        if language == "zh-CN" and ratio < lim.zh_min_cjk_ratio:
            return [Violation("language", "not_chinese")]
        if language == "en" and ratio > lim.en_max_cjk_ratio:
            return [Violation("language", "not_english")]
        return []

    def patterns(self, texts: Sequence[str]) -> list[Violation]:
        found: dict[str, Violation] = {}
        quoted_ok = set(self.rules.quoted_examples_allowed)
        for text in texts:
            norm = normalise(text)
            compact = re.sub(r"\s+", "", norm)
            bare = strip_quoted(norm)
            bare_compact = re.sub(r"\s+", "", bare)
            for name, pat in self._categories:
                if name in found:
                    continue
                n, c = (bare, bare_compact) if name in quoted_ok else (norm, compact)
                if pat.search(n) or pat.search(c):
                    found[name] = Violation("pattern", name)
        return list(found.values())

    def medical_caution(self, texts: Sequence[str]) -> list[Violation]:
        triggers, required = self._caution
        norm = normalise(" ".join(texts))
        if any(t.search(norm) for t in triggers) and not any(r.search(norm) for r in required):
            return [Violation("medical_caution", "tipp_health_caution_missing")]
        return []

    @staticmethod
    def taxonomy(
        selected: str, alternatives: Sequence[str], module: str, skills: dict[str, str]
    ) -> list[Violation]:
        """`skills` maps skill id -> module id."""
        out: list[Violation] = []
        if selected not in skills:
            out.append(Violation("taxonomy", "selected_skill_not_in_taxonomy"))
        elif skills[selected] != module:
            out.append(Violation("taxonomy", "module_mismatch"))
        if any(a not in skills for a in alternatives):
            out.append(Violation("taxonomy", "alternative_not_in_taxonomy"))
        if selected in alternatives:
            out.append(Violation("taxonomy", "alternative_repeats_selected"))
        return out

    # --- all together -----------------------------------------------------------------------

    def check(
        self,
        data: dict[str, object],
        *,
        language: str,
        sources: Sequence[SourceChunk] = (),
        sufficient: bool = False,
        user_facing: bool = True,
    ) -> list[Violation]:
        raw = data.get("source_chunk_ids")
        cited = [str(c) for c in raw] if isinstance(raw, list) else []
        out = self.citations(cited, str(data.get("grounding", "none")), sources, sufficient)
        if not user_facing:
            return out
        texts = prose(data)
        out += self.overlap(texts, sources)
        out += self.language(texts, language)
        out += self.patterns(texts)
        out += self.medical_caution(texts)
        return out
