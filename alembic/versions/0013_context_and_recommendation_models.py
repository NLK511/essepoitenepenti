"""add context and recommendation models

Revision ID: 0013_context_rec_models
Revises: 0012_watchlist_metadata
Create Date: 2026-03-24 01:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_context_rec_models"
down_revision = "0012_watchlist_metadata"
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
    if "macro_context_snapshots" not in tables:
        op.create_table(
            "macro_context_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
            sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("saliency_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("confidence_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("active_themes_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("regime_tags_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("warnings_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("missing_inputs_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_breakdown_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "industry_context_snapshots" not in tables:
        op.create_table(
            "industry_context_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("industry_key", sa.String(length=120), nullable=False),
            sa.Column("industry_label", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
            sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("direction", sa.String(length=32), nullable=False, server_default="neutral"),
            sa.Column("saliency_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("confidence_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("active_drivers_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("linked_macro_themes_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("linked_industry_themes_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("warnings_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("missing_inputs_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_breakdown_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ticker_signal_snapshots" not in tables:
        op.create_table(
            "ticker_signal_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("horizon", sa.String(length=8), nullable=False, server_default="1w"),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
            sa.Column("direction", sa.String(length=32), nullable=False, server_default="neutral"),
            sa.Column("swing_probability_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("confidence_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("attention_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("macro_exposure_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("industry_alignment_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("ticker_sentiment_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("technical_setup_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("catalyst_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("expected_move_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("execution_quality_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("warnings_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("missing_inputs_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_breakdown_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "recommendation_plans" not in tables:
        op.create_table(
            "recommendation_plans",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("horizon", sa.String(length=8), nullable=False, server_default="1w"),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
            sa.Column("confidence_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("entry_price_low", sa.Float(), nullable=True),
            sa.Column("entry_price_high", sa.Float(), nullable=True),
            sa.Column("stop_loss", sa.Float(), nullable=True),
            sa.Column("take_profit", sa.Float(), nullable=True),
            sa.Column("holding_period_days", sa.Integer(), nullable=True),
            sa.Column("risk_reward_ratio", sa.Float(), nullable=True),
            sa.Column("thesis_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("rationale_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("risks_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("warnings_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("missing_inputs_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("evidence_summary_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("signal_breakdown_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("watchlist_id", sa.Integer(), nullable=True),
            sa.Column("ticker_signal_snapshot_id", sa.Integer(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"]),
            sa.ForeignKeyConstraint(["ticker_signal_snapshot_id"], ["ticker_signal_snapshots.id"]),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = {
        "macro_context_snapshots": [("ix_macro_context_snapshots_computed_at", ["computed_at"]), ("ix_macro_context_snapshots_status", ["status"])],
        "industry_context_snapshots": [
            ("ix_industry_context_snapshots_industry_key", ["industry_key"]),
            ("ix_industry_context_snapshots_computed_at", ["computed_at"]),
            ("ix_industry_context_snapshots_status", ["status"]),
        ],
        "ticker_signal_snapshots": [
            ("ix_ticker_signal_snapshots_ticker", ["ticker"]),
            ("ix_ticker_signal_snapshots_horizon", ["horizon"]),
            ("ix_ticker_signal_snapshots_computed_at", ["computed_at"]),
            ("ix_ticker_signal_snapshots_status", ["status"]),
            ("ix_ticker_signal_snapshots_job_id", ["job_id"]),
            ("ix_ticker_signal_snapshots_run_id", ["run_id"]),
        ],
        "recommendation_plans": [
            ("ix_recommendation_plans_ticker", ["ticker"]),
            ("ix_recommendation_plans_horizon", ["horizon"]),
            ("ix_recommendation_plans_action", ["action"]),
            ("ix_recommendation_plans_status", ["status"]),
            ("ix_recommendation_plans_computed_at", ["computed_at"]),
            ("ix_recommendation_plans_watchlist_id", ["watchlist_id"]),
            ("ix_recommendation_plans_ticker_signal_snapshot_id", ["ticker_signal_snapshot_id"]),
            ("ix_recommendation_plans_job_id", ["job_id"]),
            ("ix_recommendation_plans_run_id", ["run_id"]),
        ],
    }
    for table_name, definitions in indexes.items():
        existing = _get_indexes(table_name)
        for index_name, columns in definitions:
            if index_name not in existing:
                op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    for table_name in (
        "recommendation_plans",
        "ticker_signal_snapshots",
        "industry_context_snapshots",
        "macro_context_snapshots",
    ):
        if table_name in _get_tables():
            op.drop_table(table_name)
