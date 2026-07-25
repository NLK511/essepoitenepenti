"""Add fractional broker position unit fields."""

import sqlalchemy as sa

from alembic import op

revision = "0055_fractional_position_units"
down_revision = "0054_candidate_plan_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broker_positions", sa.Column("unit_quantity", sa.Float(), nullable=True))
    op.add_column("broker_positions", sa.Column("current_unit_quantity", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("broker_positions", "current_unit_quantity")
    op.drop_column("broker_positions", "unit_quantity")
