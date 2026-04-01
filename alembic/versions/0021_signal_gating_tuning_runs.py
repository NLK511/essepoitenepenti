"""add recommendation signal_gating_tuning runs

Revision ID: 0021_signal_gating_tuning_runs
Revises: 0020_decision_samples
Create Date: 2026-04-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_signal_gating_tuning_runs"
down_revision = "0020_decision_samples"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _get_tables()
    if "recommendation_autotune_runs" in tables and "signal_gating_tuning_runs" not in tables:
        op.rename_table("recommendation_autotune_runs", "signal_gating_tuning_runs")
        tables = _get_tables()
    if "signal_gating_tuning_runs" not in tables:
        op.create_table(
            "signal_gating_tuning_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("objective_name", sa.String(length=120), nullable=False, server_default="signal_gating_tuning_raw_grid"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
            sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("filters_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("resolved_sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("baseline_threshold", sa.Float(), nullable=True),
            sa.Column("baseline_score", sa.Float(), nullable=True),
            sa.Column("best_threshold", sa.Float(), nullable=True),
            sa.Column("best_score", sa.Float(), nullable=True),
            sa.Column("winning_config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("candidate_results_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("artifact_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_signal_gating_tuning_runs_objective_name", "signal_gating_tuning_runs", ["objective_name"], unique=False)
        op.create_index("ix_signal_gating_tuning_runs_status", "signal_gating_tuning_runs", ["status"], unique=False)
        op.create_index("ix_signal_gating_tuning_runs_created_at", "signal_gating_tuning_runs", ["created_at"], unique=False)

    settings_renames = [
        ("autotune_threshold_offset", "signal_gating_tuning_threshold_offset"),
        ("autotune_confidence_adjustment", "signal_gating_tuning_confidence_adjustment"),
        ("autotune_near_miss_gap_cutoff", "signal_gating_tuning_near_miss_gap_cutoff"),
        ("autotune_shortlist_aggressiveness", "signal_gating_tuning_shortlist_aggressiveness"),
        ("autotune_degraded_penalty", "signal_gating_tuning_degraded_penalty"),
    ]
    for old_key, new_key in settings_renames:
        existing_new = bind.execute(sa.text("SELECT 1 FROM app_settings WHERE key = :new_key LIMIT 1"), {"new_key": new_key}).scalar_one_or_none()
        if existing_new is None:
            bind.execute(sa.text("UPDATE app_settings SET key = :new_key WHERE key = :old_key"), {"new_key": new_key, "old_key": old_key})
        else:
            bind.execute(sa.text("DELETE FROM app_settings WHERE key = :old_key"), {"old_key": old_key})


def downgrade() -> None:
    if "signal_gating_tuning_runs" in _get_tables():
        op.drop_table("signal_gating_tuning_runs")
