"""Therapist dashboard API (Plan §5.8; Phase 7).

Therapists only, and only for groups they are assigned to (Plan §4.2). Admins keep aggregate
oversight elsewhere and see no participant learning data. Every cross-user read is audited.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import AppSettings, Db, TherapistUser
from app.core.policy import ensure_family, ensure_group
from app.therapist import content_review as cr
from app.therapist import learning_review as lr
from app.therapist import metrics as mx
from app.therapist import tasks as tk
from app.therapist import time as tt

router = APIRouter(prefix="/api/v1", tags=["therapist"])


class Ai:
    def __init__(self, request: Request) -> None:
        self.ai = request.app.state.ai

    def names(self, lang: str) -> lr.Names:
        def names(sid: str) -> tuple[str, str, str]:
            mid = self.ai.skill_module.get(sid, "")
            return str(self.ai.skill_name(sid, lang) or sid), mid, self.ai.module_name(mid, lang)

        return names

    def skill_ids(self) -> set[str]:
        return set(self.ai.skill_module)


A = Annotated[Ai, Depends(Ai)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=1000)
    for_roles: list[Literal["adolescent", "caregiver"]] = Field(min_length=1, max_length=2)
    skill_ids: list[str] = Field(default_factory=list, max_length=8)
    starts_on: date
    due_on: date


class ExpectationIn(Strict):
    days_per_week: int = Field(ge=1, le=7)


class ReviewIn(Strict):
    decision: Literal["reviewed", "needs_change"]


class TimeIn(Strict):
    seconds: int = Field(ge=1, le=tt.MAX_REPORT_SECONDS)


# --- tasks & scheduling (D69, D70) ---


@router.get("/groups/{group_id}/schedule")
def schedule(group_id: uuid.UUID, therapist: TherapistUser, db: Db) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    return {
        "group": {"id": str(group.id), "name": group.name},
        "diary_days_per_week": group.diary_days_per_week,
        "tasks": tk.group_tasks(db, group),
    }


@router.put("/groups/{group_id}/diary-expectation")
def set_expectation(
    group_id: uuid.UUID, body: ExpectationIn, therapist: TherapistUser, db: Db
) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    tk.set_diary_expectation(db, therapist, group, body.days_per_week)
    return {"diary_days_per_week": group.diary_days_per_week}


@router.post("/groups/{group_id}/tasks", status_code=201)
def create_task(
    group_id: uuid.UUID, body: TaskIn, therapist: TherapistUser, db: Db, ai: A
) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    task = tk.create_task(db, therapist, group, body.model_dump(), ai.skill_ids())
    return {"task": tk.task_view(task)}


@router.put("/tasks/{task_id}")
def update_task(
    task_id: uuid.UUID, body: TaskIn, therapist: TherapistUser, db: Db, ai: A
) -> dict[str, Any]:
    task = tk.get_task(db, therapist, task_id)
    tk.update_task(db, therapist, task, body.model_dump(), ai.skill_ids())
    return {"task": tk.task_view(task)}


@router.delete("/tasks/{task_id}", status_code=204)
def archive_task(task_id: uuid.UUID, therapist: TherapistUser, db: Db) -> None:
    task = tk.get_task(db, therapist, task_id)
    tk.archive_task(db, therapist, task)


# --- learning review and mastery (D15) ---


@router.get("/families/{family_id}/learning")
def family_learning(
    family_id: uuid.UUID, therapist: TherapistUser, db: Db, ai: A
) -> dict[str, Any]:
    family = ensure_family(db, therapist, family_id)
    return {
        "family": {"id": str(family.id), "label": family.label},
        **lr.family_learning(db, therapist, family, ai.names(therapist.language)),
    }


@router.get("/families/{family_id}/learning/lessons/{lesson_id}")
def lesson_detail(
    family_id: uuid.UUID, lesson_id: uuid.UUID, therapist: TherapistUser, db: Db
) -> dict[str, Any]:
    family = ensure_family(db, therapist, family_id)
    return lr.lesson_detail(db, therapist, family, lesson_id)


@router.get("/groups/{group_id}/coverage")
def coverage(group_id: uuid.UUID, therapist: TherapistUser, db: Db, ai: A) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    lang = therapist.language
    tax = ai.ai.taxonomy
    modules = [
        {
            "id": m.id,
            "name": ai.ai.module_name(m.id, lang),
            "skills": [
                {"id": s.id, "name": str(ai.ai.skill_name(s.id, lang) or s.id)} for s in m.skills
            ],
        }
        for m in (tax.modules if tax else [])
    ]
    return {
        "group": {"id": str(group.id), "name": group.name},
        "modules": modules,
        **lr.group_coverage(db, therapist, group, ai.names(lang)),
    }


# --- content review (D71) ---


@router.get("/content/cache")
def list_cache(
    therapist: TherapistUser,
    db: Db,
    ai: A,
    review: Annotated[str | None, Query(max_length=20)] = None,
    function: Annotated[str | None, Query(max_length=40)] = None,
    skill: Annotated[str | None, Query(max_length=60)] = None,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> dict[str, Any]:
    names = ai.names(therapist.language)
    return cr.list_items(
        db,
        lambda sid: names(sid)[0],
        review=review,
        function=function,
        skill_id=skill,
        offset=offset,
    )


@router.post("/content/cache/{item_id}/review")
def review_cache(
    item_id: uuid.UUID, body: ReviewIn, therapist: TherapistUser, db: Db, ai: A
) -> dict[str, Any]:
    names = ai.names(therapist.language)
    return {
        "item": cr.review_item(db, therapist, item_id, body.decision, lambda sid: names(sid)[0])
    }


# --- metrics and therapist time ---


@router.get("/groups/{group_id}/metrics")
def metrics(
    group_id: uuid.UUID,
    therapist: TherapistUser,
    db: Db,
    settings: AppSettings,
    days: Annotated[int, Query()] = 28,
) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    return mx.group_metrics(db, group, days, settings.safety_ack_sla_hours)


@router.post("/families/{family_id}/time", status_code=204)
def report_time(family_id: uuid.UUID, body: TimeIn, therapist: TherapistUser, db: Db) -> None:
    family = ensure_family(db, therapist, family_id)
    tt.record(db, therapist, family, body.seconds)
