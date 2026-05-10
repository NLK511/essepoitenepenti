"""add broker reconciliation snapshots

Revision ID: 0041_broker_recon_snapshots
Revises: 0040_observability_events
Create Date: 2026-05-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0041_broker_recon_snapshots"
down_revision = "0040_observability_events"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "broker_reconciliation_snapshots" in _tables():
        return
    op.create_table(
        "broker_reconciliation_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker", sa.String(length=64), nullable=False, server_default="alpaca"),
        sa.Column("account_mode", sa.String(length=32), nullable=False, server_default="paper"),
        sa.Column("snapshot_type", sa.String(length=64), nullable=False, server_default="pre_submit"),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("broker_order_execution_id", sa.Integer(), sa.ForeignKey("broker_order_executions.id"), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("account_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("open_orders_payload_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("open_positions_payload_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("drift_severity", sa.String(length=32), nullable=False, server_default="not_evaluated"),
        sa.Column("drift_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in [
        "broker",
        "account_mode",
        "snapshot_type",
        "run_id",
        "job_id",
        "broker_order_execution_id",
        "ticker",
        "drift_severity",
        "created_at",
    ]:
        op.create_index(f"ix_broker_reconciliation_snapshots_{column}", "broker_reconciliation_snapshots", [column])


def downgrade() -> None:
    if "broker_reconciliation_snapshots" not in _tables():
        return
    for column in [
        "created_at",
        "drift_severity",
        "ticker",
        "broker_order_execution_id",
        "job_id",
        "run_id",
        "snapshot_type",
        "account_mode",
        "broker",
    ]:
        op.drop_index(f"ix_broker_reconciliation_snapshots_{column}", table_name="broker_reconciliation_snapshots")
    op.drop_table("broker_reconciliation_snapshots")
