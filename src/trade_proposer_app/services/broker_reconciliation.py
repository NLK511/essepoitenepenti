from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import (
    BrokerReconciliationSnapshotRepository,
)
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import redacted_payload
from trade_proposer_app.services.builders import create_order_execution_service
from trade_proposer_app.services.risk_management import BrokerRiskManager
from trade_proposer_app.services.settings_domains import SettingsDomainService


class BrokerReconciliationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.orders = BrokerOrderExecutionRepository(session)
        self.positions = BrokerPositionRepository(session)
        self.accounts = BrokerAccountRepository(session)
        self.account_safety = BrokerAccountSafetyRepository(session)
        self.settings = SettingsRepository(session)
        self.settings_domains = SettingsDomainService(repository=self.settings)
        self.halt_events = RiskHaltEventRepository(session)
        self.snapshots = BrokerReconciliationSnapshotRepository(session)

    def build_workbench(
        self,
        *,
        run_id: int | None = None,
        broker_account_id: str | None = None,
        broker: str | None = None,
        account_mode: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        has_filters = any([run_id is not None, broker_account_id, broker, account_mode, status])
        listed_orders = (
            self.orders.list_filtered(
                run_id=run_id,
                broker_account_id=broker_account_id,
                broker=broker,
                account_mode=account_mode,
                status=status,
                limit=limit,
            )
            if has_filters
            else self.orders.list_all(limit=limit)
        )
        listed_positions = (
            self.positions.list_filtered(
                run_id=run_id,
                broker_account_id=broker_account_id,
                broker=broker,
                account_mode=account_mode,
                status=status,
                limit=limit,
            )
            if has_filters
            else self.positions.list_all(limit=limit)
        )
        risk = BrokerRiskManager(self.settings, self.positions, self.halt_events).assess()
        halt_events = self.halt_events.list_latest(limit=10)
        snapshots = self.snapshots.list_latest(run_id=run_id, limit=limit)
        return {
            "broker_orders": [order.model_dump(mode="json") for order in listed_orders],
            "broker_positions": [position.model_dump(mode="json") for position in listed_positions],
            "broker_accounts": self._broker_account_payloads(),
            "global_broker_risk_caps": self.settings.get_global_broker_risk_caps(),
            "global_live_summary": self._global_live_summary(),
            "risk": risk.model_dump(mode="json"),
            "risk_halt_events": [event.model_dump(mode="json") for event in halt_events],
            "broker_reconciliation_snapshots": [
                snapshot.model_dump(mode="json") for snapshot in snapshots
            ],
            "broker_sync_state": self.settings_domains.broker_sync_state().to_dict(),
            "counts": {
                "broker_orders": len(listed_orders),
                "broker_positions": len(listed_positions),
                "broker_accounts": len(self.accounts.list_all()),
                "broker_reconciliation_snapshots": len(snapshots),
            },
        }

    def _broker_account_payloads(self) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for account in self.accounts.list_accounts_redacted():
            values = account.model_dump(mode="json")
            values["mode_badge"] = account.account_mode.upper()
            values["has_credentials"] = bool(
                self.accounts.get_credentials(account.broker_account_id)
            )
            values["validation_evidence"] = redacted_payload(account.validation_evidence)
            values["risk_settings"] = redacted_payload(account.risk_settings)
            values["circuit_breaker"] = self.account_safety.get_circuit_breaker(
                account.broker_account_id
            ).model_dump(mode="json")
            drawdown = self.account_safety.get_drawdown_state(account.broker_account_id)
            values["drawdown"] = drawdown.model_dump(mode="json") if drawdown is not None else None
            payloads.append(redacted_payload(values))  # type: ignore[arg-type]
        return payloads

    def _global_live_summary(self) -> dict[str, object]:
        enabled_live_accounts = [
            account
            for account in self.accounts.list_all()
            if account.enabled and account.account_mode == "live"
        ]
        terminal_statuses = {
            "skipped",
            "failed",
            "rejected",
            "canceled",
            "cancelled",
            "closed",
            "win",
            "loss",
            "needs_review",
        }
        active_live_orders = [
            order
            for order in self.orders.list_all(limit=5000)
            if order.account_mode == "live" and order.status not in terminal_statuses
        ]
        today = datetime.now(UTC).date()
        return {
            "enabled_live_account_count": len(enabled_live_accounts),
            "enabled_live_broker_accounts": [
                account.broker_account_id for account in enabled_live_accounts
            ],
            "active_live_open_notional_usd": round(
                sum(float(order.notional_amount or 0.0) for order in active_live_orders), 4
            ),
            "live_order_count_today": sum(
                1
                for order in active_live_orders
                if order.created_at.astimezone(UTC).date() == today
            ),
        }

    def sync_open_orders(self, *, limit: int = 200):
        completed_at = datetime.now(UTC)
        try:
            outcome = create_order_execution_service(self.session).sync_open_executions(limit=limit)
        except Exception as exc:
            self.settings.set_settings(
                {
                    "broker_order_sync_last_at": completed_at.isoformat(),
                    "broker_order_sync_last_error": str(exc),
                }
            )
            raise
        self.settings.set_settings(
            {
                "broker_order_sync_last_at": completed_at.isoformat(),
                "broker_order_sync_last_count": str(int(outcome.summary.get("synced_count", 0) or 0)),
                "broker_order_sync_last_error": "",
            }
        )
        return outcome
