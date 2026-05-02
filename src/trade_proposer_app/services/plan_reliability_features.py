from __future__ import annotations

from dataclasses import dataclass

from trade_proposer_app.domain.models import RecommendationDecisionSample, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.services.execution_candidates import ExecutionCandidateBuilder


@dataclass(frozen=True)
class PlanReliabilityFeatures:
    plan_id: int
    ticker: str
    action: str
    intended_action: str | None
    setup_family: str
    context_bias: str | None
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_percent: float
    reward_percent: float
    outcome: str
    stop_loss_hit: bool
    take_profit_hit: bool
    max_favorable_excursion: float
    max_adverse_excursion: float


class PlanReliabilityFeatureBuilder:
    """Builds reusable plan/outcome features for tuning, search, and calibration."""

    ACTIONS = {"long", "short", "no_action", "watchlist"}
    DIRECT_TRADE_ACTIONS = {"long", "short"}
    PHANTOM_TRADE_ACTIONS = {"no_action", "watchlist"}

    def build(
        self,
        plan: RecommendationPlan,
        outcome: RecommendationPlanOutcome,
        sample: RecommendationDecisionSample | None = None,
    ) -> PlanReliabilityFeatures | None:
        if plan.id is None or (plan.action or "") not in self.ACTIONS:
            return None
        is_direct_trade = plan.action in self.DIRECT_TRADE_ACTIONS
        is_phantom_trade = plan.action in self.PHANTOM_TRADE_ACTIONS
        is_broker_resolved = outcome.outcome_source == "broker"
        if is_direct_trade and outcome.outcome not in {"win", "loss"}:
            return None
        if is_phantom_trade and outcome.outcome not in {"phantom_win", "phantom_loss"}:
            return None
        signal_breakdown = self._as_dict(plan.signal_breakdown)
        intended_action = str(signal_breakdown.get("intended_action") or "").strip().lower() or None
        if is_phantom_trade and intended_action not in self.DIRECT_TRADE_ACTIONS:
            return None
        entry = ExecutionCandidateBuilder.entry_reference(plan)
        if entry is None or entry <= 0 or plan.stop_loss is None or plan.take_profit is None:
            return None
        stop_hit = outcome.stop_loss_hit
        take_hit = outcome.take_profit_hit
        if stop_hit is None or take_hit is None:
            if not is_broker_resolved:
                return None
            if outcome.realized_return_pct is None:
                return None
            realized_return = float(outcome.realized_return_pct)
            if realized_return == 0:
                return None
            stop_hit = realized_return < 0
            take_hit = realized_return > 0
            max_favorable_excursion = abs(realized_return) if realized_return > 0 else 0.0
            max_adverse_excursion = abs(realized_return) if realized_return < 0 else 0.0
        else:
            max_favorable_excursion = outcome.max_favorable_excursion
            max_adverse_excursion = outcome.max_adverse_excursion
        if bool(stop_hit) == bool(take_hit):
            return None
        stop_loss = float(plan.stop_loss)
        take_profit = float(plan.take_profit)
        risk_percent = abs((entry - stop_loss) / entry) * 100.0
        reward_percent = abs((take_profit - entry) / entry) * 100.0
        if risk_percent <= 0 or reward_percent <= 0:
            return None
        transmission_summary = self._as_dict(signal_breakdown.get("transmission_summary"))
        setup_family = self._setup_family(plan=plan, outcome=outcome, sample=sample, signal_breakdown=signal_breakdown)
        return PlanReliabilityFeatures(
            plan_id=plan.id,
            ticker=plan.ticker,
            action=plan.action,
            intended_action=intended_action,
            setup_family=setup_family,
            context_bias=str(transmission_summary.get("context_bias") or "").strip().lower() or None,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_percent=risk_percent,
            reward_percent=reward_percent,
            outcome=outcome.outcome,
            stop_loss_hit=bool(stop_hit),
            take_profit_hit=bool(take_hit),
            max_favorable_excursion=float(max_favorable_excursion or 0.0),
            max_adverse_excursion=float(max_adverse_excursion or 0.0),
        )

    @staticmethod
    def _as_dict(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        return {}

    @staticmethod
    def _setup_family(
        *,
        plan: RecommendationPlan,
        outcome: RecommendationPlanOutcome,
        sample: RecommendationDecisionSample | None,
        signal_breakdown: dict[str, object],
    ) -> str:
        candidates = [
            signal_breakdown.get("setup_family"),
            sample.setup_family if sample is not None else None,
            outcome.setup_family,
        ]
        for candidate in candidates:
            value = str(candidate or "").strip().lower()
            if value:
                return value
        return "uncategorized"
