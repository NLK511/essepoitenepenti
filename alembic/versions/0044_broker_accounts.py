"""add broker account model

Revision ID: 0044_broker_accounts
Revises: 0043_fund_snapshots
Create Date: 2026-06-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0044_broker_accounts"
down_revision = "0043_fund_snapshots"
branch_labels = None
depends_on = None


DEFAULT_ACCOUNT_ID = "alpaca-paper-default"


def upgrade() -> None:
    op.create_table(
        "broker_accounts",
        sa.Column("broker_account_id", sa.String(length=120), primary_key=True),
        sa.Column("broker", sa.String(length=64), nullable=False, server_default="alpaca"),
        sa.Column("account_mode", sa.String(length=32), nullable=False, server_default="paper"),
        sa.Column("account_label", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "autonomous_execution_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("manual_actions_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("credential_reference", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("symbol_allowlist_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("symbol_denylist_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("supported_actions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("supported_instruments_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("supported_order_types_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notional_cap_usd", sa.Float(), nullable=True),
        sa.Column("max_open_positions", sa.Integer(), nullable=True),
        sa.Column("max_open_notional_usd", sa.Float(), nullable=True),
        sa.Column("max_position_notional_usd", sa.Float(), nullable=True),
        sa.Column("max_same_ticker_open_positions", sa.Integer(), nullable=True),
        sa.Column("halt_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halt_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "validation_status",
            sa.String(length=64),
            nullable=False,
            server_default="not_validated",
        ),
        sa.Column("validation_evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("risk_settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_broker_accounts_broker", "broker_accounts", ["broker"])
    op.create_index("ix_broker_accounts_account_mode", "broker_accounts", ["account_mode"])
    op.create_index("ix_broker_accounts_account_label", "broker_accounts", ["account_label"])
    op.create_index("ix_broker_accounts_enabled", "broker_accounts", ["enabled"])
    op.create_index(
        "ix_broker_accounts_autonomous_execution_enabled",
        "broker_accounts",
        ["autonomous_execution_enabled"],
    )
    op.create_index(
        "ix_broker_accounts_manual_actions_enabled", "broker_accounts", ["manual_actions_enabled"]
    )
    op.create_index("ix_broker_accounts_halt_enabled", "broker_accounts", ["halt_enabled"])
    op.create_index(
        "ix_broker_accounts_validation_status", "broker_accounts", ["validation_status"]
    )

    op.create_table(
        "broker_account_credentials",
        sa.Column(
            "broker_account_id",
            sa.String(length=120),
            sa.ForeignKey("broker_accounts.broker_account_id"),
            primary_key=True,
        ),
        sa.Column("encrypted_credentials_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    default_actions_json = '["long", "short"]'
    default_order_types_json = '["limit", "market"]'
    op.execute(
        sa.text(
            "INSERT INTO broker_accounts ("
            "broker_account_id, broker, account_mode, account_label, enabled, "
            "autonomous_execution_enabled, manual_actions_enabled, credential_reference, "
            "supported_actions_json, supported_order_types_json, created_at, updated_at"
            ") VALUES ("
            ":id, 'alpaca', 'paper', :id, false, false, true, :ref, :actions, :order_types, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
            ")"
        ).bindparams(
            id=DEFAULT_ACCOUNT_ID,
            ref=f"broker_account:{DEFAULT_ACCOUNT_ID}",
            actions=default_actions_json,
            order_types=default_order_types_json,
        )
    )

    with op.batch_alter_table("broker_order_executions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "broker_account_id",
                sa.String(length=120),
                nullable=False,
                server_default=DEFAULT_ACCOUNT_ID,
            )
        )
    op.create_index(
        "ix_broker_order_executions_broker_account_id",
        "broker_order_executions",
        ["broker_account_id"],
    )

    with op.batch_alter_table("broker_positions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "broker_account_id",
                sa.String(length=120),
                nullable=False,
                server_default=DEFAULT_ACCOUNT_ID,
            )
        )
    op.create_index(
        "ix_broker_positions_broker_account_id", "broker_positions", ["broker_account_id"]
    )

    with op.batch_alter_table("broker_reconciliation_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "broker_account_id",
                sa.String(length=120),
                nullable=False,
                server_default=DEFAULT_ACCOUNT_ID,
            )
        )
    op.create_index(
        "ix_broker_reconciliation_snapshots_broker_account_id",
        "broker_reconciliation_snapshots",
        ["broker_account_id"],
    )

    with op.batch_alter_table("broker_steering_decisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "broker_account_id",
                sa.String(length=120),
                nullable=False,
                server_default=DEFAULT_ACCOUNT_ID,
            )
        )
    op.create_index(
        "ix_broker_steering_decisions_broker_account_id",
        "broker_steering_decisions",
        ["broker_account_id"],
    )

    with op.batch_alter_table("risk_halt_events") as batch_op:
        batch_op.add_column(sa.Column("broker_account_id", sa.String(length=120), nullable=True))
    op.create_index(
        "ix_risk_halt_events_broker_account_id", "risk_halt_events", ["broker_account_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_risk_halt_events_broker_account_id", table_name="risk_halt_events")
    with op.batch_alter_table("risk_halt_events") as batch_op:
        batch_op.drop_column("broker_account_id")

    op.drop_index(
        "ix_broker_steering_decisions_broker_account_id", table_name="broker_steering_decisions"
    )
    with op.batch_alter_table("broker_steering_decisions") as batch_op:
        batch_op.drop_column("broker_account_id")

    op.drop_index(
        "ix_broker_reconciliation_snapshots_broker_account_id",
        table_name="broker_reconciliation_snapshots",
    )
    with op.batch_alter_table("broker_reconciliation_snapshots") as batch_op:
        batch_op.drop_column("broker_account_id")

    op.drop_index("ix_broker_positions_broker_account_id", table_name="broker_positions")
    with op.batch_alter_table("broker_positions") as batch_op:
        batch_op.drop_column("broker_account_id")

    op.drop_index(
        "ix_broker_order_executions_broker_account_id", table_name="broker_order_executions"
    )
    with op.batch_alter_table("broker_order_executions") as batch_op:
        batch_op.drop_column("broker_account_id")

    op.drop_table("broker_account_credentials")
    op.drop_table("broker_accounts")
