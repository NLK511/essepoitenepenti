"""add trade policy snapshot to recommendation plans

Revision ID: 0030_trade_policy
Revises: 0029_broker_positions
Create Date: 2026-04-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_trade_policy"
down_revision = "0029_broker_positions"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _columns("recommendation_plans")
    if "trade_policy_id" not in columns:
        op.add_column("recommendation_plans", sa.Column("trade_policy_id", sa.String(length=128), nullable=True))
        op.create_index("ix_recommendation_plans_trade_policy_id", "recommendation_plans", ["trade_policy_id"])
    if "trade_policy_snapshot_json" not in columns:
        op.add_column(
            "recommendation_plans",
            sa.Column("trade_policy_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    columns = _columns("recommendation_plans")
    if "trade_policy_snapshot_json" in columns:
        op.drop_column("recommendation_plans", "trade_policy_snapshot_json")
    if "trade_policy_id" in columns:
        op.drop_index("ix_recommendation_plans_trade_policy_id", table_name="recommendation_plans")
        op.drop_column("recommendation_plans", "trade_policy_id")
