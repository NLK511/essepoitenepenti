"""job last_enqueued_at

Revision ID: 0002_job_last_enqueued_at
Revises: 0001_initial
Create Date: 2026-03-14 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_job_last_enqueued_at"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("last_enqueued_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "last_enqueued_at")
