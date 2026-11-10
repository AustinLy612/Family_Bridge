"""Health endpoints (Plan Phase 0 task 2).

- /health/live  — the process is up. Never touches dependencies.
- /health/ready — database reachable, migrations at head, content loaded and valid.
  Returns 503 with the failing checks otherwise. Exposes no secrets or personal data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from app.core.db import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request, response: Response) -> dict[str, Any]:
    state = request.app.state
    db = check_database(state.engine_factory())
    content = state.content
    checks: dict[str, Any] = {
        "database": {"ok": db.reachable, **({"error": db.error} if db.error else {})},
        "migrations": {
            "ok": db.at_head,
            "current": list(db.current),
            "expected": list(db.expected),
        },
        "content": {
            "ok": content is not None,
            **({"version": content.aggregate_hash} if content is not None else {}),
        },
    }
    ok = all(c["ok"] for c in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "unavailable", "checks": checks}
