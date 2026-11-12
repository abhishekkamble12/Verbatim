"""002 Reports table (Project.txt section 9) and one-source-per-file uniqueness

Revision ID: 002_reports
Revises: 001_initial_schema
Create Date: 2026-11-07 23:00:00.000000

A report is produced by one `jobs` row, so that row is the "agent run"; steps live in `agent_steps`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_reports"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notebook_id", sa.String(length=64), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(length=64), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("claims_json", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_reports_user_nb", "reports", ["user_id", "notebook_id"])
    op.create_index("idx_reports_job", "reports", ["job_id"])
    op.create_unique_constraint("uq_sources_notebook_sha", "sources", ["notebook_id", "sha256"])


def downgrade() -> None:
    op.drop_constraint("uq_sources_notebook_sha", "sources", type_="unique")
    op.drop_table("reports")
