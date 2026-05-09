"""add_run_correlation_id

Revision ID: 0039_run_correlation_id
Revises: 0038_merge_trend_risk_heads
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_run_correlation_id"
down_revision = "0038_merge_trend_risk_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("correlation_id", sa.String(80), nullable=True))
        batch_op.create_index(batch_op.f("ix_runs_correlation_id"), ["correlation_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_correlation_id"))
        batch_op.drop_column("correlation_id")
