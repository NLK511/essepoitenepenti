"""rename context refresh job types and drop legacy support snapshots

Revision ID: 0023_context_refresh_cleanup
Revises: 0022_plan_generation_tuning
Create Date: 2026-04-12 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_context_refresh_cleanup"
down_revision = "0022_plan_generation_tuning"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    tables = _get_tables()

    if "jobs" in tables and _has_column("jobs", "job_type"):
        bind.execute(sa.text(
            "UPDATE jobs SET job_type = 'macro_context_refresh' WHERE job_type = 'macro_sentiment_refresh'"
        ))
        bind.execute(sa.text(
            "UPDATE jobs SET job_type = 'industry_context_refresh' WHERE job_type = 'industry_sentiment_refresh'"
        ))

    if "runs" in tables and _has_column("runs", "job_type"):
        bind.execute(sa.text(
            "UPDATE runs SET job_type = 'macro_context_refresh' WHERE job_type = 'macro_sentiment_refresh'"
        ))
        bind.execute(sa.text(
            "UPDATE runs SET job_type = 'industry_context_refresh' WHERE job_type = 'industry_sentiment_refresh'"
        ))

    if "sentiment_snapshots" in tables:
        op.drop_table("sentiment_snapshots")


def downgrade() -> None:
    tables = _get_tables()
    bind = op.get_bind()

    if "jobs" in tables and _has_column("jobs", "job_type"):
        bind.execute(sa.text(
            "UPDATE jobs SET job_type = 'macro_sentiment_refresh' WHERE job_type = 'macro_context_refresh'"
        ))
        bind.execute(sa.text(
            "UPDATE jobs SET job_type = 'industry_sentiment_refresh' WHERE job_type = 'industry_context_refresh'"
        ))

    if "runs" in tables and _has_column("runs", "job_type"):
        bind.execute(sa.text(
            "UPDATE runs SET job_type = 'macro_sentiment_refresh' WHERE job_type = 'macro_context_refresh'"
        ))
        bind.execute(sa.text(
            "UPDATE runs SET job_type = 'industry_sentiment_refresh' WHERE job_type = 'industry_context_refresh'"
        ))

    if "sentiment_snapshots" not in tables:
        op.create_table(
            "sentiment_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(length=32), nullable=False),
            sa.Column("subject_key", sa.String(length=120), nullable=False),
            sa.Column("subject_label", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("label", sa.String(length=32), nullable=False, server_default="NEUTRAL"),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("coverage_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_breakdown_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("drivers_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("signals_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sentiment_snapshots_scope", "sentiment_snapshots", ["scope"], unique=False)
        op.create_index("ix_sentiment_snapshots_subject_key", "sentiment_snapshots", ["subject_key"], unique=False)
        op.create_index("ix_sentiment_snapshots_computed_at", "sentiment_snapshots", ["computed_at"], unique=False)
        op.create_index("ix_sentiment_snapshots_expires_at", "sentiment_snapshots", ["expires_at"], unique=False)
