"""Content version metadata (Plan Phase 0 task 6: "exposes content version hashes")."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@router.get("/content")
def content_versions(request: Request) -> dict[str, Any]:
    bundle = request.app.state.content
    return {"version": bundle.aggregate_hash, "files": bundle.hashes}
