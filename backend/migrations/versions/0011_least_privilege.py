"""Least privilege (Plan §5.12): a DML-only group role for the API; the audit log is
SELECT/INSERT only for it. The login role itself is created by `app.cli migrate` from
APP_DB_USER / APP_DB_PASSWORD (passwords never live in migrations).

Revision ID: 0011_least_privilege
Revises: 0010_phase9
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_least_privilege"
down_revision: str | None = "0010_phase9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "familybridge_app_rw"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
            CREATE ROLE {ROLE} NOLOGIN;
          END IF;
        END $$;
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
          EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROLE}', current_database());
        END $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {ROLE}")
    op.execute(f"GRANT SELECT ON alembic_version TO {ROLE}")
    # tables and sequences created by later migrations (run as the same owner) get DML too
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    # The role is cluster-wide (shared with the test database), so it is not dropped here.
