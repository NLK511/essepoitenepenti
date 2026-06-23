"""add replay plan outcomes

Revision ID: 0049_replay_plan_outcomes
Revises: 0048_news_available_at
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0049_replay_plan_outcomes"
down_revision = "0048_news_available_at"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "replay_plan_outcomes" in _tables():
        return
    op.create_table(
        "replay_plan_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("replay_batch_id", sa.Integer(), nullable=False),
        sa.Column("replay_slice_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_plan_id", sa.Integer(), nullable=False),
        sa.Column("candidate_config_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("resolution_source", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["replay_batch_id"], ["historical_replay_batches.id"]),
        sa.ForeignKeyConstraint(["replay_slice_id"], ["historical_replay_slices.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["recommendation_plan_id"], ["recommendation_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replay_slice_id",
            "recommendation_plan_id",
            "candidate_config_hash",
            name="uq_replay_plan_outcomes_slice_plan_candidate",
        ),
    )
    for column in (
        "replay_batch_id",
        "replay_slice_id",
        "run_id",
        "recommendation_plan_id",
        "candidate_config_hash",
        "outcome",
        "status",
        "evaluated_at",
    ):
        op.create_index(f"ix_replay_plan_outcomes_{column}", "replay_plan_outcomes", [column])


def downgrade() -> None:
    if "replay_plan_outcomes" in _tables():
        op.drop_table("replay_plan_outcomes")
