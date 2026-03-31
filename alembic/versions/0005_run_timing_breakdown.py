"""run timing breakdown

Revision ID: 0005_run_timing_breakdown
Revises: 0004_jobs_watchlists_run_errs
Create Date: 2026-03-15 00:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_run_timing_breakdown"
down_revision = "0004_jobs_watchlists_run_errs"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    run_columns = _get_columns("runs")
    if "started_at" not in run_columns:
        op.add_column("runs", sa.Column("started_at", sa.DateTime(), nullable=True))
    if "completed_at" not in run_columns:
        op.add_column("runs", sa.Column("completed_at", sa.DateTime(), nullable=True))
    if "duration_seconds" not in run_columns:
        op.add_column("runs", sa.Column("duration_seconds", sa.Float(), nullable=True))
    if "timing_json" not in run_columns:
        op.add_column("runs", sa.Column("timing_json", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    run_columns = _get_columns("runs")
    if "timing_json" in run_columns:
        op.drop_column("runs", "timing_json")
    if "duration_seconds" in run_columns:
        op.drop_column("runs", "duration_seconds")
    if "completed_at" in run_columns:
        op.drop_column("runs", "completed_at")
    if "started_at" in run_columns:
        op.drop_column("runs", "started_at")
