"""Deprecate Alpaca broker defaults in favor of eToro demo."""

import sqlalchemy as sa

from alembic import op

revision = "0056_deprecate_alpaca_defaults"
down_revision = "0055_fractional_position_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE app_settings "
            "SET value = 'etoro' "
            "WHERE key = 'order_execution_broker' AND lower(value) = 'alpaca'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE app_settings "
            "SET value = 'demo' "
            "WHERE key = 'order_execution_account_mode' AND lower(value) = 'paper'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE broker_accounts "
            "SET enabled = false, autonomous_execution_enabled = false, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE broker = 'alpaca' AND (enabled = true OR autonomous_execution_enabled = true)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM broker_accounts "
            "WHERE broker_account_id = 'alpaca-paper-default' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM broker_order_executions "
            "  WHERE broker_order_executions.broker_account_id = broker_accounts.broker_account_id"
            ") "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM broker_positions "
            "  WHERE broker_positions.broker_account_id = broker_accounts.broker_account_id"
            ") "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM broker_account_credentials "
            "  WHERE broker_account_credentials.broker_account_id = "
            "broker_accounts.broker_account_id"
            ") "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM broker_circuit_breakers "
            "  WHERE broker_circuit_breakers.broker_account_id = broker_accounts.broker_account_id"
            ") "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM broker_drawdown_states "
            "  WHERE broker_drawdown_states.broker_account_id = broker_accounts.broker_account_id"
            ")"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE app_settings "
            "SET value = 'alpaca' "
            "WHERE key = 'order_execution_broker' AND lower(value) = 'etoro'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE app_settings "
            "SET value = 'paper' "
            "WHERE key = 'order_execution_account_mode' AND lower(value) = 'demo'"
        )
    )
