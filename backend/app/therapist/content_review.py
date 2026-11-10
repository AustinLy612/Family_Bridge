"""Content review of cached AI items (Plan §5.8; D71).

Caregiver explanations, practice items and quizzes are cached per skill, language, prompt and
knowledge-base version and served to every caregiver who opens that skill. Any therapist may
mark an item "reviewed" or "needs change" (D71). "Needs change" is final for that item: it is no
longer served, the next request regenerates it (or serves the authored fallback), and the new
version comes up here unreviewed. Prompt files themselves change through version control only.

Episode approval arrives with the episode registry in Phase 8.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import bad_request, conflict, not_found
from app.core.sessions import utcnow
from app.models import User
from app.models.ai import AICacheItem, CacheReview

PAGE = 50
DECISIONS = (CacheReview.reviewed, CacheReview.needs_change)


def item_view(
    item: AICacheItem, reviewers: dict[uuid.UUID, str], skill_name: Callable[[str], str]
) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "function": item.function,
        "skill": {"id": item.skill_id, "name": skill_name(item.skill_id)},
        "role": item.role,
        "language": item.language,
        "variant": item.variant,
        "prompt_version": item.prompt_version,
        "kb_version": item.kb_version,
        "source": item.source.value,
        "review": item.review.value,
        "reviewed_by": reviewers.get(item.reviewed_by) if item.reviewed_by else None,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "hits": item.hits,
        "created_at": item.created_at.isoformat(),
        "output": item.output,
    }


def _reviewers(db: Session, items: list[AICacheItem]) -> dict[uuid.UUID, str]:
    ids = {i.reviewed_by for i in items if i.reviewed_by}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.display_alias).where(User.id.in_(ids))).all())


def list_items(
    db: Session,
    skill_name: Callable[[str], str],
    *,
    review: str | None,
    function: str | None,
    skill_id: str | None,
    offset: int,
) -> dict[str, Any]:
    q = select(AICacheItem)
    if review:
        try:
            q = q.where(AICacheItem.review == CacheReview(review))
        except ValueError as err:
            raise bad_request("content.invalid_filter") from err
    if function:
        q = q.where(AICacheItem.function == function)
    if skill_id:
        q = q.where(AICacheItem.skill_id == skill_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(
        db.scalars(
            q.order_by(AICacheItem.created_at.desc(), AICacheItem.id).offset(offset).limit(PAGE)
        )
    )
    counts = dict(
        db.execute(select(AICacheItem.review, func.count()).group_by(AICacheItem.review)).all()
    )
    reviewers = _reviewers(db, items)
    return {
        "items": [item_view(i, reviewers, skill_name) for i in items],
        "total": int(total),
        "offset": offset,
        "page_size": PAGE,
        "counts": {r.value: int(counts.get(r, 0)) for r in CacheReview},
    }


def review_item(
    db: Session,
    therapist: User,
    item_id: uuid.UUID,
    decision: str,
    skill_name: Callable[[str], str],
) -> dict[str, Any]:
    item = db.get(AICacheItem, item_id)
    if item is None:
        raise not_found()
    try:
        new = CacheReview(decision)
    except ValueError as err:
        raise bad_request("content.invalid_decision") from err
    if new not in DECISIONS:
        raise bad_request("content.invalid_decision")
    if item.review is CacheReview.needs_change:
        raise conflict("content.already_withdrawn")
    item.review = new
    item.reviewed_by = therapist.id
    item.reviewed_at = utcnow()
    db.flush()
    audit.record(
        db,
        "content.cache_reviewed",
        actor=therapist,
        target_type="ai_cache_item",
        target_id=item.id,
        details={"decision": new.value, "function": item.function, "skill": item.skill_id},
    )
    return item_view(item, {therapist.id: therapist.display_alias}, skill_name)
