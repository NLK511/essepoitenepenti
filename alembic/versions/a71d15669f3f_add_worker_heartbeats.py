"""add_worker_heartbeats

Revision ID: a71d15669f3f
Revises: 0015_drop_legacy_recs
Create Date: 2026-03-24 10:05:20.918364
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a71d15669f3f'
down_revision = '0015_drop_legacy_recs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(120), primary_key=True),
        sa.Column("hostname", sa.String(120), nullable=False),
        sa.Column("pid", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime, nullable=False, index=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("active_run_id", sa.Integer, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime, nullable=True))
        batch_op.create_index(batch_op.f("ix_runs_worker_id"), ["worker_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_lease_expires_at"), ["lease_expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_lease_expires_at"))
        batch_op.drop_index(batch_op.f("ix_runs_worker_id"))
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("worker_id")
    op.drop_table("worker_heartbeats")
