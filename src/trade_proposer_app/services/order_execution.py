from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from uuid import uuid4

from trade_proposer_app.domain.models import BrokerOrderExecution, RecommendationPlan
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClient, AlpacaPaperClientError


def result_broker_order_id(payload: dict[str, object]) -> str | None:
    value = payload.get("id")
    return str(value) if value is not None else None


@dataclass(slots=True)
class OrderExecutionOutcome:
    summary: dict[str, object]
    orders: list[BrokerOrderExecution] = field(default_factory=list)


@dataclass(slots=True)
class BrokerOrderSyncOutcome:
    summary: dict[str, object]
    orders: list[BrokerOrderExecution] = field(default_factory=list)


class OrderExecutionService:
    TERMINAL_STATUSES = {"closed_win", "closed_loss", "canceled", "rejected", "expired"}
    MARKET_TIMEZONE = ZoneInfo("America/New_York")

    def __init__(
        self,
        settings: SettingsRepository,
        executions: BrokerOrderExecutionRepository,
        client: AlpacaPaperClient | None = None,
    ) -> None:
        self.settings = settings
        self.executions = executions
        self.client = client

    def execute_plans(
        self,
        plans: list[RecommendationPlan],
        *,
        run_id: int | None = None,
        job_id: int | None = None,
    ) -> OrderExecutionOutcome:
        config = self.settings.get_order_execution_config()
        warnings: list[str] = []
        summary: dict[str, object] = {
            "enabled": config["enabled"],
            "broker": config["broker"],
            "account_mode": config["account_mode"],
            "notional_per_plan": config["notional_per_plan"],
            "plan_count": len(plans),
            "actionable_plan_count": 0,
            "submitted_order_count": 0,
            "skipped_order_count": 0,
            "failed_order_count": 0,
            "duplicate_order_count": 0,
            "warnings_found": False,
            "skips": [],
            "orders": [],
        }

        if not config["enabled"]:
            summary["skips"] = [{"reason": "order_execution_disabled", "count": len(plans)}]
            summary["skipped_order_count"] = len(plans)
            return OrderExecutionOutcome(summary=summary, orders=[])

        alpaca_credential = self.settings.get_provider_credential_map().get("alpaca")
        if self.client is None:
            if alpaca_credential is None:
                warnings.append("alpaca provider credential is missing")
                summary["warnings_found"] = True
                summary["skips"] = [{"reason": "missing_alpaca_credential", "count": len(plans)}]
                summary["skipped_order_count"] = len(plans)
                summary["warnings"] = warnings
                return OrderExecutionOutcome(summary=summary, orders=[])
            self.client = AlpacaPaperClient(api_key=alpaca_credential.api_key, api_secret=alpaca_credential.api_secret)

        ordered_results: list[BrokerOrderExecution] = []
        skip_reasons: dict[str, int] = {}

        for plan in plans:
            if plan.id is None:
                self._bump(skip_reasons, "missing_plan_id")
                ordered_results.append(
                    self._store_skip(plan, run_id=run_id, job_id=job_id, reason="missing_plan_id", config=config)
                )
                continue
            if plan.action not in {"long", "short"}:
                skip_reasons["non_actionable"] = skip_reasons.get("non_actionable", 0) + 1
                continue

            summary["actionable_plan_count"] = int(summary["actionable_plan_count"]) + 1

            entry_price = self._entry_reference(plan)
            if entry_price is None or entry_price <= 0:
                self._bump(skip_reasons, "missing_entry_price")
                ordered_results.append(
                    self._store_skip(plan, run_id=run_id, job_id=job_id, reason="missing_entry_price", config=config)
                )
                continue

            stop_loss = plan.stop_loss
            take_profit = plan.take_profit
            if stop_loss is None or take_profit is None:
                self._bump(skip_reasons, "missing_exit_levels")
                ordered_results.append(
                    self._store_skip(plan, run_id=run_id, job_id=job_id, reason="missing_exit_levels", config=config, entry_price=entry_price)
                )
                continue

            if not self._levels_are_directionally_valid(plan.action, entry_price, stop_loss, take_profit):
                self._bump(skip_reasons, "invalid_trade_levels")
                ordered_results.append(
                    self._store_skip(plan, run_id=run_id, job_id=job_id, reason="invalid_trade_levels", config=config, entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit)
                )
                continue

            quantity = int(math.floor(float(config["notional_per_plan"]) / float(entry_price)))
            if quantity < 1:
                self._bump(skip_reasons, "quantity_below_minimum")
                ordered_results.append(
                    self._store_skip(plan, run_id=run_id, job_id=job_id, reason="quantity_below_minimum", config=config, entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit)
                )
                continue

            client_order_id = self._client_order_id(plan, run_id=run_id)
            existing = self.executions.get_by_client_order_id(config["broker"], client_order_id)
            if existing is not None:
                summary["duplicate_order_count"] = int(summary["duplicate_order_count"]) + 1
                ordered_results.append(existing)
                continue

            request_payload = self._build_order_payload(
                ticker=plan.ticker,
                action=plan.action,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quantity=quantity,
                client_order_id=client_order_id,
            )
            stored_order = BrokerOrderExecution(
                broker=str(config["broker"]),
                account_mode=str(config["account_mode"]),
                recommendation_plan_id=plan.id or 0,
                recommendation_plan_ticker=plan.ticker,
                run_id=run_id,
                job_id=job_id,
                ticker=plan.ticker,
                action=plan.action,
                side="buy" if plan.action == "long" else "sell",
                order_type="limit",
                time_in_force="gtc",
                quantity=quantity,
                notional_amount=round(quantity * entry_price, 4),
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                status="queued",
                client_order_id=client_order_id,
                request_payload=request_payload,
            )
            ordered_results.append(self._submit_candidate(stored_order))
            latest_order = ordered_results[-1]
            if latest_order.status in {"accepted", "filled", "submitted"}:
                summary["submitted_order_count"] = int(summary["submitted_order_count"]) + 1
            else:
                summary["failed_order_count"] = int(summary["failed_order_count"]) + 1

        summary["skipped_order_count"] = sum(skip_reasons.values())
        summary["skips"] = [{"reason": reason, "count": count} for reason, count in sorted(skip_reasons.items())]
        summary["orders"] = [order.model_dump(mode="json") for order in ordered_results]
        summary["warnings"] = warnings
        summary["warnings_found"] = bool(warnings or skip_reasons)
        return OrderExecutionOutcome(summary=summary, orders=ordered_results)

    def resubmit_execution(self, execution_id: int) -> BrokerOrderExecution:
        existing = self.executions.get(execution_id)
        if existing.status not in {"failed", "canceled"}:
            raise ValueError("only failed or canceled broker orders can be resubmitted")
        if existing.quantity <= 0:
            raise ValueError("only orders with a positive quantity can be resubmitted")
        if existing.entry_price is None or existing.stop_loss is None or existing.take_profit is None:
            raise ValueError("stored order is missing execution levels and cannot be resubmitted")
        client_order_id = f"{existing.client_order_id}-retry-{uuid4().hex[:8]}"
        request_payload = self._build_order_payload(
            ticker=existing.ticker,
            action=existing.action,
            entry_price=existing.entry_price,
            stop_loss=existing.stop_loss,
            take_profit=existing.take_profit,
            quantity=existing.quantity,
            client_order_id=client_order_id,
        )
        candidate = BrokerOrderExecution(
            broker=existing.broker,
            account_mode=existing.account_mode,
            recommendation_plan_id=existing.recommendation_plan_id,
            recommendation_plan_ticker=existing.recommendation_plan_ticker,
            run_id=existing.run_id,
            job_id=existing.job_id,
            ticker=existing.ticker,
            action=existing.action,
            side=existing.side,
            order_type=existing.order_type,
            time_in_force=existing.time_in_force,
            quantity=existing.quantity,
            notional_amount=existing.notional_amount,
            entry_price=existing.entry_price,
            stop_loss=existing.stop_loss,
            take_profit=existing.take_profit,
            status="queued",
            client_order_id=client_order_id,
            request_payload=request_payload,
        )
        return self._submit_candidate(candidate)

    def cancel_execution(self, execution_id: int) -> BrokerOrderExecution:
        existing = self.executions.get(execution_id)
        if existing.broker_order_id is None:
            raise ValueError("broker order id is missing, so the order cannot be canceled")
        if existing.status == "canceled":
            raise ValueError("broker order is already canceled")
        if existing.status in {"filled", "closed_win", "closed_loss"}:
            raise ValueError("filled or closed orders cannot be canceled")
        client = self._ensure_client()
        result = client.cancel_order(existing.broker_order_id)
        canceled = BrokerOrderExecution(
            id=existing.id,
            broker=existing.broker,
            account_mode=existing.account_mode,
            recommendation_plan_id=existing.recommendation_plan_id,
            recommendation_plan_ticker=existing.recommendation_plan_ticker,
            run_id=existing.run_id,
            job_id=existing.job_id,
            ticker=existing.ticker,
            action=existing.action,
            side=existing.side,
            order_type=existing.order_type,
            time_in_force=existing.time_in_force,
            quantity=existing.quantity,
            notional_amount=existing.notional_amount,
            entry_price=existing.entry_price,
            stop_loss=existing.stop_loss,
            take_profit=existing.take_profit,
            status="canceled",
            broker_order_id=existing.broker_order_id,
            client_order_id=existing.client_order_id,
            submitted_at=existing.submitted_at,
            filled_at=existing.filled_at,
            canceled_at=datetime.now(timezone.utc),
            request_payload=existing.request_payload,
            response_payload=result.payload,
            error_message="",
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        return self.executions.update(canceled)

    def refresh_execution(self, execution_id: int) -> BrokerOrderExecution:
        existing = self.executions.get(execution_id)
        if existing.broker_order_id is None:
            raise ValueError("broker order id is missing, so the order cannot be refreshed")
        result = self._ensure_client().get_order(existing.broker_order_id)
        refreshed = self._apply_broker_snapshot(existing, result.payload, broker_status=result.broker_status)
        return self.executions.update(refreshed)

    def sync_open_executions(self, *, limit: int = 200) -> BrokerOrderSyncOutcome:
        orders = self.executions.list_all(limit=limit)
        synced_orders: list[BrokerOrderExecution] = []
        skipped = 0
        failed = 0
        warnings: list[str] = []
        for order in orders:
            if order.broker_order_id is None or order.status in self.TERMINAL_STATUSES | {"skipped"}:
                skipped += 1
                continue
            try:
                synced_orders.append(self.refresh_execution(order.id or 0))
            except AlpacaPaperClientError as exc:
                failed += 1
                warnings.append(f"broker order {order.id} sync failed: {exc}")
            except ValueError as exc:
                failed += 1
                warnings.append(f"broker order {order.id} sync failed: {exc}")
        summary = {
            "requested_count": len(orders),
            "synced_count": len(synced_orders),
            "skipped_count": skipped,
            "failed_count": failed,
            "warnings_found": bool(warnings),
            "warnings": warnings,
            "orders": [order.model_dump(mode="json") for order in synced_orders],
        }
        return BrokerOrderSyncOutcome(summary=summary, orders=synced_orders)

    def _submit_candidate(self, candidate: BrokerOrderExecution) -> BrokerOrderExecution:
        self._ensure_client()
        try:
            result = self.client.submit_order(candidate.request_payload)  # type: ignore[union-attr]
            candidate.broker_order_id = result.broker_order_id
            candidate.status = result.broker_status or "submitted"
            candidate.submitted_at = datetime.now(timezone.utc)
            candidate.response_payload = result.payload
            candidate.error_message = ""
            return self.executions.create(candidate)
        except AlpacaPaperClientError as exc:
            candidate.status = "failed"
            candidate.error_message = str(exc)
            candidate.response_payload = exc.payload
            candidate.submitted_at = datetime.now(timezone.utc)
            return self.executions.create(candidate)
        except Exception as exc:  # pragma: no cover - defensive catch for broker/client integration
            candidate.status = "failed"
            candidate.error_message = str(exc)
            candidate.submitted_at = datetime.now(timezone.utc)
            return self.executions.create(candidate)

    def _ensure_client(self) -> AlpacaPaperClient:
        if self.client is not None:
            return self.client
        alpaca_credential = self.settings.get_provider_credential_map().get("alpaca")
        if alpaca_credential is None:
            raise ValueError("alpaca provider credential is missing")
        self.client = AlpacaPaperClient(api_key=alpaca_credential.api_key, api_secret=alpaca_credential.api_secret)
        return self.client

    @staticmethod
    def _bump(counter: dict[str, int], reason: str) -> None:
        counter[reason] = counter.get(reason, 0) + 1

    @staticmethod
    def _entry_reference(plan: RecommendationPlan) -> float | None:
        if plan.entry_price_low is not None and plan.entry_price_high is not None:
            return (float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0
        if plan.entry_price_low is not None:
            return float(plan.entry_price_low)
        if plan.entry_price_high is not None:
            return float(plan.entry_price_high)
        return None

    @staticmethod
    def _levels_are_directionally_valid(action: str, entry_price: float, stop_loss: float, take_profit: float) -> bool:
        if action == "long":
            return stop_loss < entry_price < take_profit
        if action == "short":
            return take_profit < entry_price < stop_loss
        return False

    @staticmethod
    def _client_order_id(plan: RecommendationPlan, *, run_id: int | None) -> str:
        run_part = f"run-{run_id}" if run_id is not None else "run-none"
        plan_part = f"plan-{plan.id or 'new'}"
        return f"tp-{run_part}-{plan_part}-{plan.ticker.lower()}"

    @staticmethod
    def _build_order_payload(
        *,
        ticker: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: int,
        client_order_id: str,
    ) -> dict[str, object]:
        return {
            "symbol": ticker,
            "qty": quantity,
            "side": "buy" if action == "long" else "sell",
            "type": "limit",
            "time_in_force": "gtc",
            "limit_price": OrderExecutionService._normalize_price(entry_price),
            "order_class": "bracket",
            "take_profit": {"limit_price": OrderExecutionService._normalize_price(take_profit)},
            "stop_loss": {"stop_price": OrderExecutionService._normalize_price(stop_loss)},
            "client_order_id": client_order_id,
        }

    @staticmethod
    def _normalize_price(price: float) -> float:
        value = Decimal(str(price))
        if abs(value) >= 1:
            quantum = Decimal("0.01")
        else:
            quantum = Decimal("0.0001")
        return float(value.quantize(quantum, rounding=ROUND_HALF_UP))

    @staticmethod
    def _parse_datetime(value: object | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            normalized = normalized.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        return None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_market_open(now: datetime | None = None) -> bool:
        current = (now or OrderExecutionService._now()).astimezone(OrderExecutionService.MARKET_TIMEZONE)
        if current.weekday() >= 5:
            return False
        market_open = current.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = current.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= current <= market_close

    @staticmethod
    def _broker_timestamp(payload: dict[str, object], *keys: str) -> datetime | None:
        for key in keys:
            parsed = OrderExecutionService._parse_datetime(payload.get(key))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _derive_bracket_status(payload: dict[str, object], *, fallback_status: str) -> str:
        legs_value = payload.get("legs")
        legs = [leg for leg in legs_value if isinstance(leg, dict)] if isinstance(legs_value, list) else []
        for leg in legs:
            leg_status = str(leg.get("status") or "").strip().lower()
            leg_filled_at = OrderExecutionService._broker_timestamp(leg, "filled_at", "filledAt")
            if leg_status != "filled" and leg_filled_at is None:
                continue
            leg_type = str(leg.get("type") or leg.get("order_type") or "").strip().lower()
            if leg_type in {"limit", "limit_order"}:
                return "closed_win"
            if leg_type in {"stop", "stop_limit", "stop_order"}:
                return "closed_loss"
        if fallback_status == "filled":
            return "open"
        return fallback_status

    def _apply_broker_snapshot(
        self,
        existing: BrokerOrderExecution,
        payload: dict[str, object],
        *,
        broker_status: str | None = None,
    ) -> BrokerOrderExecution:
        broker_parent_status = (broker_status or str(payload.get("status") or existing.status) or existing.status).strip().lower()
        status = self._derive_bracket_status(payload, fallback_status=broker_parent_status)
        now = self._now()
        filled_at = self._broker_timestamp(payload, "filled_at", "filledAt") or existing.filled_at
        canceled_at = self._broker_timestamp(payload, "canceled_at", "canceledAt") or existing.canceled_at
        if status in {"open", "closed_win", "closed_loss"} and filled_at is None:
            filled_at = now
        if status == "canceled" and canceled_at is None:
            canceled_at = now
        return BrokerOrderExecution(
            id=existing.id,
            broker=existing.broker,
            account_mode=existing.account_mode,
            recommendation_plan_id=existing.recommendation_plan_id,
            recommendation_plan_ticker=existing.recommendation_plan_ticker,
            run_id=existing.run_id,
            job_id=existing.job_id,
            ticker=existing.ticker,
            action=existing.action,
            side=existing.side,
            order_type=existing.order_type,
            time_in_force=existing.time_in_force,
            quantity=existing.quantity,
            notional_amount=existing.notional_amount,
            entry_price=existing.entry_price,
            stop_loss=existing.stop_loss,
            take_profit=existing.take_profit,
            status=status,
            broker_order_id=existing.broker_order_id or result_broker_order_id(payload) or existing.broker_order_id,
            client_order_id=existing.client_order_id,
            submitted_at=self._broker_timestamp(payload, "submitted_at", "submittedAt") or existing.submitted_at,
            filled_at=filled_at,
            canceled_at=canceled_at,
            request_payload=existing.request_payload,
            response_payload=payload,
            error_message="",
            created_at=existing.created_at,
            updated_at=now,
        )

    def _store_skip(
        self,
        plan: RecommendationPlan,
        *,
        run_id: int | None,
        job_id: int | None,
        reason: str,
        config: dict[str, object],
        entry_price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> BrokerOrderExecution:
        execution = BrokerOrderExecution(
            broker=str(config["broker"]),
            account_mode=str(config["account_mode"]),
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            run_id=run_id,
            job_id=job_id,
            ticker=plan.ticker,
            action=plan.action,
            side="buy" if plan.action == "long" else "sell",
            order_type="limit",
            time_in_force="gtc",
            quantity=0,
            notional_amount=0.0,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="skipped",
            client_order_id=self._client_order_id(plan, run_id=run_id),
            error_message=reason,
            request_payload={"reason": reason},
            response_payload={},
        )
        return self.executions.create(execution)
