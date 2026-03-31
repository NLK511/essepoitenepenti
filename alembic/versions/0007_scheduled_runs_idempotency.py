"""scheduled runs idempotency

Revision ID: 0007_sched_runs_idempotency
Revises: 0006_rec_states_summary
Create Date: 2026-03-14 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_sched_runs_idempotency"
down_revision = "0006_rec_states_summary"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    uniques = {unique["name"] for unique in inspector.get_unique_constraints(table_name) if unique.get("name")}
    return indexes | uniques


def upgrade() -> None:
    run_columns = _get_columns("runs")
    if "scheduled_for" not in run_columns:
        op.add_column("runs", sa.Column("scheduled_for", sa.DateTime(), nullable=True))

    run_indexes = _get_indexes("runs")
    if "ix_runs_scheduled_for" not in run_indexes:
        op.create_index("ix_runs_scheduled_for", "runs", ["scheduled_for"])
    if "uq_runs_job_id_scheduled_for" not in run_indexes:
        op.create_index(
            "uq_runs_job_id_scheduled_for",
            "runs",
            ["job_id", "scheduled_for"],
            unique=True,
        )


def downgrade() -> None:
    run_indexes = _get_indexes("runs")
    if "uq_runs_job_id_scheduled_for" in run_indexes:
        op.drop_index("uq_runs_job_id_scheduled_for", table_name="runs")
    if "ix_runs_scheduled_for" in run_indexes:
        op.drop_index("ix_runs_scheduled_for", table_name="runs")

    run_columns = _get_columns("runs")
    if "scheduled_for" in run_columns:
        op.drop_column("runs", "scheduled_for")
