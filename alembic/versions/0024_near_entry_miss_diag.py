"""add near-entry-miss diagnostics to recommendation outcomes

Revision ID: 0024_near_entry_miss_diag
Revises: 0023_context_refresh_cleanup
Create Date: 2026-04-19 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_near_entry_miss_diag"
down_revision = "0023_context_refresh_cleanup"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "recommendation_outcomes" not in set(inspector.get_table_names()):
        return

    with op.batch_alter_table("recommendation_outcomes") as batch_op:
        if not _has_column("recommendation_outcomes", "entry_miss_distance_percent"):
            batch_op.add_column(sa.Column("entry_miss_distance_percent", sa.Float(), nullable=True))
        if not _has_column("recommendation_outcomes", "near_entry_miss"):
            batch_op.add_column(sa.Column("near_entry_miss", sa.Boolean(), nullable=True))
        if not _has_column("recommendation_outcomes", "direction_worked_without_entry"):
            batch_op.add_column(sa.Column("direction_worked_without_entry", sa.Boolean(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "recommendation_outcomes" not in set(inspector.get_table_names()):
        return

    with op.batch_alter_table("recommendation_outcomes") as batch_op:
        if _has_column("recommendation_outcomes", "direction_worked_without_entry"):
            batch_op.drop_column("direction_worked_without_entry")
        if _has_column("recommendation_outcomes", "near_entry_miss"):
            batch_op.drop_column("near_entry_miss")
        if _has_column("recommendation_outcomes", "entry_miss_distance_percent"):
            batch_op.drop_column("entry_miss_distance_percent")
