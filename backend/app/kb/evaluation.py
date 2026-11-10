"""Retrieval evaluation (Plan §5.3 step 8; Phase 3 acceptance: recall@5 >= 0.85 per language).

A query is a hit when any of its expected handouts appears among the top-k results. MRR uses
the rank of the first expected handout (0 when absent). Reports contain ids and numbers only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.content.models import RetrievalEvalSet
from app.kb.retrieval import KnowledgeService


@dataclass
class Bucket:
    n: int = 0
    hits: int = 0
    rr: float = 0.0

    def add(self, rank: int | None) -> None:
        self.n += 1
        if rank is not None:
            self.hits += 1
            self.rr += 1.0 / rank

    def as_dict(self) -> dict[str, float | int]:
        return {
            "queries": self.n,
            "recall": round(self.hits / self.n, 4) if self.n else 0.0,
            "mrr": round(self.rr / self.n, 4) if self.n else 0.0,
        }


@dataclass
class EvalReport:
    k: int
    target: float
    document_version: int | None
    overall: Bucket = field(default_factory=Bucket)
    by_language: dict[str, Bucket] = field(default_factory=dict)
    by_module: dict[str, Bucket] = field(default_factory=dict)
    misses: list[dict[str, Any]] = field(default_factory=list)
    similarities_hit: list[float] = field(default_factory=list)  # top-1 similarity on hits
    similarities_miss: list[float] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.by_language) and all(
            b.hits / b.n >= self.target for b in self.by_language.values() if b.n
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "target_recall": self.target,
            "document_version": self.document_version,
            "passed": self.passed,
            "overall": self.overall.as_dict(),
            "by_language": {k: v.as_dict() for k, v in sorted(self.by_language.items())},
            "by_module": {k: v.as_dict() for k, v in sorted(self.by_module.items())},
            "misses": self.misses,
        }


def run_eval(
    db: Session, service: KnowledgeService, eval_set: RetrievalEvalSet, module_of: dict[str, str]
) -> EvalReport:
    report = EvalReport(k=eval_set.k, target=eval_set.target_recall, document_version=None)
    for q in eval_set.queries:
        res = service.search(
            db,
            q.query,
            language=q.language,
            caller="eval",
            skill_ids=q.skill_ids,
            module=q.module,
            k=eval_set.k,
            log=False,
        )
        report.document_version = res.document_version
        got = [h.handout_id for h in res.hits]
        rank = next((i for i, hid in enumerate(got, 1) if hid in q.expected), None)
        report.overall.add(rank)
        report.by_language.setdefault(q.language, Bucket()).add(rank)
        report.by_module.setdefault(module_of.get(q.expected[0], "?"), Bucket()).add(rank)
        if res.top_similarity is not None:
            (report.similarities_hit if rank else report.similarities_miss).append(
                res.top_similarity
            )
        if rank is None:
            report.misses.append({"id": q.id, "expected": q.expected, "got": got})
    return report
