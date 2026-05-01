"""add risk halt event audit table

Revision ID: 0031_risk_halt_events
Revises: 0030_recommendation_plan_trade_policy
Create Date: 2026-04-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_risk_halt_events"
down_revision = "0030_recommendation_plan_trade_policy"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "risk_halt_events" in _tables():
        return
    op.create_table(
        "risk_halt_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("previous_halt_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("new_halt_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actor", sa.String(length=64), nullable=False, server_default="operator"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_risk_halt_events_action", "risk_halt_events", ["action"])
    op.create_index("ix_risk_halt_events_created_at", "risk_halt_events", ["created_at"])


def downgrade() -> None:
    if "risk_halt_events" not in _tables():
        return
    op.drop_index("ix_risk_halt_events_created_at", table_name="risk_halt_events")
    op.drop_index("ix_risk_halt_events_action", table_name="risk_halt_events")
    op.drop_table("risk_halt_events")
