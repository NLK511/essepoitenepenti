"""add benchmark counts to signal gating tuning runs

Revision ID: 0027_sgt_bm_counts
Revises: 0026_decision_sample_bm_fields
Create Date: 2026-04-20 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_sgt_bm_counts"
down_revision = "0026_decision_sample_bm_fields"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "signal_gating_tuning_runs" not in _get_tables():
        return
    existing_columns = _get_columns("signal_gating_tuning_runs")
    with op.batch_alter_table("signal_gating_tuning_runs") as batch_op:
        if "benchmark_sample_count" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_sample_count", sa.Integer(), nullable=False, server_default="0"))
        if "scoreable_sample_count" not in existing_columns:
            batch_op.add_column(sa.Column("scoreable_sample_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    if "signal_gating_tuning_runs" not in _get_tables():
        return
    existing_columns = _get_columns("signal_gating_tuning_runs")
    with op.batch_alter_table("signal_gating_tuning_runs") as batch_op:
        for column_name in ["scoreable_sample_count", "benchmark_sample_count"]:
            if column_name in existing_columns:
                batch_op.drop_column(column_name)
