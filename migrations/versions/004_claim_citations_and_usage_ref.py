"""004 Citations per claim, usage per answer/report

Revision ID: 004_claim_cit_usage_ref
Revises: 003_unique_report_job
Create Date: 2026-11-09 00:00:00.000000

message_citations.claim_id lets reloaded history show which quote backs which claim.
usage_ledger.ref_id ties a ledger row to the chat message or report it paid for.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_claim_cit_usage_ref"
down_revision: str | None = "003_unique_report_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message_citations",
        sa.Column("claim_id", sa.String(64), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("idx_message_citations_claim", "message_citations", ["claim_id"])
    op.add_column("usage_ledger", sa.Column("ref_id", sa.String(64), nullable=True))
    op.create_index("idx_usage_ledger_ref", "usage_ledger", ["ref_id"])


def downgrade() -> None:
    op.drop_index("idx_usage_ledger_ref", table_name="usage_ledger")
    op.drop_column("usage_ledger", "ref_id")
    op.drop_index("idx_message_citations_claim", table_name="message_citations")
    op.drop_column("message_citations", "claim_id")
