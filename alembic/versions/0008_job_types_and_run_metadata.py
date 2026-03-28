"""job types and run metadata

Revision ID: 0008_job_types_run_metadata
Revises: 0007_sched_runs_idempotency
Create Date: 2026-03-14 14:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_job_types_run_metadata"
down_revision = "0007_sched_runs_idempotency"
branch_labels = None
depends_on = None


DEFAULT_JOB_TYPE = "proposal_generation"


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
    job_columns = _get_columns("jobs")
    if "job_type" not in job_columns:
        op.add_column(
            "jobs",
            sa.Column("job_type", sa.String(length=64), nullable=False, server_default=DEFAULT_JOB_TYPE),
        )
        op.execute(sa.text("UPDATE jobs SET job_type = :job_type WHERE job_type IS NULL OR job_type = ''").bindparams(job_type=DEFAULT_JOB_TYPE))

    job_indexes = _get_indexes("jobs")
    if "ix_jobs_job_type" not in job_indexes:
        op.create_index("ix_jobs_job_type", "jobs", ["job_type"])

    run_columns = _get_columns("runs")
    if "job_type" not in run_columns:
        op.add_column(
            "runs",
            sa.Column("job_type", sa.String(length=64), nullable=False, server_default=DEFAULT_JOB_TYPE),
        )
        op.execute(
            sa.text(
                """
                UPDATE runs
                SET job_type = COALESCE(
                    (SELECT jobs.job_type FROM jobs WHERE jobs.id = runs.job_id),
                    :job_type
                )
                WHERE job_type IS NULL OR job_type = ''
                """
            ).bindparams(job_type=DEFAULT_JOB_TYPE)
        )
    if "summary_json" not in run_columns:
        op.add_column("runs", sa.Column("summary_json", sa.Text(), nullable=False, server_default=""))
    if "artifact_json" not in run_columns:
        op.add_column("runs", sa.Column("artifact_json", sa.Text(), nullable=False, server_default=""))

    run_indexes = _get_indexes("runs")
    if "ix_runs_job_type" not in run_indexes:
        op.create_index("ix_runs_job_type", "runs", ["job_type"])


def downgrade() -> None:
    run_indexes = _get_indexes("runs")
    if "ix_runs_job_type" in run_indexes:
        op.drop_index("ix_runs_job_type", table_name="runs")

    run_columns = _get_columns("runs")
    if "artifact_json" in run_columns:
        op.drop_column("runs", "artifact_json")
    if "summary_json" in run_columns:
        op.drop_column("runs", "summary_json")
    if "job_type" in run_columns:
        op.drop_column("runs", "job_type")

    job_indexes = _get_indexes("jobs")
    if "ix_jobs_job_type" in job_indexes:
        op.drop_index("ix_jobs_job_type", table_name="jobs")

    job_columns = _get_columns("jobs")
    if "job_type" in job_columns:
        op.drop_column("jobs", "job_type")
