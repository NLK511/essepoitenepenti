"""initial schema

Revision ID: 0001_initial
Revises: None
Create Date: 2026-03-14 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("tickers_csv", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_watchlists_name", "watchlists", ["name"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("tickers_csv", sa.Text(), nullable=False),
        sa.Column("schedule", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_jobs_name", "jobs", ["name"], unique=True)

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_runs_job_id", "runs", ["job_id"], unique=False)
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profit", sa.Float(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("analysis_json", sa.Text(), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recommendations_run_id", "recommendations", ["run_id"], unique=False)
    op.create_index("ix_recommendations_ticker", "recommendations", ["ticker"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "provider_credentials",
        sa.Column("provider", sa.String(length=120), primary_key=True),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("api_secret", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_credentials")
    op.drop_table("app_settings")
    op.drop_index("ix_recommendations_ticker", table_name="recommendations")
    op.drop_index("ix_recommendations_run_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_job_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_jobs_name", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_watchlists_name", table_name="watchlists")
    op.drop_table("watchlists")
