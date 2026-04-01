"""add recommendation autotune runs

Revision ID: 0021_recommendation_autotune_runs
Revises: 0020_decision_samples
Create Date: 2026-04-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_recommendation_autotune_runs"
down_revision = "0020_decision_samples"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _get_tables()
    if "recommendation_autotune_runs" not in tables:
        op.create_table(
            "recommendation_autotune_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("objective_name", sa.String(length=120), nullable=False, server_default="confidence_threshold_raw_grid"),
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
        op.create_index("ix_recommendation_autotune_runs_objective_name", "recommendation_autotune_runs", ["objective_name"], unique=False)
        op.create_index("ix_recommendation_autotune_runs_status", "recommendation_autotune_runs", ["status"], unique=False)
        op.create_index("ix_recommendation_autotune_runs_created_at", "recommendation_autotune_runs", ["created_at"], unique=False)


def downgrade() -> None:
    if "recommendation_autotune_runs" in _get_tables():
        op.drop_table("recommendation_autotune_runs")
