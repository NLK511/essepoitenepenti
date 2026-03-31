"""add historical replay batch and slice tables

Revision ID: 0017_historical_replay_batches
Revises: 0016_ctx_expires_at
Create Date: 2026-03-24 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_historical_replay_batches"
down_revision = "0016_ctx_expires_at"
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
    if "historical_replay_batches" not in tables:
        op.create_table(
            "historical_replay_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="research"),
            sa.Column("as_of_start", sa.DateTime(), nullable=False),
            sa.Column("as_of_end", sa.DateTime(), nullable=False),
            sa.Column("cadence", sa.String(length=32), nullable=False, server_default="daily"),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("artifact_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_historical_replay_batches_name", "historical_replay_batches", ["name"], unique=True)
        op.create_index("ix_historical_replay_batches_status", "historical_replay_batches", ["status"], unique=False)
        op.create_index("ix_historical_replay_batches_mode", "historical_replay_batches", ["mode"], unique=False)
        op.create_index("ix_historical_replay_batches_as_of_start", "historical_replay_batches", ["as_of_start"], unique=False)
        op.create_index("ix_historical_replay_batches_as_of_end", "historical_replay_batches", ["as_of_end"], unique=False)
        op.create_index("ix_historical_replay_batches_job_id", "historical_replay_batches", ["job_id"], unique=False)

    tables = _get_tables()
    if "historical_replay_slices" not in tables:
        op.create_table(
            "historical_replay_slices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("replay_batch_id", sa.Integer(), sa.ForeignKey("historical_replay_batches.id"), nullable=False),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("input_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("output_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("timing_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("replay_batch_id", "as_of", name="uq_historical_replay_slice_batch_as_of"),
        )
        op.create_index("ix_historical_replay_slices_replay_batch_id", "historical_replay_slices", ["replay_batch_id"], unique=False)
        op.create_index("ix_historical_replay_slices_job_id", "historical_replay_slices", ["job_id"], unique=False)
        op.create_index("ix_historical_replay_slices_run_id", "historical_replay_slices", ["run_id"], unique=False)
        op.create_index("ix_historical_replay_slices_as_of", "historical_replay_slices", ["as_of"], unique=False)
        op.create_index("ix_historical_replay_slices_status", "historical_replay_slices", ["status"], unique=False)


def downgrade() -> None:
    tables = _get_tables()
    if "historical_replay_slices" in tables:
        indexes = _get_indexes("historical_replay_slices")
        for index_name in (
            "ix_historical_replay_slices_status",
            "ix_historical_replay_slices_as_of",
            "ix_historical_replay_slices_run_id",
            "ix_historical_replay_slices_job_id",
            "ix_historical_replay_slices_replay_batch_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="historical_replay_slices")
        op.drop_table("historical_replay_slices")

    tables = _get_tables()
    if "historical_replay_batches" in tables:
        indexes = _get_indexes("historical_replay_batches")
        for index_name in (
            "ix_historical_replay_batches_job_id",
            "ix_historical_replay_batches_as_of_end",
            "ix_historical_replay_batches_as_of_start",
            "ix_historical_replay_batches_mode",
            "ix_historical_replay_batches_status",
            "ix_historical_replay_batches_name",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="historical_replay_batches")
        op.drop_table("historical_replay_batches")
