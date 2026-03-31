"""add recommendation decision samples

Revision ID: 0020_decision_samples
Revises: 0019_historical_replay_inputs
Create Date: 2026-03-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_decision_samples"
down_revision = "0019_historical_replay_inputs"
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
    if "recommendation_decision_samples" not in tables:
        op.create_table(
            "recommendation_decision_samples",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("recommendation_plan_id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("horizon", sa.String(length=8), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("decision_type", sa.String(length=32), nullable=False, server_default="no_action"),
            sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("shortlisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("shortlist_rank", sa.Integer(), nullable=True),
            sa.Column("shortlist_decision_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("confidence_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("calibrated_confidence_percent", sa.Float(), nullable=True),
            sa.Column("effective_threshold_percent", sa.Float(), nullable=True),
            sa.Column("confidence_gap_percent", sa.Float(), nullable=True),
            sa.Column("setup_family", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("transmission_bias", sa.String(length=32), nullable=True),
            sa.Column("context_regime", sa.String(length=32), nullable=True),
            sa.Column("review_priority", sa.String(length=32), nullable=False, server_default="normal"),
            sa.Column("review_label", sa.String(length=32), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("decision_context_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("signal_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("evidence_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("watchlist_id", sa.Integer(), nullable=True),
            sa.Column("ticker_signal_snapshot_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["recommendation_plan_id"], ["recommendation_plans.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"]),
            sa.ForeignKeyConstraint(["ticker_signal_snapshot_id"], ["ticker_signal_snapshots.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("recommendation_plan_id", name="uq_recommendation_decision_samples_plan_id"),
        )

    existing = _get_indexes("recommendation_decision_samples")
    for index_name, columns in [
        ("ix_recommendation_decision_samples_ticker", ["ticker"]),
        ("ix_recommendation_decision_samples_run_id", ["run_id"]),
        ("ix_recommendation_decision_samples_decision_type", ["decision_type"]),
        ("ix_recommendation_decision_samples_review_priority", ["review_priority"]),
        ("ix_recommendation_decision_samples_reviewed_at", ["reviewed_at"]),
    ]:
        if index_name not in existing:
            op.create_index(index_name, "recommendation_decision_samples", columns, unique=False)


def downgrade() -> None:
    if "recommendation_decision_samples" in _get_tables():
        op.drop_table("recommendation_decision_samples")
