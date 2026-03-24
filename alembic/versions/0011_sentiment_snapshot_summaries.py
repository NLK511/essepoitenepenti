"""add snapshot summary text

Revision ID: 0011_sentiment_snapshot_summaries
Revises: 0010_sentiment_snapshots
Create Date: 2026-03-24 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_sentiment_snapshot_summaries"
down_revision = "0010_sentiment_snapshots"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    tables = _get_tables()
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
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        columns = _get_columns("sentiment_snapshots")
        if "summary_text" not in columns:
            op.add_column("sentiment_snapshots", sa.Column("summary_text", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    tables = _get_tables()
    if "sentiment_snapshots" in tables:
        columns = _get_columns("sentiment_snapshots")
        if "summary_text" in columns:
            op.drop_column("sentiment_snapshots", "summary_text")
