"""Add runtime process heartbeat table."""

from alembic import op
import sqlalchemy as sa


revision = "0052_runtime_processes"
down_revision = "0051_news_ingested_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_processes",
        sa.Column("instance_id", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("hostname", sa.String(length=120), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("graceful_shutdown_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_index("ix_runtime_processes_role", "runtime_processes", ["role"])
    op.create_index("ix_runtime_processes_status", "runtime_processes", ["status"])
    op.create_index("ix_runtime_processes_started_at", "runtime_processes", ["started_at"])
    op.create_index("ix_runtime_processes_last_heartbeat_at", "runtime_processes", ["last_heartbeat_at"])
    op.create_index("ix_runtime_processes_graceful_shutdown_at", "runtime_processes", ["graceful_shutdown_at"])
    op.create_index("ix_runtime_processes_role_status", "runtime_processes", ["role", "status"])


def downgrade() -> None:
    op.drop_index("ix_runtime_processes_role_status", table_name="runtime_processes")
    op.drop_index("ix_runtime_processes_graceful_shutdown_at", table_name="runtime_processes")
    op.drop_index("ix_runtime_processes_last_heartbeat_at", table_name="runtime_processes")
    op.drop_index("ix_runtime_processes_started_at", table_name="runtime_processes")
    op.drop_index("ix_runtime_processes_status", table_name="runtime_processes")
    op.drop_index("ix_runtime_processes_role", table_name="runtime_processes")
    op.drop_table("runtime_processes")
