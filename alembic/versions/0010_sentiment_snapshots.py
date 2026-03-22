"""add sentiment snapshots

Revision ID: 0010_sentiment_snapshots
Revises: 0009_recommendation_feature_vectors
Create Date: 2026-03-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_sentiment_snapshots"
down_revision = "0009_recommendation_feature_vectors"
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
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = _get_indexes("sentiment_snapshots")
    for name, columns, unique in (
        ("ix_sentiment_snapshots_scope", ["scope"], False),
        ("ix_sentiment_snapshots_subject_key", ["subject_key"], False),
        ("ix_sentiment_snapshots_computed_at", ["computed_at"], False),
        ("ix_sentiment_snapshots_expires_at", ["expires_at"], False),
        ("ix_sentiment_snapshots_job_id", ["job_id"], False),
        ("ix_sentiment_snapshots_run_id", ["run_id"], False),
    ):
        if name not in indexes:
            op.create_index(name, "sentiment_snapshots", columns, unique=unique)


def downgrade() -> None:
    tables = _get_tables()
    if "sentiment_snapshots" in tables:
        op.drop_table("sentiment_snapshots")
