"""003 One report per job

Revision ID: 003_unique_report_job
Revises: 002_reports
Create Date: 2026-11-08 00:00:00.000000

SQS can deliver a report job to two workers at once. The unique index makes the second insert fail
instead of leaving two reports, which made GET /jobs/{id} return 500.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "003_unique_report_job"
down_revision: str | None = "002_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("idx_reports_job", table_name="reports")
    op.create_index("uq_reports_job", "reports", ["job_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_reports_job", table_name="reports")
    op.create_index("idx_reports_job", "reports", ["job_id"])
