from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

SteeringDecisionName = Literal[
    "cancel_pending_order",
    "keep_pending_order",
    "tighten_stop_loss",
    "move_stop_to_breakeven_or_profit",
    "lower_take_profit",
    "close_position_now",
    "keep_position_exits",
    "manual_review_required",
]


@dataclass(frozen=True)
class BrokerSteeringConfig:
    enabled: bool = False
    dry_run: bool = True
    cancel_expired_pending_orders_enabled: bool = True
    cancel_invalidated_pending_orders_enabled: bool = True
    move_to_profit_enabled: bool = True
    close_on_severe_invalidation_enabled: bool = True
    tighten_on_deterioration_enabled: bool = True
    lower_tp_on_weakness_enabled: bool = True
    pending_expiration_grace_minutes: int = 5
    pending_min_confidence_percent: float = 55.0
    pending_invalidation_required_signals: int = 2
    pending_price_chase_limit_percent: float = 1.0
    breakeven_trigger_percent: float = 0.75
    min_profit_lock_percent: float = 0.10
    position_close_confidence_percent: float = 40.0
    position_close_required_signals: int = 3
    position_min_hold_confidence_percent: float = 50.0
    position_deterioration_required_signals: int = 2
    deterioration_stop_cushion_percent: float = 0.35
    weakened_thesis_tp_cushion_percent: float = 0.50
    min_tp_distance_percent: float = 0.10
    min_reviewed_dry_run_decisions_before_enable: int = 30
    min_reviewed_dry_run_amendments_before_enable: int = 10
    min_reviewed_dry_run_close_now_before_enable: int = 10


@dataclass(frozen=True)
class BrokerSteeringState:
    recommendation_plan_id: int
    ticker: str
    direction: str
    current_price: float | None = None
    entry_price: float | None = None
    original_stop_loss: float | None = None
    original_take_profit: float | None = None
    current_stop_loss: float | None = None
    current_take_profit: float | None = None
    confidence_percent: float | None = None
    calibrated_confidence_percent: float | None = None
    actionability: str | None = None
    analysis_direction: str | None = None
    severe_negative_news: bool = False
    price_chase_percent: float | None = None
    volatility_percent: float | None = None
    has_pending_order: bool = False
    has_open_position: bool = False
    broker_order_status: str | None = None
    broker_position_status: str | None = None
    broker_quantity: int | None = None
    broker_side: str | None = None
    broker_order_id: int | None = None
    broker_position_id: int | None = None
    broker_ownership_known: bool = True
    broker_reconciliation_healthy: bool = True
    linked_exit_orders_missing: bool = False
    expiration_at: datetime | None = None
    now: datetime | None = None


@dataclass(frozen=True)
class BrokerSteeringDecision:
    decision: SteeringDecisionName
    ticker: str
    recommendation_plan_id: int
    broker_order_id: int | None = None
    broker_position_id: int | None = None
    reason_codes: list[str] = field(default_factory=list)
    human_summary: str = ""
    current_price: float | None = None
    current_stop_loss: float | None = None
    current_take_profit: float | None = None
    proposed_stop_loss: float | None = None
    proposed_take_profit: float | None = None
    risk_delta_usd: float | None = None
    risk_delta_percent: float | None = None
    confidence: str = "low"
    execute_allowed: bool = False
    requires_manual_review: bool = False
    diagnostics: dict[str, object] = field(default_factory=dict)


class BrokerSteeringEngine:
    PENDING_STATUSES = {"queued", "submitted", "accepted", "open", "new", "partially_filled"}
    TERMINAL_STATUSES = {"filled", "canceled", "rejected", "expired", "closed"}

    def evaluate(self, state: BrokerSteeringState, config: BrokerSteeringConfig) -> BrokerSteeringDecision:
        now = state.now or datetime.now(timezone.utc)
        confidence = self._effective_confidence(state)
        if not self._direction_supported(state.direction):
            return self._manual_review(
                state,
                ["ambiguous_direction"],
                "Broker direction is missing or unsupported; do not guess long or short.",
                config=config,
            )
        if state.has_pending_order:
            return self._evaluate_pending(state, config, now, confidence)
        if state.has_open_position:
            return self._evaluate_filled(state, config, now, confidence)
        return self._manual_review(
            state,
            ["no_active_pending_order_or_open_position"],
            "No active pending order or open position was found.",
            config=config,
        )

    def _evaluate_pending(
        self,
        state: BrokerSteeringState,
        config: BrokerSteeringConfig,
        now: datetime,
        confidence: float | None,
    ) -> BrokerSteeringDecision:
        reason_codes: list[str] = []
        if config.cancel_expired_pending_orders_enabled and self._is_expired(state, now, config):
            reason_codes.append("pending_expired")
            return self._decision(
                state,
                config,
                "cancel_pending_order",
                reason_codes,
                "Pending order expired before fill.",
                execute_allowed=True,
                confidence="high",
            )

        invalidation_count = self._pending_invalidation_signals(state, config, confidence)
        if config.cancel_invalidated_pending_orders_enabled and invalidation_count >= config.pending_invalidation_required_signals:
            reason_codes.extend(self._pending_invalidation_reasons(state, config, confidence))
            return self._decision(
                state,
                config,
                "cancel_pending_order",
                reason_codes,
                "Pending order no longer looks actionable.",
                execute_allowed=True,
                confidence="medium" if invalidation_count == config.pending_invalidation_required_signals else "high",
            )

        return self._decision(
            state,
            config,
            "keep_pending_order",
            ["insufficient_invalidation_evidence"],
            "Pending order remains plausible; keep it for now.",
            execute_allowed=False,
            confidence="low",
        )

    def _evaluate_filled(
        self,
        state: BrokerSteeringState,
        config: BrokerSteeringConfig,
        now: datetime,
        confidence: float | None,
    ) -> BrokerSteeringDecision:
        if not state.broker_ownership_known or not state.broker_reconciliation_healthy:
            return self._manual_review(
                state,
                ["broker_uncertainty"],
                "Broker ownership or reconciliation is uncertain; do not mutate exits.",
                broker_confidence="low",
            )

        severe_count = self._severe_invalidation_signals(state, config, confidence)
        if config.close_on_severe_invalidation_enabled and severe_count >= config.position_close_required_signals:
            return self._decision(
                state,
                config,
                "close_position_now",
                self._severe_invalidation_reasons(state, config, confidence),
                "Filled position thesis appears broken; close it now.",
                execute_allowed=True,
                confidence="high" if severe_count > config.position_close_required_signals else "medium",
                proposed_stop_loss=state.current_stop_loss,
                proposed_take_profit=state.current_take_profit,
            )

        profit_lock = self._profit_lock_stop(state, config)
        if config.move_to_profit_enabled and profit_lock is not None:
            return self._decision(
                state,
                config,
                "move_stop_to_breakeven_or_profit",
                ["profit_lock_triggered"],
                "Position has enough favorable movement to lock in a small profit.",
                execute_allowed=True,
                confidence="high",
                proposed_stop_loss=profit_lock,
                proposed_take_profit=state.current_take_profit,
            )

        deterioration_count = self._deterioration_signals(state, config, confidence)
        if config.tighten_on_deterioration_enabled and deterioration_count >= config.position_deterioration_required_signals:
            tightened_stop = self._tightened_stop(state, config, profit_lock)
            if tightened_stop is not None:
                return self._decision(
                    state,
                    config,
                    "tighten_stop_loss",
                    self._deterioration_reasons(state, config, confidence),
                    "Thesis weakened; tighten the stop-loss.",
                    execute_allowed=True,
                    confidence="medium" if deterioration_count == config.position_deterioration_required_signals else "high",
                    proposed_stop_loss=tightened_stop,
                    proposed_take_profit=state.current_take_profit,
                )

        if config.lower_tp_on_weakness_enabled and deterioration_count >= config.position_deterioration_required_signals:
            lowered_tp = self._lowered_take_profit(state, config)
            if lowered_tp is not None:
                return self._decision(
                    state,
                    config,
                    "lower_take_profit",
                    self._deterioration_reasons(state, config, confidence),
                    "Thesis weakened but position is still favorable; lower the take-profit.",
                    execute_allowed=True,
                    confidence="medium",
                    proposed_stop_loss=state.current_stop_loss,
                    proposed_take_profit=lowered_tp,
                )

        return self._decision(
            state,
            config,
            "keep_position_exits",
            ["position_exits_stable"],
            "Position exits remain conservative enough for now.",
            execute_allowed=False,
            confidence="low",
            proposed_stop_loss=state.current_stop_loss,
            proposed_take_profit=state.current_take_profit,
        )

    def _pending_invalidation_signals(self, state: BrokerSteeringState, config: BrokerSteeringConfig, confidence: float | None) -> int:
        signals = 0
        if confidence is not None and confidence < config.pending_min_confidence_percent:
            signals += 1
        if self._is_no_action(state.actionability):
            signals += 1
        if self._analysis_conflicts(state):
            signals += 1
        if state.severe_negative_news:
            signals += 1
        if self._price_chased_away(state, config):
            signals += 1
        if not state.broker_reconciliation_healthy:
            signals += 1
        return signals

    def _pending_invalidation_reasons(self, state: BrokerSteeringState, config: BrokerSteeringConfig, confidence: float | None) -> list[str]:
        reasons: list[str] = []
        if confidence is not None and confidence < config.pending_min_confidence_percent:
            reasons.append("pending_confidence_below_threshold")
        if self._is_no_action(state.actionability):
            reasons.append("pending_actionability_no_action")
        if self._analysis_conflicts(state):
            reasons.append("pending_analysis_conflict")
        if state.severe_negative_news:
            reasons.append("pending_severe_negative_news")
        if self._price_chased_away(state, config):
            reasons.append("pending_price_chased_away")
        if not state.broker_reconciliation_healthy:
            reasons.append("pending_broker_uncertainty")
        return reasons

    def _severe_invalidation_signals(self, state: BrokerSteeringState, config: BrokerSteeringConfig, confidence: float | None) -> int:
        signals = 0
        if confidence is not None and confidence < config.position_close_confidence_percent:
            signals += 1
        if self._is_no_action(state.actionability):
            signals += 1
        if self._analysis_conflicts(state, strong=True):
            signals += 1
        if state.severe_negative_news:
            signals += 1
        if self._hard_stop_broken(state):
            signals += 1
        if state.linked_exit_orders_missing:
            signals += 1
        return signals

    def _severe_invalidation_reasons(self, state: BrokerSteeringState, config: BrokerSteeringConfig, confidence: float | None) -> list[str]:
        reasons: list[str] = []
        if confidence is not None and confidence < config.position_close_confidence_percent:
            reasons.append("position_confidence_below_close_threshold")
        if self._is_no_action(state.actionability):
            reasons.append("position_actionability_no_action")
        if self._analysis_conflicts(state, strong=True):
            reasons.append("position_analysis_conflict")
        if state.severe_negative_news:
            reasons.append("position_severe_negative_news")
        if self._hard_stop_broken(state):
            reasons.append("position_hard_stop_broken")
        if state.linked_exit_orders_missing:
            reasons.append("position_linked_exit_orders_missing")
        return reasons

    def _deterioration_signals(self, state: BrokerSteeringState, config: BrokerSteeringConfig, confidence: float | None) -> int:
        signals = 0
        if confidence is not None and confidence < config.position_min_hold_confidence_percent:
            signals += 1
        if self._is_no_action(state.actionability):
            signals += 1
        if self._analysis_conflicts(state):
            signals += 1
        if state.severe_negative_news:
            signals += 1
        if self._volatility_expanded(state):
            signals += 1
        return signals

    def _deterioration_reasons(self, state: BrokerSteeringState, config: BrokerSteeringConfig, confidence: float | None) -> list[str]:
        reasons: list[str] = []
        if confidence is not None and confidence < config.position_min_hold_confidence_percent:
            reasons.append("position_confidence_below_hold_threshold")
        if self._is_no_action(state.actionability):
            reasons.append("position_actionability_softened")
        if self._analysis_conflicts(state):
            reasons.append("position_analysis_weakened")
        if state.severe_negative_news:
            reasons.append("position_negative_news")
        if self._volatility_expanded(state):
            reasons.append("position_volatility_expanded")
        return reasons

    def _profit_lock_stop(self, state: BrokerSteeringState, config: BrokerSteeringConfig) -> float | None:
        entry = state.entry_price
        current = state.current_price
        if entry is None or current is None:
            return None
        if self._is_long(state.direction):
            if current < entry * (1 + config.breakeven_trigger_percent / 100.0):
                return None
            candidate = entry * (1 + config.min_profit_lock_percent / 100.0)
            baseline = self._long_baseline_stop(state)
            if baseline is not None and candidate <= baseline:
                return None
            return candidate
        if self._is_short(state.direction):
            if current > entry * (1 - config.breakeven_trigger_percent / 100.0):
                return None
            candidate = entry * (1 - config.min_profit_lock_percent / 100.0)
            baseline = self._short_baseline_stop(state)
            if baseline is not None and candidate >= baseline:
                return None
            return candidate
        return None

    def _tightened_stop(self, state: BrokerSteeringState, config: BrokerSteeringConfig, profit_lock: float | None) -> float | None:
        current = state.current_price
        if current is None:
            return None
        if self._is_long(state.direction):
            candidate = current * (1 - config.deterioration_stop_cushion_percent / 100.0)
            baseline_candidates = [value for value in [state.current_stop_loss, state.original_stop_loss, profit_lock] if value is not None]
            baseline = max(baseline_candidates) if baseline_candidates else None
            if baseline is not None and candidate <= baseline:
                return None
            return candidate
        if self._is_short(state.direction):
            candidate = current * (1 + config.deterioration_stop_cushion_percent / 100.0)
            baseline_candidates = [value for value in [state.current_stop_loss, state.original_stop_loss, profit_lock] if value is not None]
            baseline = min(baseline_candidates) if baseline_candidates else None
            if baseline is not None and candidate >= baseline:
                return None
            return candidate
        return None

    def _lowered_take_profit(self, state: BrokerSteeringState, config: BrokerSteeringConfig) -> float | None:
        current = state.current_price
        target = state.current_take_profit
        entry = state.entry_price
        if current is None or target is None or entry is None:
            return None
        if self._is_long(state.direction):
            if current <= entry:
                return None
            candidate = current * (1 + config.weakened_thesis_tp_cushion_percent / 100.0)
            if candidate <= current * (1 + config.min_tp_distance_percent / 100.0):
                return None
            if candidate >= target:
                return None
            if candidate <= entry:
                return None
            return candidate
        if self._is_short(state.direction):
            if current >= entry:
                return None
            candidate = current * (1 - config.weakened_thesis_tp_cushion_percent / 100.0)
            if candidate >= current * (1 - config.min_tp_distance_percent / 100.0):
                return None
            if candidate <= target:
                return None
            if candidate >= entry:
                return None
            return candidate
        return None

    def _is_expired(self, state: BrokerSteeringState, now: datetime, config: BrokerSteeringConfig) -> bool:
        if state.expiration_at is None:
            return False
        return now >= state.expiration_at + timedelta(minutes=config.pending_expiration_grace_minutes)

    def _price_chased_away(self, state: BrokerSteeringState, config: BrokerSteeringConfig) -> bool:
        if state.current_price is None or state.entry_price is None:
            return False
        limit = state.price_chase_percent if state.price_chase_percent is not None else config.pending_price_chase_limit_percent
        if self._is_long(state.direction):
            return state.current_price >= state.entry_price * (1 + limit / 100.0)
        if self._is_short(state.direction):
            return state.current_price <= state.entry_price * (1 - limit / 100.0)
        return False

    def _hard_stop_broken(self, state: BrokerSteeringState) -> bool:
        if state.current_price is None or state.current_stop_loss is None:
            return False
        if self._is_long(state.direction):
            return state.current_price <= state.current_stop_loss
        if self._is_short(state.direction):
            return state.current_price >= state.current_stop_loss
        return False

    def _analysis_conflicts(self, state: BrokerSteeringState, *, strong: bool = False) -> bool:
        if not state.analysis_direction:
            return False
        analysis = state.analysis_direction.strip().lower()
        direction = state.direction.strip().lower()
        if analysis == direction:
            return False
        if strong:
            return analysis in {"bearish", "bullish", "long", "short"}
        return analysis in {"bearish", "bullish", "long", "short", "negative", "positive"}

    @staticmethod
    def _volatility_expanded(state: BrokerSteeringState) -> bool:
        return False

    @staticmethod
    def _direction_supported(direction: str | None) -> bool:
        return str(direction or "").strip().lower() in {"long", "short"}

    @staticmethod
    def _is_no_action(value: str | None) -> bool:
        return str(value or "").strip().lower() in {"no_action", "hold", "watchlist", "neutral"}

    @staticmethod
    def _is_long(direction: str | None) -> bool:
        return str(direction or "").strip().lower() == "long"

    @staticmethod
    def _is_short(direction: str | None) -> bool:
        return str(direction or "").strip().lower() == "short"

    def _long_baseline_stop(self, state: BrokerSteeringState) -> float | None:
        values = [value for value in [state.current_stop_loss, state.original_stop_loss] if value is not None]
        return max(values) if values else None

    def _short_baseline_stop(self, state: BrokerSteeringState) -> float | None:
        values = [value for value in [state.current_stop_loss, state.original_stop_loss] if value is not None]
        return min(values) if values else None

    def _effective_confidence(self, state: BrokerSteeringState) -> float | None:
        if state.calibrated_confidence_percent is not None:
            return state.calibrated_confidence_percent
        return state.confidence_percent

    def _manual_review(
        self,
        state: BrokerSteeringState,
        reason_codes: list[str],
        human_summary: str,
        *,
        broker_confidence: str = "low",
        config: BrokerSteeringConfig | None = None,
    ) -> BrokerSteeringDecision:
        return self._decision(
            state,
            config or BrokerSteeringConfig(),
            "manual_review_required",
            reason_codes,
            human_summary,
            execute_allowed=False,
            confidence=broker_confidence,
            requires_manual_review=True,
        )

    def _decision(
        self,
        state: BrokerSteeringState,
        config: BrokerSteeringConfig,
        decision: SteeringDecisionName,
        reason_codes: list[str],
        human_summary: str,
        *,
        execute_allowed: bool,
        confidence: str,
        requires_manual_review: bool = False,
        proposed_stop_loss: float | None = None,
        proposed_take_profit: float | None = None,
    ) -> BrokerSteeringDecision:
        if config.dry_run:
            execute_allowed = False
        return BrokerSteeringDecision(
            decision=decision,
            ticker=state.ticker,
            recommendation_plan_id=state.recommendation_plan_id,
            broker_order_id=state.broker_order_id,
            broker_position_id=state.broker_position_id,
            reason_codes=reason_codes,
            human_summary=human_summary,
            current_price=state.current_price,
            current_stop_loss=state.current_stop_loss,
            current_take_profit=state.current_take_profit,
            proposed_stop_loss=proposed_stop_loss,
            proposed_take_profit=proposed_take_profit,
            confidence=confidence,
            execute_allowed=execute_allowed and config.enabled and not config.dry_run,
            requires_manual_review=requires_manual_review,
            diagnostics={
                "direction": state.direction,
                "has_pending_order": state.has_pending_order,
                "has_open_position": state.has_open_position,
                "confidence_percent": self._effective_confidence(state),
                "broker_reconciliation_healthy": state.broker_reconciliation_healthy,
                "linked_exit_orders_missing": state.linked_exit_orders_missing,
                "expiration_at": state.expiration_at.isoformat() if state.expiration_at else None,
                "now": (state.now or datetime.now(timezone.utc)).isoformat(),
            },
        )
