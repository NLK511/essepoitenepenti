"""add plan generation tuning core tables

Revision ID: 0022_plan_generation_tuning
Revises: 0021_sgt_runs
Create Date: 2026-04-02 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_plan_generation_tuning"
down_revision = "0021_sgt_runs"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _get_tables()
    if "plan_generation_tuning_config_versions" not in tables:
        op.create_table(
            "plan_generation_tuning_config_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("version_label", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("parent_config_version_id", sa.Integer(), nullable=True),
            sa.Column("source_run_id", sa.Integer(), nullable=True),
            sa.Column("source_candidate_id", sa.Integer(), nullable=True),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("parameter_schema_version", sa.String(length=32), nullable=False, server_default="v1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["parent_config_version_id"], ["plan_generation_tuning_config_versions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_plan_generation_tuning_config_versions_version_label", "plan_generation_tuning_config_versions", ["version_label"], unique=False)
        op.create_index("ix_plan_generation_tuning_config_versions_status", "plan_generation_tuning_config_versions", ["status"], unique=False)
        op.create_index("ix_plan_generation_tuning_config_versions_source", "plan_generation_tuning_config_versions", ["source"], unique=False)

    if "plan_generation_tuning_runs" not in tables:
        op.create_table(
            "plan_generation_tuning_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("objective_name", sa.String(length=120), nullable=False, server_default="plan_generation_precision_tuning_v1"),
            sa.Column("promotion_mode", sa.String(length=32), nullable=False, server_default="dry_run"),
            sa.Column("baseline_config_version_id", sa.Integer(), nullable=True),
            sa.Column("winning_candidate_id", sa.Integer(), nullable=True),
            sa.Column("promoted_config_version_id", sa.Integer(), nullable=True),
            sa.Column("eligible_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("eligible_tier_a_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("validation_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("filters_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("code_version", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["baseline_config_version_id"], ["plan_generation_tuning_config_versions.id"]),
            sa.ForeignKeyConstraint(["promoted_config_version_id"], ["plan_generation_tuning_config_versions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_plan_generation_tuning_runs_status", "plan_generation_tuning_runs", ["status"], unique=False)
        op.create_index("ix_plan_generation_tuning_runs_mode", "plan_generation_tuning_runs", ["mode"], unique=False)
        op.create_index("ix_plan_generation_tuning_runs_objective_name", "plan_generation_tuning_runs", ["objective_name"], unique=False)

    if "plan_generation_tuning_candidates" not in tables:
        op.create_table(
            "plan_generation_tuning_candidates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="evaluated"),
            sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("promotion_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("changed_keys_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("score_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("metric_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("sample_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("validation_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("rejection_reasons_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["plan_generation_tuning_runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_plan_generation_tuning_candidates_run_id", "plan_generation_tuning_candidates", ["run_id"], unique=False)
        op.create_index("ix_plan_generation_tuning_candidates_rank", "plan_generation_tuning_candidates", ["rank"], unique=False)
        op.create_index("ix_plan_generation_tuning_candidates_status", "plan_generation_tuning_candidates", ["status"], unique=False)

    if "plan_generation_tuning_events" not in tables:
        op.create_table(
            "plan_generation_tuning_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("config_version_id", sa.Integer(), nullable=True),
            sa.Column("candidate_id", sa.Integer(), nullable=True),
            sa.Column("actor_type", sa.String(length=32), nullable=False, server_default="system"),
            sa.Column("actor_identifier", sa.String(length=120), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["plan_generation_tuning_runs.id"]),
            sa.ForeignKeyConstraint(["config_version_id"], ["plan_generation_tuning_config_versions.id"]),
            sa.ForeignKeyConstraint(["candidate_id"], ["plan_generation_tuning_candidates.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_plan_generation_tuning_events_event_type", "plan_generation_tuning_events", ["event_type"], unique=False)
        op.create_index("ix_plan_generation_tuning_events_run_id", "plan_generation_tuning_events", ["run_id"], unique=False)
        op.create_index("ix_plan_generation_tuning_events_config_version_id", "plan_generation_tuning_events", ["config_version_id"], unique=False)
        op.create_index("ix_plan_generation_tuning_events_candidate_id", "plan_generation_tuning_events", ["candidate_id"], unique=False)


def downgrade() -> None:
    tables = _get_tables()
    if "plan_generation_tuning_events" in tables:
        op.drop_table("plan_generation_tuning_events")
    if "plan_generation_tuning_candidates" in tables:
        op.drop_table("plan_generation_tuning_candidates")
    if "plan_generation_tuning_runs" in tables:
        op.drop_table("plan_generation_tuning_runs")
    if "plan_generation_tuning_config_versions" in tables:
        op.drop_table("plan_generation_tuning_config_versions")
