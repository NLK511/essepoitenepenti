"""Add candidate plan artifacts table."""

from alembic import op
import sqlalchemy as sa


revision = "0054_candidate_plan_artifacts"
down_revision = "0053_tuning_experiments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_plan_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("replay_batch_id", sa.Integer(), nullable=False),
        sa.Column("replay_slice_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("source_baseline_plan_id", sa.Integer(), nullable=False),
        sa.Column("source_replay_eligibility_id", sa.Integer(), nullable=True),
        sa.Column("candidate_config_hash", sa.String(length=128), nullable=False),
        sa.Column("validation_depth", sa.String(length=64), nullable=False),
        sa.Column("candidate_config_json", sa.Text(), nullable=False),
        sa.Column("source_plan_payload_json", sa.Text(), nullable=False),
        sa.Column("candidate_plan_payload_json", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("entry_price_low", sa.Float(), nullable=True),
        sa.Column("entry_price_high", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("holding_period_days", sa.Integer(), nullable=True),
        sa.Column("geometry_hash", sa.String(length=128), nullable=False),
        sa.Column("source_geometry_hash", sa.String(length=128), nullable=False),
        sa.Column("regeneration_status", sa.String(length=32), nullable=False),
        sa.Column("invalid_geometry_reasons_json", sa.Text(), nullable=False),
        sa.Column("settings_snapshot_hash", sa.String(length=128), nullable=False),
        sa.Column("code_version_hash", sa.String(length=128), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["replay_batch_id"], ["historical_replay_batches.id"]),
        sa.ForeignKeyConstraint(["replay_slice_id"], ["historical_replay_slices.id"]),
        sa.ForeignKeyConstraint(["source_baseline_plan_id"], ["recommendation_plans.id"]),
        sa.ForeignKeyConstraint(["source_replay_eligibility_id"], ["replay_eligibility_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("replay_slice_id", "source_baseline_plan_id", "candidate_config_hash", name="uq_candidate_plan_artifacts_slice_plan_candidate"),
    )
    op.create_index("ix_candidate_plan_artifacts_replay_batch_id", "candidate_plan_artifacts", ["replay_batch_id"])
    op.create_index("ix_candidate_plan_artifacts_replay_slice_id", "candidate_plan_artifacts", ["replay_slice_id"])
    op.create_index("ix_candidate_plan_artifacts_ticker", "candidate_plan_artifacts", ["ticker"])
    op.create_index("ix_candidate_plan_artifacts_as_of", "candidate_plan_artifacts", ["as_of"])
    op.create_index("ix_candidate_plan_artifacts_source_baseline_plan_id", "candidate_plan_artifacts", ["source_baseline_plan_id"])
    op.create_index("ix_candidate_plan_artifacts_source_replay_eligibility_id", "candidate_plan_artifacts", ["source_replay_eligibility_id"])
    op.create_index("ix_candidate_plan_artifacts_candidate_config_hash", "candidate_plan_artifacts", ["candidate_config_hash"])
    op.create_index("ix_candidate_plan_artifacts_validation_depth", "candidate_plan_artifacts", ["validation_depth"])
    op.create_index("ix_candidate_plan_artifacts_geometry_hash", "candidate_plan_artifacts", ["geometry_hash"])
    op.create_index("ix_candidate_plan_artifacts_source_geometry_hash", "candidate_plan_artifacts", ["source_geometry_hash"])
    op.create_index("ix_candidate_plan_artifacts_regeneration_status", "candidate_plan_artifacts", ["regeneration_status"])


def downgrade() -> None:
    op.drop_index("ix_candidate_plan_artifacts_regeneration_status", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_source_geometry_hash", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_geometry_hash", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_validation_depth", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_candidate_config_hash", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_source_replay_eligibility_id", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_source_baseline_plan_id", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_as_of", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_ticker", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_replay_slice_id", table_name="candidate_plan_artifacts")
    op.drop_index("ix_candidate_plan_artifacts_replay_batch_id", table_name="candidate_plan_artifacts")
    op.drop_table("candidate_plan_artifacts")
