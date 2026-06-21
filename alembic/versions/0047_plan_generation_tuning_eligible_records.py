"""persist plan generation tuning eligible records

Revision ID: 0047_plan_tuning_eligible
Revises: 0046_protective_order_evidence
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0047_plan_tuning_eligible"
down_revision = "0046_protective_order_evidence"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "plan_generation_tuning_eligible_records" in _get_tables():
        return
    op.create_table(
        "plan_generation_tuning_eligible_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("setup_family", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("context_bias", sa.String(length=32), nullable=True),
        sa.Column("confidence_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entry_price_low", sa.Float(), nullable=True),
        sa.Column("entry_price_high", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("signal_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("horizon_return_5d", sa.Float(), nullable=True),
        sa.Column("cache_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("source_updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["recommendation_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", name="uq_plan_generation_tuning_eligible_plan_id"),
    )
    op.create_index(
        "ix_plan_generation_tuning_eligible_records_plan_id",
        "plan_generation_tuning_eligible_records",
        ["plan_id"],
    )
    op.create_index(
        "ix_plan_generation_tuning_eligible_records_ticker",
        "plan_generation_tuning_eligible_records",
        ["ticker"],
    )
    op.create_index(
        "ix_plan_generation_tuning_eligible_records_computed_at",
        "plan_generation_tuning_eligible_records",
        ["computed_at"],
    )
    op.create_index(
        "ix_plan_generation_tuning_eligible_records_setup_family",
        "plan_generation_tuning_eligible_records",
        ["setup_family"],
    )
    op.create_index(
        "ix_plan_generation_tuning_eligible_records_cache_version",
        "plan_generation_tuning_eligible_records",
        ["cache_version"],
    )
    op.create_index(
        "ix_plan_generation_tuning_eligible_records_source_updated_at",
        "plan_generation_tuning_eligible_records",
        ["source_updated_at"],
    )


def downgrade() -> None:
    if "plan_generation_tuning_eligible_records" in _get_tables():
        op.drop_table("plan_generation_tuning_eligible_records")
