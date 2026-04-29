"""add broker positions table

Revision ID: 0029_broker_positions
Revises: 0028_broker_order_executions
Create Date: 2026-04-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_broker_positions"
down_revision = "0028_broker_order_executions"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "broker_positions" in _get_tables():
        return
    op.create_table(
        "broker_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker_order_execution_id", sa.Integer(), sa.ForeignKey("broker_order_executions.id"), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False, server_default="alpaca"),
        sa.Column("account_mode", sa.String(length=32), nullable=False, server_default="paper"),
        sa.Column("recommendation_plan_id", sa.Integer(), sa.ForeignKey("recommendation_plans.id"), nullable=False),
        sa.Column("recommendation_plan_ticker", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="submitted"),
        sa.Column("entry_order_id", sa.String(length=120), nullable=True),
        sa.Column("entry_avg_price", sa.Float(), nullable=True),
        sa.Column("entry_filled_at", sa.DateTime(), nullable=True),
        sa.Column("exit_order_id", sa.String(length=120), nullable=True),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("exit_avg_price", sa.Float(), nullable=True),
        sa.Column("exit_filled_at", sa.DateTime(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("realized_return_pct", sa.Float(), nullable=True),
        sa.Column("realized_r_multiple", sa.Float(), nullable=True),
        sa.Column("raw_broker_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("broker_order_execution_id", name="uq_broker_positions_broker_order_execution_id"),
    )
    for column in ["broker_order_execution_id", "broker", "account_mode", "recommendation_plan_id", "run_id", "job_id", "ticker", "action", "side", "status", "entry_order_id", "entry_filled_at", "exit_order_id", "exit_reason", "exit_filled_at"]:
        op.create_index(f"ix_broker_positions_{column}", "broker_positions", [column])


def downgrade() -> None:
    if "broker_positions" not in _get_tables():
        return
    for column in ["exit_filled_at", "exit_reason", "exit_order_id", "entry_filled_at", "entry_order_id", "status", "side", "action", "ticker", "job_id", "run_id", "recommendation_plan_id", "account_mode", "broker", "broker_order_execution_id"]:
        op.drop_index(f"ix_broker_positions_{column}", table_name="broker_positions")
    op.drop_table("broker_positions")
