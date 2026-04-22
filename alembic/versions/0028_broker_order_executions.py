"""add broker order executions table

Revision ID: 0028_broker_order_executions
Revises: 0027_sgt_bm_counts
Create Date: 2026-04-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_broker_order_executions"
down_revision = "0027_sgt_bm_counts"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "broker_order_executions" in _get_tables():
        return
    op.create_table(
        "broker_order_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker", sa.String(length=64), nullable=False, server_default="alpaca"),
        sa.Column("account_mode", sa.String(length=32), nullable=False, server_default="paper"),
        sa.Column("recommendation_plan_id", sa.Integer(), sa.ForeignKey("recommendation_plans.id"), nullable=False),
        sa.Column("recommendation_plan_ticker", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False, server_default="limit"),
        sa.Column("time_in_force", sa.String(length=16), nullable=False, server_default="gtc"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notional_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("broker_order_id", sa.String(length=120), nullable=True),
        sa.Column("client_order_id", sa.String(length=120), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("filled_at", sa.DateTime(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("request_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("response_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("broker", "client_order_id", name="uq_broker_order_executions_broker_client_order_id"),
    )
    op.create_index("ix_broker_order_executions_broker", "broker_order_executions", ["broker"])
    op.create_index("ix_broker_order_executions_account_mode", "broker_order_executions", ["account_mode"])
    op.create_index("ix_broker_order_executions_recommendation_plan_id", "broker_order_executions", ["recommendation_plan_id"])
    op.create_index("ix_broker_order_executions_run_id", "broker_order_executions", ["run_id"])
    op.create_index("ix_broker_order_executions_job_id", "broker_order_executions", ["job_id"])
    op.create_index("ix_broker_order_executions_ticker", "broker_order_executions", ["ticker"])
    op.create_index("ix_broker_order_executions_status", "broker_order_executions", ["status"])
    op.create_index("ix_broker_order_executions_client_order_id", "broker_order_executions", ["client_order_id"])


def downgrade() -> None:
    tables = _get_tables()
    if "broker_order_executions" not in tables:
        return
    op.drop_index("ix_broker_order_executions_client_order_id", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_status", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_ticker", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_job_id", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_run_id", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_recommendation_plan_id", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_account_mode", table_name="broker_order_executions")
    op.drop_index("ix_broker_order_executions_broker", table_name="broker_order_executions")
    op.drop_table("broker_order_executions")
