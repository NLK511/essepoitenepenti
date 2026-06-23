"""add replay eligibility records

Revision ID: 0050_replay_eligibility_records
Revises: 0049_replay_plan_outcomes
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0050_replay_eligibility_records"
down_revision = "0049_replay_plan_outcomes"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "replay_eligibility_records" in _tables():
        return
    op.create_table(
        "replay_eligibility_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("replay_batch_id", sa.Integer(), nullable=False),
        sa.Column("replay_slice_id", sa.Integer(), nullable=False),
        sa.Column("replay_plan_outcome_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_plan_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("candidate_config_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("eligibility_mode", sa.String(length=64), nullable=False, server_default="current_code_point_in_time_replay"),
        sa.Column("tier", sa.String(length=32), nullable=False, server_default="tier_c"),
        sa.Column("eligible_for_tuning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolution_source", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("rejection_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["replay_batch_id"], ["historical_replay_batches.id"]),
        sa.ForeignKeyConstraint(["replay_slice_id"], ["historical_replay_slices.id"]),
        sa.ForeignKeyConstraint(["replay_plan_outcome_id"], ["replay_plan_outcomes.id"]),
        sa.ForeignKeyConstraint(["recommendation_plan_id"], ["recommendation_plans.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replay_slice_id",
            "recommendation_plan_id",
            "candidate_config_hash",
            name="uq_replay_eligibility_slice_plan_candidate",
        ),
    )
    for column in (
        "replay_batch_id",
        "replay_slice_id",
        "replay_plan_outcome_id",
        "recommendation_plan_id",
        "run_id",
        "ticker",
        "candidate_config_hash",
        "eligibility_mode",
        "tier",
        "eligible_for_tuning",
        "resolution_source",
        "outcome",
    ):
        op.create_index(f"ix_replay_eligibility_records_{column}", "replay_eligibility_records", [column])


def downgrade() -> None:
    if "replay_eligibility_records" in _tables():
        op.drop_table("replay_eligibility_records")
