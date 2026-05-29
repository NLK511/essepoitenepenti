from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerOrderExecution, BrokerPosition, RecommendationPlan
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import BrokerReconciliationSnapshotRepository
from trade_proposer_app.repositories.broker_steering_decisions import BrokerSteeringDecisionRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.broker_position_steering import BrokerSteeringConfig, BrokerSteeringDecision, BrokerSteeringEngine, BrokerSteeringState


@dataclass(frozen=True)
class BrokerSteeringRunSummary:
    total_candidates: int
    decisions: dict[str, int]
    execution_status: str


class BrokerSteeringStateBuilder:
    PENDING_STATUSES = {"queued", "submitted", "accepted", "open", "new", "partially_filled"}
    POSITION_STATUSES = {"submitted", "open"}

    def __init__(
        self,
        session: Session,
        *,
        price_lookup: Callable[[str], float | None] | None = None,
    ) -> None:
        self.session = session
        self.price_lookup = price_lookup or self._default_price_lookup
        self.plans = RecommendationPlanRepository(session)
        self.orders = BrokerOrderExecutionRepository(session)
        self.positions = BrokerPositionRepository(session)
        self.snapshots = BrokerReconciliationSnapshotRepository(session)
        self.market_data = HistoricalMarketDataRepository(session)
        self._price_cache: dict[str, float | None] = {}

    def list_states(self, *, limit: int = 200, now: datetime | None = None) -> list[BrokerSteeringState]:
        order_map = self._active_orders_by_plan_id(limit=limit)
        position_map = self._active_positions_by_plan_id(limit=limit)
        plan_ids = sorted({*order_map.keys(), *position_map.keys()})
        states: list[BrokerSteeringState] = []
        for plan_id in plan_ids:
            try:
                plan = self.plans.get_plan(plan_id)
            except ValueError:
                continue
            order = order_map.get(plan_id)
            position = position_map.get(plan_id)
            states.append(self._build_state(plan, order=order, position=position, now=now))
        return states

    def _active_orders_by_plan_id(self, *, limit: int) -> dict[int, BrokerOrderExecution]:
        orders = [order for order in self.orders.list_active(limit=limit) if order.recommendation_plan_id is not None]
        return {order.recommendation_plan_id: order for order in orders}

    def _active_positions_by_plan_id(self, *, limit: int) -> dict[int, BrokerPosition]:
        positions = [position for position in self.positions.list_active(limit=limit) if position.recommendation_plan_id is not None]
        return {position.recommendation_plan_id: position for position in positions}

    def _default_price_lookup(self, ticker: str) -> float | None:
        normalized = ticker.strip().upper()
        if not normalized:
            return None
        if normalized in self._price_cache:
            return self._price_cache[normalized]
        bars = self.market_data.list_bars(ticker=normalized, timeframe="1d", limit=1)
        price = bars[-1].close_price if bars else None
        self._price_cache[normalized] = price
        return price

    def _build_state(
        self,
        plan: RecommendationPlan,
        *,
        order: BrokerOrderExecution | None,
        position: BrokerPosition | None,
        now: datetime | None,
    ) -> BrokerSteeringState:
        is_position = position is not None
        current_price = self.price_lookup(plan.ticker)
        entry_price = plan.entry_price_high if plan.entry_price_high is not None else plan.entry_price_low
        if plan.entry_price_low is not None and plan.entry_price_high is not None:
            entry_price = (float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0
        current_stop_loss = order.stop_loss if order is not None else plan.stop_loss
        current_take_profit = order.take_profit if order is not None else plan.take_profit
        broker_order_status = order.status if order is not None else None
        broker_position_status = position.status if position is not None else None
        broker_side = position.side if position is not None else (order.side if order is not None else None)
        direction = self._direction_for_plan(plan)
        expiration_at = None
        if plan.computed_at and plan.holding_period_days is not None:
            expiration_at = plan.computed_at + timedelta(days=max(1, int(plan.holding_period_days)))
        broker_reconciliation_healthy = self._broker_reconciliation_healthy(plan.ticker)
        return BrokerSteeringState(
            recommendation_plan_id=plan.id or 0,
            ticker=plan.ticker,
            direction=direction,
            broker_order_id=order.id if order is not None else None,
            broker_position_id=position.id if position is not None else None,
            current_price=current_price,
            entry_price=entry_price,
            original_stop_loss=plan.stop_loss,
            original_take_profit=plan.take_profit,
            current_stop_loss=current_stop_loss,
            current_take_profit=current_take_profit,
            confidence_percent=plan.confidence_percent,
            calibrated_confidence_percent=self._calibrated_confidence(plan),
            actionability=plan.action,
            analysis_direction=plan.action if direction in {"long", "short"} else None,
            severe_negative_news=self._has_severe_negative_news(plan),
            price_chase_percent=None,
            volatility_percent=None,
            has_pending_order=order is not None and not is_position,
            has_open_position=is_position,
            broker_order_status=broker_order_status,
            broker_position_status=broker_position_status,
            broker_quantity=position.current_quantity if position is not None else (order.quantity if order is not None else None),
            broker_side=broker_side,
            broker_ownership_known=bool(order is not None or position is not None),
            broker_reconciliation_healthy=broker_reconciliation_healthy,
            linked_exit_orders_missing=bool(position is not None and not position.exit_order_id and position.current_quantity > 0),
            expiration_at=expiration_at,
            now=now,
        )

    @staticmethod
    def _direction_for_plan(plan: RecommendationPlan) -> str:
        action = str(plan.action or "").strip().lower()
        if action in {"short", "sell"}:
            return "short"
        if action in {"long", "buy"}:
            return "long"
        return "unknown"

    def _broker_reconciliation_healthy(self, ticker: str) -> bool:
        snapshots = self.snapshots.list_latest_for_ticker(ticker, limit=1)
        if not snapshots:
            return False
        latest = snapshots[0]
        if latest.warnings:
            return False
        return str(latest.drift_severity or "").strip().lower() == "ok"

    @staticmethod
    def _has_severe_negative_news(plan: RecommendationPlan) -> bool:
        for warning in plan.warnings:
            normalized = str(warning or "").strip().lower().replace(" ", "_")
            if "severe_negative_news" in normalized or "severe_negative_event" in normalized:
                return True
        return False

    @staticmethod
    def _calibrated_confidence(plan: RecommendationPlan) -> float | None:
        review = plan.signal_breakdown.get("calibration_review") if hasattr(plan.signal_breakdown, "get") else None
        if isinstance(review, dict):
            value = review.get("calibrated_confidence_percent")
            if isinstance(value, (int, float)):
                return float(value)
        return None


class BrokerSteeringService:
    def __init__(
        self,
        session: Session,
        *,
        engine: BrokerSteeringEngine | None = None,
        builder: BrokerSteeringStateBuilder | None = None,
        decision_repository: BrokerSteeringDecisionRepository | None = None,
        observability: ObservabilityEventRepository | None = None,
        settings_repository: SettingsRepository | None = None,
        order_execution=None,
    ) -> None:
        self.session = session
        self.engine = engine or BrokerSteeringEngine()
        self.builder = builder or BrokerSteeringStateBuilder(session)
        self.decision_repository = decision_repository or BrokerSteeringDecisionRepository(session)
        self.observability = observability or ObservabilityEventRepository(session)
        self.settings_repository = settings_repository or SettingsRepository(session)
        self.order_execution = order_execution
        if self.order_execution is None:
            try:
                from trade_proposer_app.services.builders import create_order_execution_service

                self.order_execution = create_order_execution_service(session)
            except Exception:
                self.order_execution = None
        self.settings = self.settings_repository.get_steering_config()

    def run_once(
        self,
        *,
        limit: int = 200,
        now: datetime | None = None,
        run_id: int | None = None,
        job_id: int | None = None,
        correlation_id: str | None = None,
    ) -> BrokerSteeringRunSummary:
        normalized_now = now or datetime.now(timezone.utc)
        config = BrokerSteeringConfig(**self.settings)
        states = self.builder.list_states(limit=limit, now=normalized_now)
        reviewed_sample_counts = self._reviewed_sample_counts() if config.enabled and not config.dry_run else None
        self.observability.record(
            event_type="steering_run_started",
            message="Broker steering run started",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={"candidate_count": len(states), "dry_run": config.dry_run, "enabled": config.enabled},
        )
        counts: dict[str, int] = {}
        execution_status = "dry_run" if config.dry_run else "submitted"
        for state in states:
            decision = self.engine.evaluate(state, config)
            counts[decision.decision] = counts.get(decision.decision, 0) + 1
            saved_decision = self.decision_repository.create(
                recommendation_plan_id=decision.recommendation_plan_id,
                ticker=decision.ticker,
                decision=decision,
                broker_order_id=decision.broker_order_id,
                broker_position_id=decision.broker_position_id,
                execution_status=execution_status,
                executed_at=normalized_now,
            )
            self.observability.record(
                event_type="steering_decision_created",
                message=decision.human_summary,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                payload={"decision": decision.decision, "ticker": decision.ticker, "reason_codes": decision.reason_codes, "recommendation_plan_id": decision.recommendation_plan_id},
            )
            if config.enabled and not config.dry_run:
                self._execute_decision_if_supported(
                    saved_decision_id=int(saved_decision.get("id") or 0),
                    state=state,
                    decision=decision,
                    reviewed_sample_counts=reviewed_sample_counts or {},
                    run_id=run_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    normalized_now=normalized_now,
                )
        self.observability.record(
            event_type="steering_run_completed",
            message="Broker steering run completed",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={"candidate_count": len(states), "decisions": counts, "dry_run": config.dry_run},
        )
        return BrokerSteeringRunSummary(total_candidates=len(states), decisions=counts, execution_status=execution_status)

    def _execute_decision_if_supported(
        self,
        *,
        saved_decision_id: int,
        state: BrokerSteeringState,
        decision: BrokerSteeringDecision,
        reviewed_sample_counts: dict[str, int],
        run_id: int | None,
        job_id: int | None,
        correlation_id: str | None,
        normalized_now: datetime,
    ) -> None:
        if self.order_execution is None:
            self.decision_repository.update_execution_result(
                saved_decision_id,
                execution_status="blocked",
                executed_at=normalized_now,
                error_message="live_order_execution_service_unavailable",
            )
            self.observability.record(
                event_type="steering_broker_mutation_failed",
                severity="warning",
                message="Broker steering mutation blocked: execution service unavailable",
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                payload={"decision": decision.decision, "ticker": decision.ticker, "reason_codes": decision.reason_codes},
            )
            return

        broker_order_id = state.broker_order_id
        broker_position_id = state.broker_position_id
        if decision.decision == "cancel_pending_order":
            if not state.has_pending_order or broker_order_id is None:
                self._block_unsupported_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now)
                return
            if not self._cancel_pending_order_is_live_enabled(decision, reviewed_sample_counts):
                self._block_threshold_decision(
                    saved_decision_id,
                    decision,
                    reason="live_pending_invalidation_sample_threshold_unmet",
                    run_id=run_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    normalized_now=normalized_now,
                    payload={"broker_order_id": broker_order_id, "reviewed_sample_counts": reviewed_sample_counts},
                )
                return
            if "pending_expired" not in set(decision.reason_codes):
                self.observability.record(
                    event_type="steering_broker_mutation_attempted",
                    message="Broker steering cancellation attempted after sample-threshold review",
                    run_id=run_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    payload={"decision": decision.decision, "ticker": decision.ticker, "broker_order_id": broker_order_id},
                )
            else:
                self.observability.record(
                    event_type="steering_broker_mutation_attempted",
                    message="Broker steering cancellation attempted",
                    run_id=run_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    payload={"decision": decision.decision, "ticker": decision.ticker, "broker_order_id": broker_order_id},
                )
            try:
                self.order_execution.cancel_execution(broker_order_id)
            except Exception as exc:
                self._fail_decision(saved_decision_id, decision, exc, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now, payload={"broker_order_id": broker_order_id})
                return
            self._succeed_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now, message="Broker steering cancellation succeeded", payload={"broker_order_id": broker_order_id})
            return

        if decision.decision == "close_position_now":
            if not state.has_open_position or broker_position_id is None:
                self._block_unsupported_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now)
                return
            if not self._close_now_is_live_enabled(reviewed_sample_counts):
                self._block_threshold_decision(
                    saved_decision_id,
                    decision,
                    reason="live_close_now_sample_threshold_unmet",
                    run_id=run_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    normalized_now=normalized_now,
                    payload={"broker_position_id": broker_position_id, "reviewed_sample_counts": reviewed_sample_counts},
                )
                return
            self.observability.record(
                event_type="steering_broker_mutation_attempted",
                message="Broker steering close-position attempted",
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                payload={"decision": decision.decision, "ticker": decision.ticker, "broker_position_id": broker_position_id},
            )
            try:
                self.order_execution.close_position(state.ticker)
            except Exception as exc:
                self._fail_decision(saved_decision_id, decision, exc, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now, payload={"broker_position_id": broker_position_id, "ticker": state.ticker})
                return
            self._succeed_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now, message="Broker steering close-position succeeded", payload={"broker_position_id": broker_position_id, "ticker": state.ticker})
            return

        if decision.decision in {"tighten_stop_loss", "move_stop_to_breakeven_or_profit", "lower_take_profit"}:
            if not state.has_open_position or broker_order_id is None:
                self._block_unsupported_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now)
                return
            if not self._amendment_is_live_enabled(reviewed_sample_counts):
                self._block_threshold_decision(
                    saved_decision_id,
                    decision,
                    reason="live_amendment_sample_threshold_unmet",
                    run_id=run_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    normalized_now=normalized_now,
                    payload={"broker_order_id": broker_order_id, "reviewed_sample_counts": reviewed_sample_counts},
                )
                return
            amend_stop_loss = decision.proposed_stop_loss if decision.decision in {"tighten_stop_loss", "move_stop_to_breakeven_or_profit"} else None
            amend_take_profit = decision.proposed_take_profit if decision.decision == "lower_take_profit" else None
            self.observability.record(
                event_type="steering_broker_mutation_attempted",
                message="Broker steering amendment attempted",
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                payload={"decision": decision.decision, "ticker": decision.ticker, "broker_order_id": broker_order_id, "stop_loss": amend_stop_loss, "take_profit": amend_take_profit},
            )
            try:
                self.order_execution.amend_execution(broker_order_id, stop_loss=amend_stop_loss, take_profit=amend_take_profit)
            except Exception as exc:
                self._fail_decision(saved_decision_id, decision, exc, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now, payload={"broker_order_id": broker_order_id, "stop_loss": amend_stop_loss, "take_profit": amend_take_profit})
                return
            self._succeed_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now, message="Broker steering amendment succeeded", payload={"broker_order_id": broker_order_id, "stop_loss": amend_stop_loss, "take_profit": amend_take_profit})
            return

        self._block_unsupported_decision(saved_decision_id, decision, run_id=run_id, job_id=job_id, correlation_id=correlation_id, normalized_now=normalized_now)

    def _reviewed_sample_counts(self) -> dict[str, int]:
        total_dry_run = self.decision_repository.count(execution_status="dry_run")
        amendment_dry_run = self.decision_repository.count(
            execution_status="dry_run",
            decisions=["tighten_stop_loss", "move_stop_to_breakeven_or_profit", "lower_take_profit"],
        )
        close_now_dry_run = self.decision_repository.count(
            execution_status="dry_run",
            decisions=["close_position_now"],
        )
        return {
            "total_dry_run": total_dry_run,
            "amendment_dry_run": amendment_dry_run,
            "close_now_dry_run": close_now_dry_run,
        }

    def _cancel_pending_order_is_live_enabled(self, decision: BrokerSteeringDecision, reviewed_sample_counts: dict[str, int]) -> bool:
        if "pending_expired" in set(decision.reason_codes):
            return True
        return reviewed_sample_counts.get("total_dry_run", 0) >= self.settings["min_reviewed_dry_run_decisions_before_enable"]

    def _amendment_is_live_enabled(self, reviewed_sample_counts: dict[str, int]) -> bool:
        return (
            reviewed_sample_counts.get("total_dry_run", 0) >= self.settings["min_reviewed_dry_run_decisions_before_enable"]
            and reviewed_sample_counts.get("amendment_dry_run", 0) >= self.settings["min_reviewed_dry_run_amendments_before_enable"]
        )

    def _close_now_is_live_enabled(self, reviewed_sample_counts: dict[str, int]) -> bool:
        return (
            reviewed_sample_counts.get("total_dry_run", 0) >= self.settings["min_reviewed_dry_run_decisions_before_enable"]
            and reviewed_sample_counts.get("close_now_dry_run", 0) >= self.settings["min_reviewed_dry_run_close_now_before_enable"]
        )

    def _block_unsupported_decision(
        self,
        saved_decision_id: int,
        decision: BrokerSteeringDecision,
        *,
        run_id: int | None,
        job_id: int | None,
        correlation_id: str | None,
        normalized_now: datetime,
    ) -> None:
        self._block_threshold_decision(
            saved_decision_id,
            decision,
            reason="live_execution_not_supported_for_decision",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            normalized_now=normalized_now,
            payload={"reason_codes": decision.reason_codes},
            severity="warning",
            message="Broker steering mutation blocked for unsupported decision",
        )

    def _block_threshold_decision(
        self,
        saved_decision_id: int,
        decision: BrokerSteeringDecision,
        *,
        reason: str,
        run_id: int | None,
        job_id: int | None,
        correlation_id: str | None,
        normalized_now: datetime,
        payload: dict[str, object],
        severity: str = "warning",
        message: str = "Broker steering mutation blocked by live enablement thresholds",
    ) -> None:
        self.decision_repository.update_execution_result(
            saved_decision_id,
            execution_status="blocked",
            executed_at=normalized_now,
            error_message=reason,
        )
        self.observability.record(
            event_type="steering_broker_mutation_failed",
            severity=severity,
            message=message,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={"decision": decision.decision, "ticker": decision.ticker, "reason_codes": decision.reason_codes, **payload},
        )

    def _fail_decision(
        self,
        saved_decision_id: int,
        decision: BrokerSteeringDecision,
        exc: Exception,
        *,
        run_id: int | None,
        job_id: int | None,
        correlation_id: str | None,
        normalized_now: datetime,
        payload: dict[str, object],
    ) -> None:
        self.decision_repository.update_execution_result(
            saved_decision_id,
            execution_status="failed",
            executed_at=normalized_now,
            error_message=str(exc),
        )
        self.observability.record(
            event_type="steering_broker_mutation_failed",
            severity="warning",
            message=str(exc),
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={"decision": decision.decision, "ticker": decision.ticker, **payload},
        )

    def _succeed_decision(
        self,
        saved_decision_id: int,
        decision: BrokerSteeringDecision,
        *,
        run_id: int | None,
        job_id: int | None,
        correlation_id: str | None,
        normalized_now: datetime,
        message: str,
        payload: dict[str, object],
    ) -> None:
        self.decision_repository.update_execution_result(
            saved_decision_id,
            execution_status="succeeded",
            executed_at=normalized_now,
        )
        self.observability.record(
            event_type="steering_broker_mutation_succeeded",
            message=message,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={"decision": decision.decision, "ticker": decision.ticker, **payload},
        )
