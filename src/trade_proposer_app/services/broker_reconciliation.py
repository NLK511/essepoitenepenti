from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerOrderExecution, BrokerPosition
from trade_proposer_app.domain.statuses import TERMINAL_EXECUTION_STATUSES
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import (
    BrokerReconciliationSnapshotRepository,
)
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import (
    BrokerAdapter,
    BrokerAdapterResultStatus,
    redacted_payload,
)
from trade_proposer_app.services.brokers.factory import BrokerAdapterFactory
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
            outcome = self._sync_open_executions(limit=limit)
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
                    "broker_order_sync_last_count": str(
                        int(outcome.summary.get("synced_count", 0) or 0)
                    ),
                    "broker_order_sync_last_error": "",
                }
        )
        return outcome

    def _sync_open_executions(self, *, limit: int):
        legacy_service = create_order_execution_service(self.session)
        adapter_factory = BrokerAdapterFactory(settings=self.settings, accounts=self.accounts)
        orders = self.orders.list_active(limit=limit)
        enabled_account_ids = {
            account.broker_account_id for account in self.accounts.list_enabled()
        }
        synced_orders: list[BrokerOrderExecution] = []
        skipped = 0
        failed = 0
        warnings: list[str] = []
        etoro_demo_adapters: dict[str, BrokerAdapter] = {}
        for order in orders:
            if order.broker_order_id is None or order.status in TERMINAL_EXECUTION_STATUSES:
                skipped += 1
                continue
            if order.broker_account_id and order.broker_account_id not in enabled_account_ids:
                skipped += 1
                continue
            try:
                if order.broker == "etoro" and order.account_mode == "demo":
                    adapter = adapter_factory.for_account_id(order.broker_account_id)
                    etoro_demo_adapters[order.broker_account_id] = adapter
                    synced_orders.append(self._sync_etoro_demo_order(order, adapter))
                else:
                    synced_orders.append(legacy_service.refresh_execution(order.id or 0))
            except Exception as exc:
                failed += 1
                warnings.append(f"broker order {order.id} sync failed: {exc}")
        for position in self.positions.list_filtered(
            broker="etoro",
            account_mode="demo",
            limit=limit,
        ):
            if position.broker_account_id not in etoro_demo_adapters:
                try:
                    etoro_demo_adapters[
                        position.broker_account_id
                    ] = adapter_factory.for_account_id(position.broker_account_id)
                except Exception as exc:
                    failed += 1
                    warnings.append(
                        f"eToro demo portfolio sync for {position.broker_account_id} failed: {exc}"
                    )
        position_summaries: dict[str, dict[str, object]] = {}
        for broker_account_id, adapter in etoro_demo_adapters.items():
            try:
                position_summaries[
                    broker_account_id
                ] = self._sync_etoro_demo_positions_from_portfolio(broker_account_id, adapter)
            except Exception as exc:
                failed += 1
                warnings.append(
                    f"eToro demo position sync for {broker_account_id} failed: {exc}"
                )
        summary = {
            "requested_count": len(orders),
            "synced_count": len(synced_orders),
            "skipped_count": skipped,
            "failed_count": failed,
            "warnings_found": bool(warnings),
            "warnings": warnings,
            "orders": [order.model_dump(mode="json") for order in synced_orders],
            "etoro_demo_position_sync": position_summaries,
        }
        return type("BrokerOrderSyncOutcome", (), {"summary": summary, "orders": synced_orders})()

    def _sync_etoro_demo_order(
        self, order: BrokerOrderExecution, adapter: BrokerAdapter
    ) -> BrokerOrderExecution:
        result = adapter.lookup_order(order_id=order.broker_order_id)
        if not result.is_success:
            detail = result.message or result.broker_status or result.status
            raise ValueError(
                f"eToro demo order lookup failed: {detail}"
            )
        payload = result.payload or {}
        status_name = self._etoro_status_name(payload)
        position_rows = self._list(payload.get("positionExecutions"))
        now = datetime.now(UTC)
        order.status = self._etoro_order_status(status_name, has_position=bool(position_rows))
        order.response_payload = redacted_payload(payload)  # type: ignore[assignment]
        if position_rows and order.filled_at is None:
            order.filled_at = self._etoro_execution_time(position_rows[0]) or now
        updated = self.orders.update(order)
        for row in position_rows:
            self._upsert_etoro_demo_position(updated, row)
        return updated

    def _upsert_etoro_demo_position(
        self, order: BrokerOrderExecution, row: dict[str, object]
    ) -> BrokerPosition:
        opening = row.get("openingData") if isinstance(row.get("openingData"), dict) else {}
        position_id = row.get("positionId") or row.get("positionID")
        remaining_units = self._float(row.get("remainingUnits") or row.get("remainingContracts"))
        opened_units = (
            self._float(opening.get("units") or opening.get("contracts")) or remaining_units
        )
        position_state = str(row.get("state") or "").strip().lower()
        current_units = (
            remaining_units if position_state == "open" and remaining_units is not None else 0.0
        )
        position = BrokerPosition(
            broker_order_execution_id=order.id or 0,
            broker_account_id=order.broker_account_id,
            broker=order.broker,
            account_mode=order.account_mode,
            recommendation_plan_id=order.recommendation_plan_id,
            recommendation_plan_ticker=order.recommendation_plan_ticker,
            run_id=order.run_id,
            job_id=order.job_id,
            ticker=order.ticker,
            action=order.action,
            side=order.side,
            quantity=1 if current_units > 0 else 0,
            current_quantity=1 if current_units > 0 else 0,
            unit_quantity=opened_units,
            current_unit_quantity=current_units,
            status=self._etoro_position_status(position_state),
            entry_order_id=str(position_id or order.broker_order_id or ""),
            entry_avg_price=self._float(opening.get("avgPrice")),
            entry_filled_at=self._parse_etoro_datetime(opening.get("executionTime"))
            or self._parse_etoro_datetime(opening.get("openTime"))
            or order.filled_at,
            stop_loss_order_price=self._float(row.get("stopLossRate")),
            take_profit_order_price=self._float(row.get("takeProfitRate")),
            protective_orders_verified_at=datetime.now(UTC),
            protective_orders_source="etoro_demo_order_lookup",
            raw_broker_payload={
                "position_execution": redacted_payload(row),
                "etoro_opened_units": opened_units,
                "etoro_remaining_units": current_units,
            },
        )
        return self.positions.upsert_by_order_execution(position)

    def _sync_etoro_demo_positions_from_portfolio(
        self, broker_account_id: str, adapter: BrokerAdapter
    ) -> dict[str, object]:
        portfolio = adapter.get_open_positions()
        if not portfolio.is_success:
            return {
                "status": "failed",
                "message": portfolio.message,
                "payload": portfolio.payload,
                "positions_checked": 0,
            }
        open_rows = portfolio.items
        open_by_position_id = {
            str(position_id): row
            for row in open_rows
            if (position_id := self._etoro_position_id(row)) is not None
        }
        local_positions = self.positions.list_filtered(
            broker_account_id=broker_account_id,
            broker="etoro",
            account_mode="demo",
            limit=1000,
        )
        history = adapter.get_trade_history()
        history_available = history.status == BrokerAdapterResultStatus.SUCCESS
        updated_count = 0
        closed_without_confirmed_pnl = 0
        close_order_synced = 0
        for position in local_positions:
            if position.exit_order_id:
                updated = self._sync_etoro_demo_close_order(position, adapter)
                if updated.id is not None:
                    position = updated
                    close_order_synced += 1
            if position.status in {"win", "loss", "rejected", "failed", "canceled", "skipped"}:
                continue
            entry_id = str(position.entry_order_id or "").strip()
            if not entry_id:
                continue
            if entry_id in open_by_position_id:
                row = open_by_position_id[entry_id]
                current_units = self._etoro_position_units(row)
                payload = dict(position.raw_broker_payload or {})
                payload["portfolio_position"] = redacted_payload(row)
                position.status = "open"
                if current_units is not None:
                    position.current_quantity = 1 if current_units > 0 else 0
                    position.current_unit_quantity = current_units
                position.raw_broker_payload = payload
                self.positions.update(position)
                updated_count += 1
                continue
            if position.status in {"submitted", "open", "closing", "needs_review"}:
                payload = dict(position.raw_broker_payload or {})
                payload["portfolio_absence_reconciled_at"] = datetime.now(UTC).isoformat()
                payload["trade_history_available"] = history_available
                position.status = "needs_review"
                position.current_quantity = 0
                position.current_unit_quantity = 0.0
                position.error_message = self._append_evidence_message(
                    position.error_message,
                    "etoro_portfolio_absent_without_confirmed_pnl",
                )
                position.raw_broker_payload = payload
                self.positions.update(position)
                closed_without_confirmed_pnl += 1
                updated_count += 1
        return {
            "status": "synced",
            "positions_checked": len(local_positions),
            "portfolio_open_positions": len(open_by_position_id),
            "updated_count": updated_count,
            "close_order_synced": close_order_synced,
            "closed_without_confirmed_pnl": closed_without_confirmed_pnl,
            "history_available": history_available,
            "history_message": "" if history_available else history.message,
        }

    def _sync_etoro_demo_close_order(
        self, position: BrokerPosition, adapter: BrokerAdapter
    ) -> BrokerPosition:
        if not position.exit_order_id:
            return position
        result = adapter.lookup_close_order(position.exit_order_id)
        if not result.is_success:
            if result.status == BrokerAdapterResultStatus.NOT_FOUND:
                return position
            raise ValueError(f"eToro demo close-order lookup failed: {result.message}")
        payload = result.payload or {}
        position_rows = [
            row
            for row in self._list(payload.get("positions"))
            if str(row.get("positionID") or row.get("positionId") or "")
            == str(position.entry_order_id)
        ] or self._list(payload.get("positions"))
        row = position_rows[0] if position_rows else {}
        exit_price = self._float(
            row.get("rate")
            or row.get("closeRate")
            or row.get("avgPrice")
            or payload.get("closeRate")
            or payload.get("avgPrice")
        )
        exit_time = self._parse_etoro_datetime(
            row.get("occurred")
            or row.get("executionTime")
            or payload.get("requestOccurred")
            or payload.get("executionTime")
        )
        closed_units = self._float(
            row.get("units") or row.get("closedUnits") or payload.get("units")
        )
        realized_pnl = self._etoro_realized_pnl(payload, row)
        raw_payload = dict(position.raw_broker_payload or {})
        raw_payload["close_order_lookup"] = redacted_payload(payload)
        if exit_price is not None:
            position.exit_avg_price = exit_price
        if exit_time is not None:
            position.exit_filled_at = exit_time
        position.current_quantity = 0
        position.current_unit_quantity = 0.0
        if closed_units is not None and position.unit_quantity is None:
            position.unit_quantity = closed_units
        if realized_pnl is not None:
            position.realized_pnl = realized_pnl
            position.status = (
                "win" if realized_pnl > 0 else "loss" if realized_pnl < 0 else "needs_review"
            )
        else:
            position.status = "needs_review"
        position.raw_broker_payload = raw_payload
        return self.positions.update(position)

    @staticmethod
    def _etoro_status_name(payload: dict[str, object]) -> str:
        status = payload.get("status")
        if isinstance(status, dict):
            return str(status.get("name") or status.get("id") or "").strip()
        return str(status or "").strip()

    @staticmethod
    def _etoro_order_status(status_name: str, *, has_position: bool) -> str:
        normalized = status_name.strip().lower()
        if has_position or normalized == "filled":
            return "filled"
        if normalized in {"waitingformarket", "pending", "accepted"}:
            return "accepted"
        if normalized in {"canceled", "cancelled"}:
            return "canceled"
        if normalized in {"rejected", "failed"}:
            return "rejected"
        return "submitted"

    @staticmethod
    def _etoro_position_status(position_state: str) -> str:
        if position_state == "open":
            return "open"
        if position_state in {"closed", "closing"}:
            return "needs_review"
        return "submitted"

    @staticmethod
    def _append_evidence_message(existing: str | None, message: str) -> str:
        if not existing:
            return message
        if message in existing:
            return existing
        return f"{existing}; {message}"

    @classmethod
    def _etoro_execution_time(cls, row: dict[str, object]) -> datetime | None:
        opening = row.get("openingData") if isinstance(row.get("openingData"), dict) else {}
        return cls._parse_etoro_datetime(opening.get("executionTime")) or cls._parse_etoro_datetime(
            opening.get("openTime")
        )

    @staticmethod
    def _parse_etoro_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _list(value: object) -> list[dict[str, object]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @classmethod
    def _etoro_position_id(cls, row: dict[str, object]) -> str | None:
        value = row.get("positionID") or row.get("positionId") or row.get("id")
        return str(value) if value is not None else None

    @classmethod
    def _etoro_position_units(cls, row: dict[str, object]) -> float | None:
        return cls._float(
            row.get("remainingUnits")
            or row.get("currentUnits")
            or row.get("units")
            or row.get("remainingContracts")
        )

    @classmethod
    def _etoro_realized_pnl(
        cls, payload: dict[str, object], row: dict[str, object]
    ) -> float | None:
        for source in (row, payload):
            value = (
                source.get("netProfit")
                or source.get("profit")
                or source.get("realizedPnl")
                or source.get("realizedPnL")
                or source.get("realized_pnl")
            )
            parsed = cls._float(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _float(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
