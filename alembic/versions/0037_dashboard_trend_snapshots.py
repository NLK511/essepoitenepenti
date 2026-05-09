"""dashboard_trend_snapshots

Revision ID: 6d2a0c9d1f31
Revises: a71d15669f3f
Create Date: 2026-05-09 08:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


revision = "6d2a0c9d1f31"
down_revision = "a71d15669f3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "dashboard_trend_snapshots" in _tables():
        return
    op.create_table(
        "dashboard_trend_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("snapshot_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("snapshot_date", name="uq_dashboard_trend_snapshots_snapshot_date"),
    )
    op.create_index("ix_dashboard_trend_snapshots_snapshot_date", "dashboard_trend_snapshots", ["snapshot_date"], unique=False)
    op.create_index("ix_dashboard_trend_snapshots_computed_at", "dashboard_trend_snapshots", ["computed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dashboard_trend_snapshots_computed_at", table_name="dashboard_trend_snapshots")
    op.drop_index("ix_dashboard_trend_snapshots_snapshot_date", table_name="dashboard_trend_snapshots")
    op.drop_table("dashboard_trend_snapshots")
