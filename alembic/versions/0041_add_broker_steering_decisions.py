"""add_broker_steering_decisions

Revision ID: 0041_broker_steering_decisions
Revises: 0040_observability_events
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0041_broker_steering_decisions"
down_revision = "0040_observability_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_steering_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("recommendation_plan_id", sa.Integer(), sa.ForeignKey("recommendation_plans.id"), nullable=False),
        sa.Column("broker_order_id", sa.Integer(), sa.ForeignKey("broker_order_executions.id"), nullable=True),
        sa.Column("broker_position_id", sa.Integer(), sa.ForeignKey("broker_positions.id"), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("execute_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("execution_status", sa.String(length=32), nullable=False, server_default="dry_run"),
        sa.Column("reason_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("proposed_stop_loss", sa.Float(), nullable=True),
        sa.Column("proposed_take_profit", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("current_stop_loss", sa.Float(), nullable=True),
        sa.Column("current_take_profit", sa.Float(), nullable=True),
        sa.Column("risk_delta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(op.f("ix_broker_steering_decisions_recommendation_plan_id"), "broker_steering_decisions", ["recommendation_plan_id"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_broker_order_id"), "broker_steering_decisions", ["broker_order_id"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_broker_position_id"), "broker_steering_decisions", ["broker_position_id"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_ticker"), "broker_steering_decisions", ["ticker"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_decision"), "broker_steering_decisions", ["decision"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_execute_allowed"), "broker_steering_decisions", ["execute_allowed"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_executed_at"), "broker_steering_decisions", ["executed_at"], unique=False)
    op.create_index(op.f("ix_broker_steering_decisions_execution_status"), "broker_steering_decisions", ["execution_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_broker_steering_decisions_execution_status"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_executed_at"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_execute_allowed"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_decision"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_ticker"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_broker_position_id"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_broker_order_id"), table_name="broker_steering_decisions")
    op.drop_index(op.f("ix_broker_steering_decisions_recommendation_plan_id"), table_name="broker_steering_decisions")
    op.drop_table("broker_steering_decisions")
