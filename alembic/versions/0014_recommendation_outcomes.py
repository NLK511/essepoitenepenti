"""add recommendation outcomes

Revision ID: 0014_recommendation_outcomes
Revises: 0013_context_and_recommendation_models
Create Date: 2026-03-24 03:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_recommendation_outcomes"
down_revision = "0013_context_and_recommendation_models"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    tables = _get_tables()
    if "recommendation_outcomes" not in tables:
        op.create_table(
            "recommendation_outcomes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("recommendation_plan_id", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.String(length=32), nullable=False, server_default="open"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
            sa.Column("evaluated_at", sa.DateTime(), nullable=False),
            sa.Column("entry_touched", sa.Boolean(), nullable=True),
            sa.Column("stop_loss_hit", sa.Boolean(), nullable=True),
            sa.Column("take_profit_hit", sa.Boolean(), nullable=True),
            sa.Column("horizon_return_1d", sa.Float(), nullable=True),
            sa.Column("horizon_return_3d", sa.Float(), nullable=True),
            sa.Column("horizon_return_5d", sa.Float(), nullable=True),
            sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
            sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
            sa.Column("realized_holding_period_days", sa.Float(), nullable=True),
            sa.Column("direction_correct", sa.Boolean(), nullable=True),
            sa.Column("confidence_bucket", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("setup_family", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["recommendation_plan_id"], ["recommendation_plans.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("recommendation_plan_id", name="uq_recommendation_outcomes_plan_id"),
        )

    existing = _get_indexes("recommendation_outcomes")
    for index_name, columns in [
        ("ix_recommendation_outcomes_recommendation_plan_id", ["recommendation_plan_id"]),
        ("ix_recommendation_outcomes_outcome", ["outcome"]),
        ("ix_recommendation_outcomes_status", ["status"]),
        ("ix_recommendation_outcomes_evaluated_at", ["evaluated_at"]),
        ("ix_recommendation_outcomes_run_id", ["run_id"]),
    ]:
        if index_name not in existing:
            op.create_index(index_name, "recommendation_outcomes", columns, unique=False)


def downgrade() -> None:
    if "recommendation_outcomes" in _get_tables():
        op.drop_table("recommendation_outcomes")
