from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from trade_proposer_app.domain.models import AccountRiskState, BrokerPosition
from trade_proposer_app.domain.statuses import BROKER_RESOLVED_POSITION_STATUSES, BrokerPositionStatus, TradeOutcome
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.settings_mutations import SettingsMutationService

OPEN_STATUSES = {BrokerPositionStatus.SUBMITTED.value, BrokerPositionStatus.OPEN.value}
CLOSED_STATUSES = BROKER_RESOLVED_POSITION_STATUSES


@dataclass(slots=True)
class TradeCandidate:
    ticker: str
    notional_amount: float


@dataclass(slots=True)
class LiveBrokerSnapshot:
    account: dict[str, object] | None = None
    open_orders: list[dict[str, object]] = field(default_factory=list)
    open_positions: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BrokerRiskManager:
    def __init__(
        self,
        settings: SettingsRepository,
        positions: BrokerPositionRepository,
        halt_events: RiskHaltEventRepository | None = None,
    ) -> None:
        self.settings = settings
        self.settings_mutations = SettingsMutationService(repository=settings)
        self.positions = positions
        self.halt_events = halt_events

    def assess(self, candidate: TradeCandidate | None = None, *, now: datetime | None = None, live_broker_snapshot: LiveBrokerSnapshot | None = None) -> AccountRiskState:
        config = SettingsDomainService(repository=self.settings).risk_settings().risk_management
        all_positions = self.positions.list_all(limit=1000)
        metrics = self._metrics(all_positions, now=now or datetime.now(timezone.utc), live_broker_snapshot=live_broker_snapshot)
        reasons: list[str] = []

        enabled = bool(config["enabled"])
        halt_enabled = bool(config["halt_enabled"])
        if halt_enabled:
            reasons.append("manual_halt_active")

        if enabled:
            projected_open_positions = int(metrics["open_position_count"])
            projected_open_notional = float(metrics["open_notional_usd"])
            projected_same_ticker = 0
            if candidate is not None:
                projected_open_positions += 1
                projected_open_notional += max(0.0, float(candidate.notional_amount))
                projected_same_ticker = int(metrics["open_ticker_counts"].get(candidate.ticker.upper(), 0)) + 1  # type: ignore[index,union-attr]
                max_position_notional = float(config["max_position_notional_usd"])
                if max_position_notional > 0 and float(candidate.notional_amount) > max_position_notional:
                    reasons.append("position_notional_limit_exceeded")
                broker_buying_power = metrics.get("broker_buying_power_usd")
                if broker_buying_power is not None and float(candidate.notional_amount) > float(broker_buying_power):
                    reasons.append("broker_buying_power_insufficient")

            max_open_positions = int(config["max_open_positions"])
            max_open_notional = float(config["max_open_notional_usd"])
            max_same_ticker = int(config["max_same_ticker_open_positions"])
            max_daily_loss = abs(float(config["max_daily_realized_loss_usd"]))
            max_consecutive_losses = int(config["max_consecutive_losses"])
            if max_open_positions > 0 and projected_open_positions > max_open_positions:
                reasons.append("open_position_limit_exceeded")
            if max_open_notional > 0 and projected_open_notional > max_open_notional:
                reasons.append("open_notional_limit_exceeded")
            if candidate is not None and max_same_ticker > 0 and projected_same_ticker > max_same_ticker:
                reasons.append("same_ticker_open_position_limit_exceeded")
            if max_daily_loss > 0 and float(metrics["today_realized_pnl_usd"]) <= -max_daily_loss:
                reasons.append("daily_realized_loss_limit_exceeded")
            if max_consecutive_losses > 0 and int(metrics["today_consecutive_losses"]) >= max_consecutive_losses:
                reasons.append("consecutive_loss_limit_exceeded")
            if metrics.get("broker_drift_severity") in {"uncertain", "material"}:
                reasons.append(f"broker_reconciliation_{metrics['broker_drift_severity']}")

            metrics["projected_open_position_count"] = projected_open_positions
            metrics["projected_open_notional_usd"] = round(projected_open_notional, 4)
        else:
            metrics["projected_open_position_count"] = metrics["open_position_count"]
            metrics["projected_open_notional_usd"] = metrics["open_notional_usd"]

        return AccountRiskState(
            allowed=not reasons,
            enabled=enabled,
            halt_enabled=halt_enabled,
            halt_reason=str(config.get("halt_reason") or ""),
            reasons=reasons,
            metrics=metrics,
            config=config,
        )

    def halt(self, reason: str) -> AccountRiskState:
        previous = bool(SettingsDomainService(repository=self.settings).risk_settings().risk_management["halt_enabled"])
        self.settings_mutations.set_risk_halt(enabled=True, reason=reason or "manual halt")
        if self.halt_events is not None:
            self.halt_events.create(
                action="halt",
                reason=reason or "manual halt",
                previous_halt_enabled=previous,
                new_halt_enabled=True,
            )
        return self.assess()

    def resume(self) -> AccountRiskState:
        previous = bool(SettingsDomainService(repository=self.settings).risk_settings().risk_management["halt_enabled"])
        self.settings_mutations.set_risk_halt(enabled=False, reason="")
        if self.halt_events is not None:
            self.halt_events.create(
                action="resume",
                reason="",
                previous_halt_enabled=previous,
                new_halt_enabled=False,
            )
        return self.assess()

    def _metrics(self, positions: list[BrokerPosition], *, now: datetime, live_broker_snapshot: LiveBrokerSnapshot | None = None) -> dict[str, object]:
        today = now.astimezone(timezone.utc).date()
        open_positions = [position for position in positions if position.status in OPEN_STATUSES]
        closed_today = [
            position
            for position in positions
            if position.status in CLOSED_STATUSES
            and (position.exit_filled_at or position.updated_at).astimezone(timezone.utc).date() == today
        ]
        open_ticker_counts: dict[str, int] = {}
        open_notional = 0.0
        app_open_ticker_counts: dict[str, int] = {}
        for position in open_positions:
            ticker = position.ticker.upper()
            app_open_ticker_counts[ticker] = app_open_ticker_counts.get(ticker, 0) + 1
            open_ticker_counts[ticker] = open_ticker_counts.get(ticker, 0) + 1
            if position.entry_avg_price is not None:
                open_notional += abs(float(position.entry_avg_price) * float(position.current_quantity or position.quantity))
            else:
                intended = position.raw_broker_payload.get("notional_amount") if isinstance(position.raw_broker_payload, dict) else None
                try:
                    open_notional += abs(float(intended)) if intended is not None else 0.0
                except (TypeError, ValueError):
                    pass

        realized_pnl = sum(float(position.realized_pnl or 0.0) for position in closed_today)
        wins = sum(1 for position in closed_today if position.status == TradeOutcome.WIN.value)
        losses = sum(1 for position in closed_today if position.status == TradeOutcome.LOSS.value)
        consecutive_losses = 0
        for position in sorted(closed_today, key=lambda item: item.exit_filled_at or item.updated_at, reverse=True):
            if position.status != TradeOutcome.LOSS.value:
                break
            consecutive_losses += 1

        broker_metrics = self._live_broker_metrics(live_broker_snapshot)
        broker_open_position_count = int(broker_metrics.get("broker_open_position_count", 0))
        broker_open_order_count = int(broker_metrics.get("broker_open_order_count", 0))
        broker_open_notional = float(broker_metrics.get("broker_open_notional_usd", 0.0))
        broker_ticker_counts = broker_metrics.get("broker_open_ticker_counts", {})
        if isinstance(broker_ticker_counts, dict):
            for ticker, count in broker_ticker_counts.items():
                open_ticker_counts[str(ticker).upper()] = open_ticker_counts.get(str(ticker).upper(), 0) + int(count)

        drift = self._broker_drift(snapshot=live_broker_snapshot, app_open_ticker_counts=app_open_ticker_counts)
        metrics: dict[str, object] = {
            "open_position_count": len(open_positions) + broker_open_position_count + broker_open_order_count,
            "app_open_position_count": len(open_positions),
            "broker_open_position_count": broker_open_position_count,
            "broker_open_order_count": broker_open_order_count,
            "open_notional_usd": round(open_notional + broker_open_notional, 4),
            "app_open_notional_usd": round(open_notional, 4),
            "broker_open_notional_usd": round(broker_open_notional, 4),
            "open_ticker_counts": open_ticker_counts,
            "app_open_ticker_counts": app_open_ticker_counts,
            "broker_drift_severity": drift["severity"],
            "broker_drift_reasons": drift["reasons"],
            "today_realized_pnl_usd": round(realized_pnl, 4),
            "today_win_count": wins,
            "today_loss_count": losses,
            "today_consecutive_losses": consecutive_losses,
        }
        metrics.update(broker_metrics)
        return metrics

    @classmethod
    def _broker_drift(cls, *, snapshot: LiveBrokerSnapshot | None, app_open_ticker_counts: dict[str, int]) -> dict[str, object]:
        if snapshot is None:
            return {"severity": "not_checked", "reasons": []}
        reasons: list[str] = []
        if snapshot.warnings:
            reasons.append("broker_snapshot_warnings")
        broker_ticker_counts: dict[str, int] = {}
        for item in [*snapshot.open_positions, *snapshot.open_orders]:
            ticker = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
            if ticker:
                broker_ticker_counts[ticker] = broker_ticker_counts.get(ticker, 0) + 1
        for ticker, broker_count in broker_ticker_counts.items():
            if broker_count > int(app_open_ticker_counts.get(ticker, 0)):
                reasons.append(f"untracked_broker_exposure:{ticker}")
        severity = "material" if any(reason.startswith("untracked_broker_exposure:") for reason in reasons) else "uncertain" if reasons else "ok"
        return {"severity": severity, "reasons": reasons}

    @classmethod
    def _live_broker_metrics(cls, snapshot: LiveBrokerSnapshot | None) -> dict[str, object]:
        if snapshot is None:
            return {
                "broker_snapshot_available": False,
                "broker_snapshot_warnings": [],
            }
        open_ticker_counts: dict[str, int] = {}
        open_notional = 0.0
        for position in snapshot.open_positions:
            ticker = str(position.get("symbol") or position.get("ticker") or "").strip().upper()
            if ticker:
                open_ticker_counts[ticker] = open_ticker_counts.get(ticker, 0) + 1
            open_notional += cls._broker_notional(position, quantity_keys=("qty", "quantity"), price_keys=("market_value", "avg_entry_price", "current_price"))
        for order in snapshot.open_orders:
            ticker = str(order.get("symbol") or order.get("ticker") or "").strip().upper()
            if ticker:
                open_ticker_counts[ticker] = open_ticker_counts.get(ticker, 0) + 1
            open_notional += cls._broker_notional(order, quantity_keys=("qty", "quantity"), price_keys=("notional", "limit_price", "stop_price"))
        buying_power = cls._optional_float((snapshot.account or {}).get("buying_power"))
        return {
            "broker_snapshot_available": True,
            "broker_snapshot_warnings": list(snapshot.warnings),
            "broker_buying_power_usd": buying_power,
            "broker_open_position_count": len(snapshot.open_positions),
            "broker_open_order_count": len(snapshot.open_orders),
            "broker_open_ticker_counts": open_ticker_counts,
            "broker_open_notional_usd": round(open_notional, 4),
        }

    @classmethod
    def _broker_notional(cls, payload: dict[str, object], *, quantity_keys: tuple[str, ...], price_keys: tuple[str, ...]) -> float:
        for key in price_keys:
            value = cls._optional_float(payload.get(key))
            if value is None:
                continue
            if key in {"market_value", "notional"}:
                return abs(value)
            quantity = next((cls._optional_float(payload.get(quantity_key)) for quantity_key in quantity_keys if cls._optional_float(payload.get(quantity_key)) is not None), None)
            return abs(value * quantity) if quantity is not None else 0.0
        return 0.0

    @staticmethod
    def _optional_float(value: object) -> float | None:
        try:
            return float(value) if value is not None and str(value).strip() != "" else None
        except (TypeError, ValueError):
            return None
