"""'Based on: <module> · <handout title>' references for AI output (Plan §5.5.2 step 2).

Titles only, never excerpts. English titles come from the committed handout index; Chinese
titles were read from the manual at ingestion and live only in the database (D7).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import AIService, SourceRef
from app.models import KnowledgeChunk


def references(
    db: Session, ai: AIService, sources: Sequence[SourceRef], language: str
) -> list[dict[str, Any]]:
    idx = ai.content.handouts
    by_id = {h.id: h for h in idx.handouts} if idx else {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in sources:
        if ref.handout_id in seen:
            continue
        seen.add(ref.handout_id)
        h = by_id.get(ref.handout_id)
        title = h.title_en if h else ""
        if language == "zh-CN":
            try:
                cid = uuid.UUID(ref.chunk_id)
            except ValueError:
                cid = None
            zh = (
                db.scalar(select(KnowledgeChunk.handout_title_zh).where(KnowledgeChunk.id == cid))
                if cid
                else None
            )
            title = zh or title
        out.append(
            {
                "module": ai.module_name(ref.module, language),
                "handout": h.number if h else "",
                "title": title,
            }
        )
    return out[:4]
