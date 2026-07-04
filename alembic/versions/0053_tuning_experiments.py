"""Add tuning experiments table."""

from alembic import op
import sqlalchemy as sa


revision = "0053_tuning_experiments"
down_revision = "0052_runtime_processes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tuning_experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("universe_json", sa.Text(), nullable=False),
        sa.Column("windows_json", sa.Text(), nullable=False),
        sa.Column("discovery_settings_json", sa.Text(), nullable=False),
        sa.Column("replay_settings_json", sa.Text(), nullable=False),
        sa.Column("objective", sa.String(length=64), nullable=False),
        sa.Column("baseline_json", sa.Text(), nullable=False),
        sa.Column("promotion_target", sa.String(length=64), nullable=False),
        sa.Column("advanced_settings_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tuning_experiments_name", "tuning_experiments", ["name"])
    op.create_index("ix_tuning_experiments_status", "tuning_experiments", ["status"])
    op.create_index("ix_tuning_experiments_objective", "tuning_experiments", ["objective"])
    op.create_index("ix_tuning_experiments_promotion_target", "tuning_experiments", ["promotion_target"])
    op.create_index("ix_tuning_experiments_archived_at", "tuning_experiments", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_tuning_experiments_archived_at", table_name="tuning_experiments")
    op.drop_index("ix_tuning_experiments_promotion_target", table_name="tuning_experiments")
    op.drop_index("ix_tuning_experiments_objective", table_name="tuning_experiments")
    op.drop_index("ix_tuning_experiments_status", table_name="tuning_experiments")
    op.drop_index("ix_tuning_experiments_name", table_name="tuning_experiments")
    op.drop_table("tuning_experiments")
