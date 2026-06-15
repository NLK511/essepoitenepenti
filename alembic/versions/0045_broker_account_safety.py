"""add broker account safety state

Revision ID: 0045_broker_safety
Revises: 0044_broker_accounts
Create Date: 2026-06-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0045_broker_safety"
down_revision = "0044_broker_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_circuit_breakers",
        sa.Column(
            "broker_account_id",
            sa.String(length=120),
            sa.ForeignKey("broker_accounts.broker_account_id"),
            primary_key=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
        sa.Column("clear_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_broker_circuit_breakers_active", "broker_circuit_breakers", ["active"])
    op.create_index(
        "ix_broker_circuit_breakers_activated_at",
        "broker_circuit_breakers",
        ["activated_at"],
    )
    op.create_index(
        "ix_broker_circuit_breakers_cleared_at",
        "broker_circuit_breakers",
        ["cleared_at"],
    )

    op.create_table(
        "broker_drawdown_states",
        sa.Column(
            "broker_account_id",
            sa.String(length=120),
            sa.ForeignKey("broker_accounts.broker_account_id"),
            primary_key=True,
        ),
        sa.Column("current_equity", sa.Float(), nullable=True),
        sa.Column("daily_high_water_equity", sa.Float(), nullable=True),
        sa.Column("total_high_water_equity", sa.Float(), nullable=True),
        sa.Column("broker_timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("daily_boundary", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("baseline_source", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_broker_drawdown_states_trusted", "broker_drawdown_states", ["trusted"])


def downgrade() -> None:
    op.drop_index("ix_broker_drawdown_states_trusted", table_name="broker_drawdown_states")
    op.drop_table("broker_drawdown_states")
    op.drop_index("ix_broker_circuit_breakers_cleared_at", table_name="broker_circuit_breakers")
    op.drop_index("ix_broker_circuit_breakers_activated_at", table_name="broker_circuit_breakers")
    op.drop_index("ix_broker_circuit_breakers_active", table_name="broker_circuit_breakers")
    op.drop_table("broker_circuit_breakers")
