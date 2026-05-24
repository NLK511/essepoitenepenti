"""merge broker steering and reconciliation heads

Revision ID: 0042_merge_broker_heads
Revises: 0041_broker_steering_decisions, 0041_broker_recon_snapshots
Create Date: 2026-05-10
"""

from alembic import op


revision = "0042_merge_broker_heads"
down_revision = ("0041_broker_steering_decisions", "0041_broker_recon_snapshots")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
