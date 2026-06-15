from __future__ import annotations

from datetime import datetime, timezone

from trade_proposer_app.domain.models import BrokerPosition
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository


class MultiBrokerReconciliationService:
    def __init__(
        self,
        *,
        positions: BrokerPositionRepository,
        safety: BrokerAccountSafetyRepository | None = None,
    ) -> None:
        self.positions = positions
        self.safety = safety

    def apply_portfolio_snapshot(
        self,
        *,
        broker_account_id: str,
        open_positions: list[dict[str, object]],
        closed_trades: list[dict[str, object]],
        snapshot_fresh: bool = True,
    ) -> list[BrokerPosition]:
        app_positions = [
            position
            for position in self.positions.list_all(limit=5000)
            if position.broker_account_id == broker_account_id
            and position.status in {"submitted", "open", "closing"}
        ]
        updated: list[BrokerPosition] = []
        if not snapshot_fresh:
            self._activate_breaker(broker_account_id, reason="broker_snapshot_stale")
        for position in app_positions:
            open_row = self._find_symbol_row(open_positions, position.ticker)
            close_rows = self._find_symbol_rows(closed_trades, position.ticker)
            closed_qty = sum(
                self._quantity(row, "closedQuantity", "closed_quantity", "quantity")
                for row in close_rows
            )
            realized_pnl = sum(
                self._float(
                    row.get("netProfit") or row.get("net_profit") or row.get("realized_pnl")
                )
                or 0.0
                for row in close_rows
            )
            if open_row is not None:
                remaining_qty = self._quantity(open_row, "quantity", "qty", "units")
                if remaining_qty <= 0:
                    remaining_qty = max(0, int(position.quantity) - int(closed_qty))
                position.current_quantity = int(remaining_qty)
                position.status = "open"
                if close_rows:
                    position.realized_pnl = realized_pnl
                position.raw_broker_payload = {
                    "open_position": open_row,
                    "closed_trades": close_rows,
                }
                updated.append(self.positions.update(position))
                continue
            if close_rows and closed_qty >= int(position.quantity or 0):
                position.current_quantity = 0
                position.realized_pnl = realized_pnl
                position.exit_filled_at = datetime.now(timezone.utc)
                position.status = (
                    "win" if realized_pnl > 0 else "loss" if realized_pnl < 0 else "needs_review"
                )
                position.raw_broker_payload = {"closed_trades": close_rows}
                updated.append(self.positions.update(position))
                continue
            if close_rows and 0 < closed_qty < int(position.quantity or 0):
                position.current_quantity = max(0, int(position.quantity) - int(closed_qty))
                position.status = "open"
                position.realized_pnl = realized_pnl
                position.raw_broker_payload = {"closed_trades": close_rows}
                updated.append(self.positions.update(position))
                continue
            position.status = "needs_review"
            position.error_message = "broker_position_missing_from_open_and_closed_evidence"
            position.raw_broker_payload = {
                "open_positions": open_positions,
                "closed_trades": closed_trades,
            }
            updated.append(self.positions.update(position))
            self._activate_breaker(
                broker_account_id,
                reason="broker_reconciliation_uncertainty",
            )
        return updated

    def _activate_breaker(self, broker_account_id: str, *, reason: str) -> None:
        if self.safety is not None:
            self.safety.activate_circuit_breaker(broker_account_id, reason=reason)

    @classmethod
    def _find_symbol_row(
        cls, rows: list[dict[str, object]], ticker: str
    ) -> dict[str, object] | None:
        matches = cls._find_symbol_rows(rows, ticker)
        return matches[0] if matches else None

    @staticmethod
    def _find_symbol_rows(rows: list[dict[str, object]], ticker: str) -> list[dict[str, object]]:
        normalized = ticker.upper()
        return [
            row
            for row in rows
            if str(row.get("symbol") or row.get("ticker") or "").strip().upper() == normalized
        ]

    @classmethod
    def _quantity(cls, row: dict[str, object], *keys: str) -> int:
        for key in keys:
            value = cls._float(row.get(key))
            if value is not None:
                return int(value)
        return 0

    @staticmethod
    def _float(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
