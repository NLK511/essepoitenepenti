from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import (
    BrokerOrderExecution,
    BrokerPosition,
    RecommendationPlan,
)
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import (
    BrokerReconciliationSnapshotRepository,
)
from trade_proposer_app.repositories.broker_steering_decisions import (
    BrokerSteeringDecisionRepository,
)
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.broker_position_steering import (
    BrokerSteeringConfig,
    BrokerSteeringDecision,
    BrokerSteeringEngine,
    BrokerSteeringState,
)
from trade_proposer_app.services.broker_steering_evidence import BrokerSteeringEvidenceBuilder


@dataclass(frozen=True)
class BrokerSteeringRunSummary:
    total_candidates: int
    decisions: dict[str, int]
    execution_status: str
    broker_refresh_attempted: bool = False
    broker_refresh_status: str = "skipped"
    broker_refresh_synced_count: int = 0
    broker_refresh_failed_count: int = 0
    broker_refresh_error: str = ""
    broker_refresh_completed_at: str | None = None


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
        self.context_snapshots = ContextSnapshotRepository(session)
        self.settings = SettingsRepository(session).get_steering_config()
        self.evidence_builder = BrokerSteeringEvidenceBuilder()
        self._price_cache: dict[str, float | None] = {}

    def list_states(
        self, *, limit: int = 200, now: datetime | None = None
    ) -> list[BrokerSteeringState]:
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
        orders = [
            order
            for order in self.orders.list_active(limit=limit)
            if order.recommendation_plan_id is not None
        ]
        return {order.recommendation_plan_id: order for order in orders}

    def _active_positions_by_plan_id(self, *, limit: int) -> dict[int, BrokerPosition]:
        positions = [
            position
            for position in self.positions.list_active(limit=limit)
            if position.recommendation_plan_id is not None
            and position.current_quantity > 0
            and str(position.status or "").strip().lower() in {"open", "closing"}
        ]
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
        entry_price = (
            plan.entry_price_high if plan.entry_price_high is not None else plan.entry_price_low
        )
        if plan.entry_price_low is not None and plan.entry_price_high is not None:
            entry_price = (float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0
        current_stop_loss = order.stop_loss if order is not None else plan.stop_loss
        current_take_profit = order.take_profit if order is not None else plan.take_profit
        broker_order_status = order.status if order is not None else None
        broker_position_status = position.status if position is not None else None
        broker_side = (
            position.side if position is not None else (order.side if order is not None else None)
        )
        direction = self._direction_for_plan(plan)
        expiration_at = None
        if plan.computed_at and plan.holding_period_days is not None:
            expiration_at = plan.computed_at + timedelta(days=max(1, int(plan.holding_period_days)))
        normalized_now = now or datetime.now(UTC)
        position_holding_period_expired = bool(
            position is not None and expiration_at is not None and expiration_at < normalized_now
        )
        broker_reconciliation_healthy, broker_reconciliation_age_minutes = (
            self._broker_reconciliation_health(
                plan.ticker,
                now=normalized_now,
                order=order,
                position=position,
            )
        )
        latest_signal = self._latest_signal(plan.ticker)
        steering_evidence = self.evidence_builder.build(plan, now=now, latest_signal=latest_signal)
        current_actionability = self._fresh_evidence_text(steering_evidence, "actionability")
        current_analysis_direction = self._fresh_evidence_text(steering_evidence, "analysis_direction")
        current_confidence = self._fresh_evidence_float(steering_evidence, "confidence_percent")
        current_calibrated_confidence = self._fresh_evidence_float(steering_evidence, "calibrated_confidence_percent")
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
            confidence_percent=current_confidence if current_confidence is not None else plan.confidence_percent,
            calibrated_confidence_percent=current_calibrated_confidence,
            actionability=current_actionability,
            analysis_direction=current_analysis_direction,
            severe_negative_news=self._has_severe_negative_news(
                plan, now=now, evidence=steering_evidence
            ),
            original_plan_action=plan.action,
            evidence_source=str(steering_evidence.get("source") or ""),
            evidence_freshness_status=str(steering_evidence.get("freshness_status") or ""),
            evidence_computed_at=str(steering_evidence.get("computed_at") or ""),
            ticker_signal_snapshot_id=int(steering_evidence["ticker_signal_snapshot_id"])
            if isinstance(steering_evidence.get("ticker_signal_snapshot_id"), int)
            else None,
            price_chase_percent=None,
            volatility_percent=None,
            has_pending_order=order is not None and not is_position,
            has_open_position=is_position,
            broker_order_status=broker_order_status,
            broker_position_status=broker_position_status,
            broker_quantity=position.current_quantity
            if position is not None
            else (order.quantity if order is not None else None),
            broker_side=broker_side,
            broker_ownership_known=bool(order is not None or position is not None),
            broker_reconciliation_healthy=broker_reconciliation_healthy,
            broker_reconciliation_age_minutes=broker_reconciliation_age_minutes,
            linked_exit_orders_missing=self._linked_protective_orders_missing(position),
            position_holding_period_expired=position_holding_period_expired,
            expiration_at=expiration_at,
            now=now,
        )

    def _latest_signal(self, ticker: str):
        return next(iter(self.context_snapshots.list_ticker_signal_snapshots(ticker=ticker, limit=1)), None)

    @staticmethod
    def _fresh_evidence_text(evidence: dict[str, object], key: str) -> str | None:
        if str(evidence.get("freshness_status") or "").strip().lower() != "fresh":
            return None
        value = evidence.get(key)
        return str(value).strip().lower() if value is not None and str(value).strip() else None

    @staticmethod
    def _fresh_evidence_float(evidence: dict[str, object], key: str) -> float | None:
        if str(evidence.get("freshness_status") or "").strip().lower() != "fresh":
            return None
        value = evidence.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    @classmethod
    def _linked_protective_orders_missing(cls, position: BrokerPosition | None) -> bool:
        if position is None or position.current_quantity <= 0:
            return False
        stop_required = position.stop_loss_order_price is not None
        take_profit_required = position.take_profit_order_price is not None
        if stop_required and not cls._protective_order_active(
            position.stop_loss_order_id, position.stop_loss_order_status
        ):
            return True
        if take_profit_required and not cls._protective_order_active(
            position.take_profit_order_id, position.take_profit_order_status
        ):
            return True
        return not stop_required and not take_profit_required

    @staticmethod
    def _protective_order_active(order_id: str | None, status: str | None) -> bool:
        if not order_id:
            return False
        normalized = str(status or "").strip().lower()
        return normalized not in {
            "",
            "filled",
            "canceled",
            "cancelled",
            "expired",
            "rejected",
            "failed",
        }

    @staticmethod
    def _direction_for_plan(plan: RecommendationPlan) -> str:
        action = str(plan.action or "").strip().lower()
        if action in {"short", "sell"}:
            return "short"
        if action in {"long", "buy"}:
            return "long"
        return "unknown"

    def _broker_reconciliation_health(
        self,
        ticker: str,
        *,
        now: datetime,
        order: BrokerOrderExecution | None = None,
        position: BrokerPosition | None = None,
    ) -> tuple[bool, float | None]:
        snapshot_health, snapshot_age = self._snapshot_reconciliation_health(ticker, now=now)
        if snapshot_health is False:
            return False, snapshot_age

        local_health, local_age = self._local_broker_record_health(
            order=order,
            position=position,
            now=now,
        )
        if local_health is not None:
            return local_health, local_age
        if snapshot_health is not None:
            return snapshot_health, snapshot_age
        return False, None

    def _snapshot_reconciliation_health(
        self, ticker: str, *, now: datetime
    ) -> tuple[bool | None, float | None]:
        snapshots = self.snapshots.list_latest_for_ticker(ticker, limit=1)
        if not snapshots:
            return None, None
        latest = snapshots[0]
        age_minutes = self._age_minutes(latest.created_at, now=now)
        if latest.warnings:
            return False, age_minutes
        severity = str(latest.drift_severity or "").strip().lower()
        if severity and severity != "ok":
            return False, age_minutes
        max_age = float(self.settings.get("max_reconciliation_age_minutes", 30) or 30)
        if age_minutes is not None and age_minutes <= max_age:
            return True, age_minutes
        return None, age_minutes

    def _local_broker_record_health(
        self,
        *,
        order: BrokerOrderExecution | None,
        position: BrokerPosition | None,
        now: datetime,
    ) -> tuple[bool | None, float | None]:
        max_age = float(self.settings.get("max_reconciliation_age_minutes", 30) or 30)
        if position is not None:
            protective_required = self._position_has_expected_protective_orders(position)
            if protective_required:
                protective_age = self._age_minutes(position.protective_orders_verified_at, now=now)
                if protective_age is None:
                    return False, None
                if protective_age > max_age:
                    return False, protective_age
            position_age = self._age_minutes(position.updated_at, now=now)
            if position_age is not None:
                local_age = max(position_age, protective_age) if protective_required and protective_age is not None else position_age
                return local_age <= max_age, local_age
            return None, None
        if order is not None:
            order_age = self._age_minutes(order.updated_at, now=now)
            if order_age is not None:
                return order_age <= max_age, order_age
        return None, None

    @staticmethod
    def _position_has_expected_protective_orders(position: BrokerPosition) -> bool:
        return bool(
            position.stop_loss_order_id
            or position.take_profit_order_id
            or position.stop_loss_order_price is not None
            or position.take_profit_order_price is not None
        )

    @staticmethod
    def _age_minutes(value: datetime | None, *, now: datetime) -> float | None:
        if value is None:
            return None
        normalized_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        return max(0.0, (normalized_now.astimezone(UTC) - normalized_value.astimezone(UTC)).total_seconds() / 60.0)

    @classmethod
    def _has_severe_negative_news(
        cls,
        plan: RecommendationPlan,
        *,
        now: datetime | None,
        evidence: dict[str, object] | None = None,
    ) -> bool:
        if evidence is not None and BrokerSteeringEvidenceBuilder.has_severe_invalidation(evidence):
            return True
        evidence = (
            plan.signal_breakdown.get("steering_evidence")
            if hasattr(plan.signal_breakdown, "get")
            else None
        )
        if isinstance(evidence, dict) and cls._fresh_steering_evidence(evidence, now=now):
            warnings = (
                evidence.get("warnings") if isinstance(evidence.get("warnings"), list) else []
            )
            conflict_flags = (
                evidence.get("market_intelligence_conflict_flags")
                if isinstance(evidence.get("market_intelligence_conflict_flags"), list)
                else []
            )
            for value in [*warnings, *conflict_flags]:
                normalized = str(value or "").strip().lower().replace(" ", "_")
                if (
                    "severe_negative_news" in normalized
                    or "severe_negative_event" in normalized
                    or "thesis_invalidated" in normalized
                ):
                    return True
        for warning in plan.warnings:
            normalized = str(warning or "").strip().lower().replace(" ", "_")
            if "severe_negative_news" in normalized or "severe_negative_event" in normalized:
                return True
        return False

    @staticmethod
    def _fresh_steering_evidence(evidence: dict[str, object], *, now: datetime | None) -> bool:
        if str(evidence.get("freshness_status") or "").strip().lower() == "stale":
            return False
        raw_computed_at = evidence.get("computed_at")
        if not raw_computed_at:
            return False
        try:
            computed_at = datetime.fromisoformat(str(raw_computed_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=UTC)
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        return computed_at.astimezone(UTC) >= reference.astimezone(UTC) - timedelta(days=1)

    @staticmethod
    def _calibrated_confidence(plan: RecommendationPlan) -> float | None:
        review = (
            plan.signal_breakdown.get("calibration_review")
            if hasattr(plan.signal_breakdown, "get")
            else None
        )
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
        broker_reconciliation_service=None,
    ) -> None:
        self.session = session
        self.engine = engine or BrokerSteeringEngine()
        self.builder = builder or BrokerSteeringStateBuilder(session)
        self.decision_repository = decision_repository or BrokerSteeringDecisionRepository(session)
        self.observability = observability or ObservabilityEventRepository(session)
        self.settings_repository = settings_repository or SettingsRepository(session)
        self.order_execution = order_execution
        self.broker_reconciliation_service = broker_reconciliation_service
        if self.order_execution is None:
            try:
                from trade_proposer_app.services.builders import create_order_execution_service

                self.order_execution = create_order_execution_service(session)
            except Exception:
                self.order_execution = None
        if self.broker_reconciliation_service is None:
            try:
                from trade_proposer_app.services.broker_reconciliation import BrokerReconciliationService

                self.broker_reconciliation_service = BrokerReconciliationService(session)
            except Exception:
                self.broker_reconciliation_service = None
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
        normalized_now = now or datetime.now(UTC)
        config = BrokerSteeringConfig(**self.settings)
        broker_refresh = self._refresh_broker_state(limit=limit)
        live_refresh_ok = broker_refresh["broker_refresh_status"] == "succeeded"
        states = self.builder.list_states(limit=limit, now=normalized_now)
        reviewed_sample_counts = (
            self._reviewed_sample_counts() if config.enabled and not config.dry_run else None
        )
        self.observability.record(
            event_type="steering_run_started",
            message="Broker steering run started",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={
                "candidate_count": len(states),
                "dry_run": config.dry_run,
                "enabled": config.enabled,
                **broker_refresh,
            },
        )
        counts: dict[str, int] = {}
        decision_execution_statuses: list[str] = []
        initial_execution_status = (
            "dry_run"
            if config.dry_run
            else "submitted"
            if config.enabled and live_refresh_ok
            else "blocked"
        )
        for state in states:
            decision = self.engine.evaluate(state, config)
            counts[decision.decision] = counts.get(decision.decision, 0) + 1
            saved_decision = self.decision_repository.create(
                recommendation_plan_id=decision.recommendation_plan_id,
                ticker=decision.ticker,
                decision=decision,
                broker_order_id=decision.broker_order_id,
                broker_position_id=decision.broker_position_id,
                execution_status=initial_execution_status,
                executed_at=normalized_now,
            )
            self.observability.record(
                event_type="steering_decision_created",
                message=decision.human_summary,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "decision": decision.decision,
                    "ticker": decision.ticker,
                    "reason_codes": decision.reason_codes,
                    "recommendation_plan_id": decision.recommendation_plan_id,
                },
            )
            if config.enabled and not config.dry_run and live_refresh_ok:
                decision_execution_statuses.append(
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
                )
            else:
                decision_execution_statuses.append(initial_execution_status)
        self.observability.record(
            event_type="steering_run_completed",
            message="Broker steering run completed",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={
                "candidate_count": len(states),
                "decisions": counts,
                "dry_run": config.dry_run,
                "execution_status": self._aggregate_execution_status(
                    decision_execution_statuses, dry_run=config.dry_run
                ),
                **broker_refresh,
            },
        )
        return BrokerSteeringRunSummary(
            total_candidates=len(states),
            decisions=counts,
            execution_status=self._aggregate_execution_status(
                decision_execution_statuses, dry_run=config.dry_run
            ),
            broker_refresh_attempted=bool(broker_refresh["broker_refresh_attempted"]),
            broker_refresh_status=str(broker_refresh["broker_refresh_status"]),
            broker_refresh_synced_count=int(broker_refresh["broker_refresh_synced_count"]),
            broker_refresh_failed_count=int(broker_refresh["broker_refresh_failed_count"]),
            broker_refresh_error=str(broker_refresh["broker_refresh_error"]),
            broker_refresh_completed_at=(
                broker_refresh["broker_refresh_completed_at"]
                if isinstance(broker_refresh["broker_refresh_completed_at"], str)
                else None
            ),
        )

    def _refresh_broker_state(self, *, limit: int) -> dict[str, object]:
        completed_at = datetime.now(UTC).isoformat()
        try:
            if self.broker_reconciliation_service is not None:
                outcome = self.broker_reconciliation_service.sync_open_orders(limit=limit)
            elif self.order_execution is not None and hasattr(
                self.order_execution, "sync_open_executions"
            ):
                outcome = self.order_execution.sync_open_executions(limit=limit)
            else:
                return {
                    "broker_refresh_attempted": False,
                    "broker_refresh_status": "skipped",
                    "broker_refresh_synced_count": 0,
                    "broker_refresh_failed_count": 0,
                    "broker_refresh_error": "broker_refresh_service_unavailable",
                    "broker_refresh_completed_at": completed_at,
                }
        except Exception as exc:
            return {
                "broker_refresh_attempted": True,
                "broker_refresh_status": "failed",
                "broker_refresh_synced_count": 0,
                "broker_refresh_failed_count": 1,
                "broker_refresh_error": str(exc),
                "broker_refresh_completed_at": datetime.now(UTC).isoformat(),
            }
        summary = getattr(outcome, "summary", {})
        if not isinstance(summary, dict):
            summary = {}
        failed_count = int(summary.get("failed_count", 0) or 0)
        warnings = summary.get("warnings", [])
        error = (
            "; ".join(str(item) for item in warnings if str(item).strip())
            if failed_count and isinstance(warnings, list)
            else ""
        )
        return {
            "broker_refresh_attempted": True,
            "broker_refresh_status": "failed" if failed_count else "succeeded",
            "broker_refresh_synced_count": int(summary.get("synced_count", 0) or 0),
            "broker_refresh_failed_count": failed_count,
            "broker_refresh_error": error,
            "broker_refresh_completed_at": datetime.now(UTC).isoformat(),
        }

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
    ) -> str:
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
                payload={
                    "decision": decision.decision,
                    "ticker": decision.ticker,
                    "reason_codes": decision.reason_codes,
                },
            )
            return "blocked"

        if decision.decision == "cancel_pending_order":
            return self._execute_cancel_pending_order(
                saved_decision_id=saved_decision_id,
                state=state,
                decision=decision,
                reviewed_sample_counts=reviewed_sample_counts,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
            )

        if decision.decision == "close_position_now":
            return self._execute_close_position_now(
                saved_decision_id=saved_decision_id,
                state=state,
                decision=decision,
                reviewed_sample_counts=reviewed_sample_counts,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
            )

        if decision.decision in {
            "tighten_stop_loss",
            "move_stop_to_breakeven_or_profit",
            "lower_take_profit",
        }:
            return self._execute_exit_amendment(
                saved_decision_id=saved_decision_id,
                state=state,
                decision=decision,
                reviewed_sample_counts=reviewed_sample_counts,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
            )

        self._block_unsupported_decision(
            saved_decision_id,
            decision,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            normalized_now=normalized_now,
        )
        return "blocked"

    def _execute_cancel_pending_order(
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
    ) -> str:
        broker_order_id = state.broker_order_id
        if not state.has_pending_order or broker_order_id is None:
            self._block_unsupported_decision(
                saved_decision_id,
                decision,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
            )
            return "blocked"
        if not self._cancel_pending_order_is_live_enabled(decision, reviewed_sample_counts):
            self._block_threshold_decision(
                saved_decision_id,
                decision,
                reason="live_pending_invalidation_sample_threshold_unmet",
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
                payload={
                    "broker_order_id": broker_order_id,
                    "reviewed_sample_counts": reviewed_sample_counts,
                },
            )
            return "blocked"
        self.observability.record(
            event_type="steering_broker_mutation_attempted",
            message="Broker steering cancellation attempted"
            if "pending_expired" in set(decision.reason_codes)
            else "Broker steering cancellation attempted after sample-threshold review",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={
                "decision": decision.decision,
                "ticker": decision.ticker,
                "broker_order_id": broker_order_id,
            },
        )
        try:
            self.order_execution.cancel_execution(broker_order_id)
        except Exception as exc:
            self._fail_decision(
                saved_decision_id,
                decision,
                exc,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
                payload={"broker_order_id": broker_order_id},
            )
            return "failed"
        self._succeed_decision(
            saved_decision_id,
            decision,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            normalized_now=normalized_now,
            message="Broker steering cancellation succeeded",
            payload={"broker_order_id": broker_order_id},
        )
        return "succeeded"

    def _execute_close_position_now(
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
    ) -> str:
        broker_position_id = state.broker_position_id
        if not state.has_open_position or broker_position_id is None:
            self._block_unsupported_decision(
                saved_decision_id,
                decision,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
            )
            return "blocked"
        if not self._close_now_is_live_enabled(reviewed_sample_counts):
            self._block_threshold_decision(
                saved_decision_id,
                decision,
                reason="live_close_now_sample_threshold_unmet",
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
                payload={
                    "broker_position_id": broker_position_id,
                    "reviewed_sample_counts": reviewed_sample_counts,
                },
            )
            return "blocked"
        self.observability.record(
            event_type="steering_broker_mutation_attempted",
            message="Broker steering close-position attempted",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload={
                "decision": decision.decision,
                "ticker": decision.ticker,
                "broker_position_id": broker_position_id,
            },
        )
        try:
            self.order_execution.close_position(state.ticker)
        except Exception as exc:
            self._fail_decision(
                saved_decision_id,
                decision,
                exc,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
                payload={"broker_position_id": broker_position_id, "ticker": state.ticker},
            )
            return "failed"
        self._succeed_decision(
            saved_decision_id,
            decision,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            normalized_now=normalized_now,
            message="Broker steering close-position succeeded",
            payload={"broker_position_id": broker_position_id, "ticker": state.ticker},
        )
        return "succeeded"

    def _execute_exit_amendment(
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
    ) -> str:
        broker_order_id = state.broker_order_id
        if not state.has_open_position or broker_order_id is None:
            self._block_unsupported_decision(
                saved_decision_id,
                decision,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
            )
            return "blocked"
        if not self._amendment_is_live_enabled(reviewed_sample_counts):
            self._block_threshold_decision(
                saved_decision_id,
                decision,
                reason="live_amendment_sample_threshold_unmet",
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
                payload={
                    "broker_order_id": broker_order_id,
                    "reviewed_sample_counts": reviewed_sample_counts,
                },
            )
            return "blocked"
        amend_stop_loss = (
            decision.proposed_stop_loss
            if decision.decision in {"tighten_stop_loss", "move_stop_to_breakeven_or_profit"}
            else None
        )
        amend_take_profit = (
            decision.proposed_take_profit if decision.decision == "lower_take_profit" else None
        )
        payload = {
            "decision": decision.decision,
            "ticker": decision.ticker,
            "broker_order_id": broker_order_id,
            "stop_loss": amend_stop_loss,
            "take_profit": amend_take_profit,
        }
        self.observability.record(
            event_type="steering_broker_mutation_attempted",
            message="Broker steering amendment attempted",
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload=payload,
        )
        try:
            self.order_execution.amend_execution(
                broker_order_id, stop_loss=amend_stop_loss, take_profit=amend_take_profit
            )
        except Exception as exc:
            self._fail_decision(
                saved_decision_id,
                decision,
                exc,
                run_id=run_id,
                job_id=job_id,
                correlation_id=correlation_id,
                normalized_now=normalized_now,
                payload={
                    "broker_order_id": broker_order_id,
                    "stop_loss": amend_stop_loss,
                    "take_profit": amend_take_profit,
                },
            )
            return "failed"
        self._succeed_decision(
            saved_decision_id,
            decision,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            normalized_now=normalized_now,
            message="Broker steering amendment succeeded",
            payload={
                "broker_order_id": broker_order_id,
                "stop_loss": amend_stop_loss,
                "take_profit": amend_take_profit,
            },
        )
        return "succeeded"

    @staticmethod
    def _aggregate_execution_status(statuses: list[str], *, dry_run: bool) -> str:
        if dry_run:
            return "dry_run"
        if not statuses:
            return "no_action"
        normalized = [str(status or "").strip().lower() for status in statuses]
        if all(status == "succeeded" for status in normalized):
            return "succeeded"
        if all(status == "blocked" for status in normalized):
            return "blocked"
        if all(status == "failed" for status in normalized):
            return "failed"
        if any(status == "succeeded" for status in normalized):
            return "partial_success"
        if any(status == "failed" for status in normalized):
            return "failed"
        if all(status == "dry_run" for status in normalized):
            return "dry_run"
        return "blocked"

    def _reviewed_sample_counts(self) -> dict[str, int]:
        total_dry_run = self.decision_repository.count(execution_status="dry_run")
        amendment_dry_run = self.decision_repository.count(
            execution_status="dry_run",
            decisions=[
                "tighten_stop_loss",
                "move_stop_to_breakeven_or_profit",
                "lower_take_profit",
            ],
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

    def _cancel_pending_order_is_live_enabled(
        self, decision: BrokerSteeringDecision, reviewed_sample_counts: dict[str, int]
    ) -> bool:
        if "pending_expired" in set(decision.reason_codes):
            return True
        return (
            reviewed_sample_counts.get("total_dry_run", 0)
            >= self.settings["min_reviewed_dry_run_decisions_before_enable"]
        )

    def _amendment_is_live_enabled(self, reviewed_sample_counts: dict[str, int]) -> bool:
        return (
            reviewed_sample_counts.get("total_dry_run", 0)
            >= self.settings["min_reviewed_dry_run_decisions_before_enable"]
            and reviewed_sample_counts.get("amendment_dry_run", 0)
            >= self.settings["min_reviewed_dry_run_amendments_before_enable"]
        )

    def _close_now_is_live_enabled(self, reviewed_sample_counts: dict[str, int]) -> bool:
        return (
            reviewed_sample_counts.get("total_dry_run", 0)
            >= self.settings["min_reviewed_dry_run_decisions_before_enable"]
            and reviewed_sample_counts.get("close_now_dry_run", 0)
            >= self.settings["min_reviewed_dry_run_close_now_before_enable"]
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
            payload={
                "decision": decision.decision,
                "ticker": decision.ticker,
                "reason_codes": decision.reason_codes,
                **payload,
            },
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
