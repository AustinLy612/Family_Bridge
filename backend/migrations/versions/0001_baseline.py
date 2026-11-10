"""Baseline: required PostgreSQL extensions (Plan Phase 0 task 3; Plan §3.1).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")    # pgvector — KB embeddings (Phase 3)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")   # keyword/trigram retrieval (Phase 3)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid(), digests


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
