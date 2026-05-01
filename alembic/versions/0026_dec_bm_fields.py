"""add benchmark fields to recommendation decision samples

Revision ID: 0026_decision_sample_bm_fields
Revises: 0025_merge_heads
Create Date: 2026-04-19 00:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_decision_sample_bm_fields"
down_revision = "0025_merge_heads"
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
    if "recommendation_decision_samples" not in _get_tables():
        return
    existing_columns = _get_columns("recommendation_decision_samples")
    with op.batch_alter_table("recommendation_decision_samples") as batch_op:
        if "benchmark_direction" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_direction", sa.String(length=32), nullable=True))
        if "benchmark_status" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_status", sa.String(length=32), nullable=False, server_default="pending"))
        if "benchmark_target_1d_hit" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_target_1d_hit", sa.Boolean(), nullable=True))
        if "benchmark_target_5d_hit" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_target_5d_hit", sa.Boolean(), nullable=True))
        if "benchmark_max_favorable_pct" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_max_favorable_pct", sa.Float(), nullable=True))
        if "benchmark_evaluated_at" not in existing_columns:
            batch_op.add_column(sa.Column("benchmark_evaluated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if "recommendation_decision_samples" not in _get_tables():
        return
    existing_columns = _get_columns("recommendation_decision_samples")
    with op.batch_alter_table("recommendation_decision_samples") as batch_op:
        for column_name in [
            "benchmark_evaluated_at",
            "benchmark_max_favorable_pct",
            "benchmark_target_5d_hit",
            "benchmark_target_1d_hit",
            "benchmark_status",
            "benchmark_direction",
        ]:
            if column_name in existing_columns:
                batch_op.drop_column(column_name)
