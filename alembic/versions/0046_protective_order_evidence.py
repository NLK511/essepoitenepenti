"""add protective order evidence to broker positions

Revision ID: 0046_protective_order_evidence
Revises: 0045_broker_safety
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0046_protective_order_evidence"
down_revision = "0045_broker_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("broker_positions") as batch:
        batch.add_column(sa.Column("stop_loss_order_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("stop_loss_order_status", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("stop_loss_order_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("take_profit_order_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("take_profit_order_status", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("take_profit_order_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("protective_orders_verified_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "protective_orders_source", sa.String(length=64), nullable=False, server_default=""
            )
        )
    op.create_index(
        "ix_broker_positions_stop_loss_order_id", "broker_positions", ["stop_loss_order_id"]
    )
    op.create_index(
        "ix_broker_positions_stop_loss_order_status", "broker_positions", ["stop_loss_order_status"]
    )
    op.create_index(
        "ix_broker_positions_take_profit_order_id", "broker_positions", ["take_profit_order_id"]
    )
    op.create_index(
        "ix_broker_positions_take_profit_order_status",
        "broker_positions",
        ["take_profit_order_status"],
    )
    op.create_index(
        "ix_broker_positions_protective_orders_verified_at",
        "broker_positions",
        ["protective_orders_verified_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_broker_positions_protective_orders_verified_at", table_name="broker_positions"
    )
    op.drop_index("ix_broker_positions_take_profit_order_status", table_name="broker_positions")
    op.drop_index("ix_broker_positions_take_profit_order_id", table_name="broker_positions")
    op.drop_index("ix_broker_positions_stop_loss_order_status", table_name="broker_positions")
    op.drop_index("ix_broker_positions_stop_loss_order_id", table_name="broker_positions")
    with op.batch_alter_table("broker_positions") as batch:
        batch.drop_column("protective_orders_source")
        batch.drop_column("protective_orders_verified_at")
        batch.drop_column("take_profit_order_price")
        batch.drop_column("take_profit_order_status")
        batch.drop_column("take_profit_order_id")
        batch.drop_column("stop_loss_order_price")
        batch.drop_column("stop_loss_order_status")
        batch.drop_column("stop_loss_order_id")
