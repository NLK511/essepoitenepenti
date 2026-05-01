from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from uuid import uuid4

from trade_proposer_app.domain.models import BrokerOrderExecution, BrokerPosition, RecommendationPlan
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClient, AlpacaPaperClientError
from trade_proposer_app.services.execution_candidates import ExecutionCandidateBuilder
from trade_proposer_app.services.risk_management import BrokerRiskManager, TradeCandidate


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
    TERMINAL_STATUSES = {"win", "loss", "canceled", "rejected", "expired"}
    MARKET_TIMEZONE = ZoneInfo("America/New_York")

    def __init__(
        self,
        settings: SettingsRepository,
        executions: BrokerOrderExecutionRepository,
        client: AlpacaPaperClient | None = None,
        positions: BrokerPositionRepository | None = None,
    ) -> None:
        self.settings = settings
        self.executions = executions
        self.client = client
        self.positions = positions
        self.candidate_builder = ExecutionCandidateBuilder()

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
            candidate_result = self.candidate_builder.build(plan, notional_per_plan=float(config["notional_per_plan"]), run_id=run_id)
            if candidate_result.skip_reason == "non_actionable":
                skip_reasons["non_actionable"] = skip_reasons.get("non_actionable", 0) + 1
                continue
            if candidate_result.candidate is None:
                reason = candidate_result.skip_reason or "invalid_execution_candidate"
                self._bump(skip_reasons, reason)
                ordered_results.append(
                    self._store_skip(
                        plan,
                        run_id=run_id,
                        job_id=job_id,
                        reason=reason,
                        config=config,
                        entry_price=candidate_result.entry_price,
                        stop_loss=candidate_result.stop_loss,
                        take_profit=candidate_result.take_profit,
                    )
                )
                continue

            summary["actionable_plan_count"] = int(summary["actionable_plan_count"]) + 1
            candidate = candidate_result.candidate
            entry_price = candidate.entry_price
            stop_loss = candidate.stop_loss
            take_profit = candidate.take_profit
            quantity = candidate.quantity
            client_order_id = candidate.client_order_id
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
            notional_amount = round(quantity * entry_price, 4)
            risk_assessment = self._risk_manager().assess(TradeCandidate(ticker=plan.ticker, notional_amount=notional_amount))
            if not risk_assessment.allowed:
                risk_reason = "risk_" + "_".join(risk_assessment.reasons or ["blocked"])
                warnings.append(f"{plan.ticker} broker execution blocked by risk manager: {', '.join(risk_assessment.reasons)}")
                self._bump(skip_reasons, risk_reason)
                ordered_results.append(
                    self._store_skip(
                        plan,
                        run_id=run_id,
                        job_id=job_id,
                        reason=risk_reason,
                        config=config,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    )
                )
                continue

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
                notional_amount=notional_amount,
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
        risk_assessment = self._risk_manager().assess(TradeCandidate(ticker=existing.ticker, notional_amount=existing.notional_amount))
        if not risk_assessment.allowed:
            raise ValueError(f"broker order resubmit blocked by risk manager: {', '.join(risk_assessment.reasons)}")

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
        if existing.status in {"filled", "win", "loss"}:
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
        updated = self.executions.update(canceled)
        self._sync_position_from_order(updated)
        return updated

    def refresh_execution(self, execution_id: int) -> BrokerOrderExecution:
        existing = self.executions.get(execution_id)
        if existing.broker_order_id is None:
            raise ValueError("broker order id is missing, so the order cannot be refreshed")
        result = self._ensure_client().get_order(existing.broker_order_id)
        refreshed = self._apply_broker_snapshot(existing, result.payload, broker_status=result.broker_status)
        updated = self.executions.update(refreshed)
        self._sync_position_from_order(updated)
        return updated

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
            created = self.executions.create(candidate)
            self._sync_position_from_order(created)
            return created
        except AlpacaPaperClientError as exc:
            candidate.status = "failed"
            candidate.error_message = str(exc)
            candidate.response_payload = exc.payload
            candidate.submitted_at = datetime.now(timezone.utc)
            created = self.executions.create(candidate)
            self._sync_position_from_order(created)
            return created
        except Exception as exc:  # pragma: no cover - defensive catch for broker/client integration
            candidate.status = "failed"
            candidate.error_message = str(exc)
            candidate.submitted_at = datetime.now(timezone.utc)
            created = self.executions.create(candidate)
            self._sync_position_from_order(created)
            return created

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
    def _client_order_id(plan: RecommendationPlan, *, run_id: int | None) -> str:
        return ExecutionCandidateBuilder.client_order_id(plan, run_id=run_id)

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
                return "win"
            if leg_type in {"stop", "stop_limit", "stop_order"}:
                return "loss"
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
        if status in {"open", "win", "loss"} and filled_at is None:
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

    def _risk_manager(self) -> BrokerRiskManager:
        repository = self._position_repository()
        if repository is None:
            raise ValueError("broker position repository is required for risk management")
        return BrokerRiskManager(self.settings, repository)

    def _position_repository(self) -> BrokerPositionRepository | None:
        if self.positions is not None:
            return self.positions
        session = getattr(self.executions, "session", None)
        if session is None:
            return None
        self.positions = BrokerPositionRepository(session)
        return self.positions

    def _sync_position_from_order(self, order: BrokerOrderExecution) -> BrokerPosition | None:
        if order.id is None or order.broker_order_id is None or order.status == "skipped":
            return None
        repository = self._position_repository()
        if repository is None:
            return None
        position = self._derive_position(order)
        return repository.upsert_by_order_execution(position)

    def _derive_position(self, order: BrokerOrderExecution) -> BrokerPosition:
        payload = order.response_payload if isinstance(order.response_payload, dict) else {}
        entry_avg_price = self._payload_float(payload, "filled_avg_price")
        entry_filled_at = self._broker_timestamp(payload, "filled_at", "filledAt") or order.filled_at
        entry_filled_qty = self._payload_float(payload, "filled_qty") or 0.0
        quantity = int(order.quantity or entry_filled_qty or 0)
        status = "submitted"
        current_quantity = 0
        exit_order_id: str | None = None
        exit_reason: str | None = None
        exit_avg_price: float | None = None
        exit_filled_at: datetime | None = None
        error_message = ""

        broker_status = str(payload.get("status") or order.status or "").strip().lower()
        legs_value = payload.get("legs")
        legs = [leg for leg in legs_value if isinstance(leg, dict)] if isinstance(legs_value, list) else []
        filled_exit_legs: list[tuple[str, dict[str, object]]] = []
        for leg in legs:
            leg_status = str(leg.get("status") or "").strip().lower()
            leg_filled_at = self._broker_timestamp(leg, "filled_at", "filledAt")
            if leg_status != "filled" and leg_filled_at is None:
                continue
            leg_type = str(leg.get("type") or leg.get("order_type") or "").strip().lower()
            if leg_type in {"limit", "limit_order"}:
                filled_exit_legs.append(("take_profit", leg))
            elif leg_type in {"stop", "stop_limit", "stop_order"}:
                filled_exit_legs.append(("stop_loss", leg))

        if len(filled_exit_legs) > 1:
            status = "needs_review"
            error_message = "multiple filled exit legs found"
        elif filled_exit_legs:
            exit_reason, exit_leg = filled_exit_legs[0]
            status = "win" if exit_reason == "take_profit" else "loss"
            exit_order_id = str(exit_leg.get("id")) if exit_leg.get("id") is not None else None
            exit_avg_price = self._payload_float(exit_leg, "filled_avg_price")
            exit_filled_at = self._broker_timestamp(exit_leg, "filled_at", "filledAt")
            current_quantity = 0
        elif entry_filled_at is not None or broker_status == "filled" or entry_filled_qty > 0:
            status = "open"
            current_quantity = quantity
        elif broker_status == "canceled" or order.status == "canceled":
            status = "canceled"
        elif broker_status in {"failed", "rejected", "expired"} or order.status in {"failed", "rejected", "expired"}:
            status = "error"
            error_message = order.error_message or f"broker order {broker_status or order.status}"

        realized_pnl = self._realized_pnl(order=order, quantity=quantity, entry_avg_price=entry_avg_price, exit_avg_price=exit_avg_price)
        realized_return_pct = None
        realized_r_multiple = None
        if realized_pnl is not None and entry_avg_price and quantity > 0:
            basis = abs(entry_avg_price * quantity)
            if basis > 0:
                realized_return_pct = round((realized_pnl / basis) * 100.0, 4)
            if order.stop_loss is not None:
                risk_per_share = abs(entry_avg_price - float(order.stop_loss))
                if risk_per_share > 0:
                    realized_r_multiple = round(realized_pnl / (risk_per_share * quantity), 4)

        return BrokerPosition(
            broker_order_execution_id=order.id or 0,
            broker=order.broker,
            account_mode=order.account_mode,
            recommendation_plan_id=order.recommendation_plan_id,
            recommendation_plan_ticker=order.recommendation_plan_ticker,
            run_id=order.run_id,
            job_id=order.job_id,
            ticker=order.ticker,
            action=order.action,
            side=order.side,
            quantity=quantity,
            current_quantity=current_quantity,
            status=status,
            entry_order_id=order.broker_order_id,
            entry_avg_price=entry_avg_price,
            entry_filled_at=entry_filled_at,
            exit_order_id=exit_order_id,
            exit_reason=exit_reason,
            exit_avg_price=exit_avg_price,
            exit_filled_at=exit_filled_at,
            realized_pnl=realized_pnl,
            realized_return_pct=realized_return_pct,
            realized_r_multiple=realized_r_multiple,
            raw_broker_payload=payload,
            error_message=error_message,
        )

    @staticmethod
    def _payload_float(payload: dict[str, object], key: str) -> float | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _realized_pnl(*, order: BrokerOrderExecution, quantity: int, entry_avg_price: float | None, exit_avg_price: float | None) -> float | None:
        if entry_avg_price is None or exit_avg_price is None or quantity <= 0:
            return None
        if order.action == "short" or order.side == "sell":
            return round((entry_avg_price - exit_avg_price) * quantity, 4)
        return round((exit_avg_price - entry_avg_price) * quantity, 4)

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
