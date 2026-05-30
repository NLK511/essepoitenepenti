"""add fundamental analysis snapshots

Revision ID: 0043_fund_snapshots
Revises: 0042_merge_broker_heads
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0043_fund_snapshots"
down_revision = "0042_merge_broker_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_analysis_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("source_set_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("coverage_status", sa.String(length=32), nullable=False, server_default="degraded"),
        sa.Column("freshness_status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("missing_inputs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_fundamental_analysis_snapshots_ticker", "fundamental_analysis_snapshots", ["ticker"])
    op.create_index("ix_fundamental_analysis_snapshots_as_of", "fundamental_analysis_snapshots", ["as_of"])
    op.create_index("ix_fundamental_analysis_snapshots_coverage_status", "fundamental_analysis_snapshots", ["coverage_status"])
    op.create_index("ix_fundamental_analysis_snapshots_freshness_status", "fundamental_analysis_snapshots", ["freshness_status"])
    op.create_index("ix_fundamental_analysis_snapshots_job_id", "fundamental_analysis_snapshots", ["job_id"])
    op.create_index("ix_fundamental_analysis_snapshots_run_id", "fundamental_analysis_snapshots", ["run_id"])


def downgrade() -> None:
    op.drop_table("fundamental_analysis_snapshots")
