from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from trade_proposer_app.domain.models import (
    RecommendationBaselineComparison,
    RecommendationBaselineSummary,
    RecommendationPlan,
)
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository


@dataclass(frozen=True)
class _BaselineDefinition:
    key: str
    label: str
    description: str
    selector: Callable[[RecommendationPlan], bool]


class RecommendationPlanBaselineService:
    def __init__(self, plans: RecommendationPlanRepository) -> None:
        self.plans = plans

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        resolved: str | None = None,
        outcome: str | None = None,
        computed_after: datetime | None = None,
        computed_before: datetime | None = None,
        limit: int = 500,
    ) -> RecommendationBaselineSummary:
        plans = self.plans.list_plans(ticker=ticker, run_id=run_id, setup_family=setup_family, resolved=resolved, outcome=outcome, computed_after=computed_after, computed_before=computed_before, limit=limit)
        comparisons = [self._build_comparison(definition, plans) for definition in self._definitions()]
        comparisons.sort(key=lambda item: (item.resolved_trade_count, item.trade_plan_count, item.win_count), reverse=True)
        family_cohorts = [self._build_comparison(definition, plans) for definition in self._family_definitions()]
        family_cohorts.sort(key=lambda item: (item.resolved_trade_count, item.trade_plan_count, item.win_count), reverse=True)
        return RecommendationBaselineSummary(
            total_plans_reviewed=len(plans),
            total_trade_plans_reviewed=sum(1 for plan in plans if self._is_trade_plan(plan)),
            comparisons=comparisons,
            family_cohorts=family_cohorts,
        )

    def _build_comparison(
        self,
        definition: _BaselineDefinition,
        plans: list[RecommendationPlan],
    ) -> RecommendationBaselineComparison:
        selected = [plan for plan in plans if definition.selector(plan)]
        trade_plans = [plan for plan in selected if self._is_trade_plan(plan)]
        resolved = [plan for plan in trade_plans if plan.latest_outcome is not None and plan.latest_outcome.outcome in {"win", "loss"}]
        wins = [plan for plan in resolved if plan.latest_outcome is not None and plan.latest_outcome.outcome == "win"]
        losses = [plan for plan in resolved if plan.latest_outcome is not None and plan.latest_outcome.outcome == "loss"]
        open_trades = [
            plan
            for plan in trade_plans
            if plan.latest_outcome is None or (plan.latest_outcome.outcome not in {"win", "loss"})
        ]
        avg_return_5d_values = [
            float(plan.latest_outcome.horizon_return_5d)
            for plan in trade_plans
            if plan.latest_outcome is not None and isinstance(plan.latest_outcome.horizon_return_5d, (int, float))
        ]
        avg_confidence_values = [float(plan.confidence_percent) for plan in trade_plans]
        return RecommendationBaselineComparison(
            key=definition.key,
            label=definition.label,
            description=definition.description,
            total_plan_count=len(selected),
            trade_plan_count=len(trade_plans),
            resolved_trade_count=len(resolved),
            win_count=len(wins),
            loss_count=len(losses),
            open_trade_count=len(open_trades),
            win_rate_percent=self._win_rate(len(wins), len(resolved)),
            average_return_5d=self._average(avg_return_5d_values),
            average_confidence_percent=self._average(avg_confidence_values),
        )

    @staticmethod
    def _definitions() -> list[_BaselineDefinition]:
        return [
            _BaselineDefinition(
                key="actual_actionable",
                label="Actual actionable plans",
                description="The redesign's current long/short plan cohort.",
                selector=lambda plan: RecommendationPlanBaselineService._is_trade_plan(plan),
            ),
            _BaselineDefinition(
                key="high_confidence_only",
                label="High-confidence only",
                description="Simple threshold baseline: only long/short plans at or above 70% confidence.",
                selector=lambda plan: RecommendationPlanBaselineService._is_trade_plan(plan) and plan.confidence_percent >= 70.0,
            ),
            _BaselineDefinition(
                key="cheap_scan_attention_leaders",
                label="Cheap-scan attention leaders",
                description="Long/short plans whose cheap-scan attention score stayed at or above 70.",
                selector=lambda plan: RecommendationPlanBaselineService._is_trade_plan(plan)
                and RecommendationPlanBaselineService._numeric_signal_value(plan, "attention_score", minimum=70.0),
            ),
            _BaselineDefinition(
                key="momentum_setup_lane",
                label="Naive momentum / breakout lane",
                description="Long/short plans in continuation, breakout, or breakdown families.",
                selector=lambda plan: RecommendationPlanBaselineService._is_trade_plan(plan)
                and RecommendationPlanBaselineService._setup_family(plan) in {"continuation", "breakout", "breakdown"},
            ),
            _BaselineDefinition(
                key="event_setup_lane",
                label="Naive catalyst / macro lane",
                description="Long/short plans in catalyst-follow-through or macro-beneficiary/loser families.",
                selector=lambda plan: RecommendationPlanBaselineService._is_trade_plan(plan)
                and RecommendationPlanBaselineService._setup_family(plan) in {"catalyst_follow_through", "macro_beneficiary_loser"},
            ),
        ]

    @staticmethod
    def _family_definitions() -> list[_BaselineDefinition]:
        families = [
            ("breakout", "Breakout cohort", "Trade plans classified as breakout setups."),
            ("continuation", "Continuation cohort", "Trade plans classified as continuation setups."),
            ("mean_reversion", "Mean-reversion cohort", "Trade plans classified as mean-reversion setups."),
            ("breakdown", "Breakdown cohort", "Trade plans classified as breakdown setups."),
            (
                "catalyst_follow_through",
                "Catalyst follow-through cohort",
                "Trade plans classified as catalyst-follow-through setups.",
            ),
            (
                "macro_beneficiary_loser",
                "Macro beneficiary / loser cohort",
                "Trade plans classified as macro-beneficiary / loser setups.",
            ),
        ]
        return [
            _BaselineDefinition(
                key=f"family__{family}",
                label=label,
                description=description,
                selector=lambda plan, family=family: RecommendationPlanBaselineService._is_trade_plan(plan)
                and RecommendationPlanBaselineService._setup_family(plan) == family,
            )
            for family, label, description in families
        ]

    @staticmethod
    def _is_trade_plan(plan: RecommendationPlan) -> bool:
        return plan.action in {"long", "short"}

    @staticmethod
    def _setup_family(plan: RecommendationPlan) -> str:
        value = plan.signal_breakdown.get("setup_family")
        return value.strip() if isinstance(value, str) and value.strip() else "uncategorized"

    @staticmethod
    def _numeric_signal_value(plan: RecommendationPlan, key: str, *, minimum: float) -> bool:
        value = plan.signal_breakdown.get(key)
        try:
            return float(value) >= minimum
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _win_rate(wins: int, resolved: int) -> float | None:
        if resolved <= 0:
            return None
        return round((wins / resolved) * 100.0, 1)

    @staticmethod
    def _average(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 3)
