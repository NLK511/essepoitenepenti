from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from trade_proposer_app.domain.models import BrokerOrderExecution, RecommendationPlan
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClient, AlpacaPaperClientError


@dataclass(slots=True)
class OrderExecutionOutcome:
    summary: dict[str, object]
    orders: list[BrokerOrderExecution] = field(default_factory=list)


class OrderExecutionService:
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
                plan=plan,
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
        request_payload = dict(existing.request_payload)
        if "symbol" not in request_payload or "qty" not in request_payload or "limit_price" not in request_payload:
            raise ValueError("stored request payload is incomplete and cannot be resubmitted")
        client_order_id = f"{existing.client_order_id}-retry-{uuid4().hex[:8]}"
        request_payload["client_order_id"] = client_order_id
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
        if existing.status == "filled":
            raise ValueError("filled orders cannot be canceled")
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
        plan: RecommendationPlan,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: int,
        client_order_id: str,
    ) -> dict[str, object]:
        return {
            "symbol": plan.ticker,
            "qty": quantity,
            "side": "buy" if plan.action == "long" else "sell",
            "type": "limit",
            "time_in_force": "gtc",
            "limit_price": round(float(entry_price), 4),
            "order_class": "bracket",
            "take_profit": {"limit_price": round(float(take_profit), 4)},
            "stop_loss": {"stop_price": round(float(stop_loss), 4)},
            "client_order_id": client_order_id,
        }

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
