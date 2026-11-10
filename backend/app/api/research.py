"""Research instrumentation and export (Plan §5.10).

- `POST /research/client-events`: the browser reports usability events (client errors, scripted
  task outcomes). Closed vocabulary only, no messages or text; capped per person per hour.
- `GET/POST /admin/research-export`: admin-only preview (row counts) and download of the
  pseudonymous CSV zip. Every download is audited with its row counts (D80-D82).
- `GET/POST /groups/{id}/recruitment`: the group's therapists record enrolment-funnel
  denominators (counts of families); each save is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from app.api.deps import AdminUser, AppSettings, CurrentUser, Db, TherapistUser
from app.content.loader import ContentBundle
from app.core import audit
from app.core.errors import bad_request
from app.core.policy import ensure_group
from app.models import RecruitmentCount, ResearchEvent, User
from app.research import events as ev
from app.research import export as rx

router = APIRouter(prefix="/api/v1", tags=["research"])

CLIENT_EVENT_CAP_PER_HOUR = 120
MAX_COUNT = 100_000


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientEventIn(Strict):
    type: Literal["client.error", "task.outcome"]
    kind: Literal["js", "api_5xx", "network"] | None = None
    area: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_.:-]*$")
    task: Literal["diary_entry", "onboarding"] | None = None
    outcome: Literal["success", "abandoned"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> ClientEventIn:
        if self.type == "client.error" and (self.kind is None or self.task or self.outcome):
            raise ValueError("client.error needs kind (and optional area) only")
        if self.type == "task.outcome" and (self.task is None or self.outcome is None or self.kind):
            raise ValueError("task.outcome needs task and outcome only")
        return self


@router.post("/research/client-events", status_code=204)
def client_event(body: ClientEventIn, user: CurrentUser, db: Db) -> Response:
    since = datetime.now(UTC) - timedelta(hours=1)
    recent = db.execute(
        select(func.count(ResearchEvent.id)).where(
            ResearchEvent.subject_pseudonym == user.pseudonym_code,
            ResearchEvent.event_type.in_(ev.CLIENT_EVENTS),
            ResearchEvent.occurred_at >= since,
        )
    ).scalar_one()
    if recent < CLIENT_EVENT_CAP_PER_HOUR:  # beyond the cap, drop quietly
        if body.type == "client.error":
            ev.record(db, "client.error", user, kind=body.kind, area=body.area or None)
        else:
            ev.record(db, "task.outcome", user, task=body.task, outcome=body.outcome)
    return Response(status_code=204)


# --- admin export -------------------------------------------------------------------------


def _content(request: Request) -> ContentBundle:
    content: ContentBundle = request.app.state.content
    return content


class ExportIn(Strict):
    include_demo: bool = False


@router.get("/admin/research-export")
def export_preview(
    request: Request, admin: AdminUser, db: Db, settings: AppSettings, include_demo: bool = False
) -> dict[str, Any]:
    out = rx.build(
        db, _content(request), settings.secret_key.get_secret_value(), include_demo=include_demo
    )
    return {
        "include_demo": include_demo,
        "files": [
            {
                "path": t.path,
                "scope": t.scope,
                "description": t.description,
                "rows": out.counts[t.path],
            }
            for t in rx.TABLES
        ],
    }


@router.post("/admin/research-export")
def export_download(
    request: Request, body: ExportIn, admin: AdminUser, db: Db, settings: AppSettings
) -> Response:
    out = rx.build(
        db,
        _content(request),
        settings.secret_key.get_secret_value(),
        include_demo=body.include_demo,
    )
    data = rx.to_zip(out)
    audit.record(
        db,
        "research.export",
        actor=admin,
        details={"include_demo": body.include_demo, "rows": out.counts, "bytes": len(data)},
    )
    db.commit()  # the audit entry is durable before any data leaves the server
    name = f"familybridge-research-{date.today().isoformat()}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


# --- recruitment denominators -------------------------------------------------------------


class RecruitmentIn(Strict):
    period_start: date
    period_end: date
    screened: int = Field(ge=0, le=MAX_COUNT)
    eligible: int = Field(ge=0, le=MAX_COUNT)
    approached: int = Field(ge=0, le=MAX_COUNT)
    consented: int = Field(ge=0, le=MAX_COUNT)


def _out(r: RecruitmentCount, by: User | None) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        "screened": r.screened,
        "eligible": r.eligible,
        "approached": r.approached,
        "consented": r.consented,
        "recorded_at": r.recorded_at.isoformat(),
        "recorded_by": by.display_alias if by else None,
    }


@router.get("/groups/{group_id}/recruitment")
def recruitment(group_id: uuid.UUID, therapist: TherapistUser, db: Db) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    rows = db.execute(
        select(RecruitmentCount)
        .where(RecruitmentCount.group_id == group.id)
        .order_by(RecruitmentCount.recorded_at.desc())
    ).scalars()
    latest: dict[tuple[date, date], dict[str, Any]] = {}
    for r in rows:
        key = (r.period_start, r.period_end)
        if key not in latest:
            latest[key] = _out(r, db.get(User, r.recorded_by) if r.recorded_by else None)
    return {"items": sorted(latest.values(), key=lambda x: x["period_start"], reverse=True)}


@router.post("/groups/{group_id}/recruitment", status_code=201)
def add_recruitment(
    group_id: uuid.UUID, body: RecruitmentIn, therapist: TherapistUser, db: Db
) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    if body.period_end < body.period_start:
        raise bad_request("recruitment.invalid_period")
    if not (body.screened >= body.eligible >= body.approached >= body.consented):
        raise bad_request("recruitment.funnel_order")
    r = RecruitmentCount(group_id=group.id, recorded_by=therapist.id, **body.model_dump())
    db.add(r)
    db.flush()
    audit.record(
        db,
        "recruitment.recorded",
        actor=therapist,
        target_type="group",
        target_id=group.id,
        details=body.model_dump(mode="json"),
    )
    return _out(r, therapist)
