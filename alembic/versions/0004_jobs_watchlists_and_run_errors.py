"""jobs watchlists and run errors

Revision ID: 0004_jobs_watchlists_and_run_errors
Revises: 0003_recommendation_diagnostics_fields
Create Date: 2026-03-14 01:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_jobs_watchlists_and_run_errors"
down_revision = "0003_recommendation_diagnostics_fields"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _get_foreign_keys(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {foreign_key.get("name") for foreign_key in inspector.get_foreign_keys(table_name) if foreign_key.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    job_columns = _get_columns("jobs")
    if "watchlist_id" not in job_columns:
        op.add_column("jobs", sa.Column("watchlist_id", sa.Integer(), nullable=True))

    job_indexes = _get_indexes("jobs")
    if "ix_jobs_watchlist_id" not in job_indexes:
        op.create_index("ix_jobs_watchlist_id", "jobs", ["watchlist_id"], unique=False)

    if dialect_name != "sqlite":
        foreign_keys = _get_foreign_keys("jobs")
        if "fk_jobs_watchlist_id_watchlists" not in foreign_keys:
            op.create_foreign_key("fk_jobs_watchlist_id_watchlists", "jobs", "watchlists", ["watchlist_id"], ["id"])

    run_columns = _get_columns("runs")
    if "error_message" not in run_columns:
        op.add_column("runs", sa.Column("error_message", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    run_columns = _get_columns("runs")
    if "error_message" in run_columns:
        op.drop_column("runs", "error_message")

    job_indexes = _get_indexes("jobs")
    if "ix_jobs_watchlist_id" in job_indexes:
        op.drop_index("ix_jobs_watchlist_id", table_name="jobs")

    if dialect_name != "sqlite":
        foreign_keys = _get_foreign_keys("jobs")
        if "fk_jobs_watchlist_id_watchlists" in foreign_keys:
            op.drop_constraint("fk_jobs_watchlist_id_watchlists", "jobs", type_="foreignkey")

    job_columns = _get_columns("jobs")
    if "watchlist_id" in job_columns:
        op.drop_column("jobs", "watchlist_id")
