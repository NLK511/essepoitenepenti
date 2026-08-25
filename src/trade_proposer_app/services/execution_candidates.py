from __future__ import annotations

import math
from dataclasses import dataclass

from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.services.finite_numbers import finite_float


@dataclass(frozen=True)
class ExecutionCandidate:
    plan: RecommendationPlan
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: int
    notional_amount: float
    client_order_id: str

    @property
    def side(self) -> str:
        return "buy" if self.plan.action == "long" else "sell"


@dataclass(frozen=True)
class ExecutionCandidateResult:
    candidate: ExecutionCandidate | None = None
    skip_reason: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    @property
    def is_candidate(self) -> bool:
        return self.candidate is not None


class ExecutionCandidateBuilder:
    """Builds broker-eligible execution candidates from immutable recommendation plans."""

    def build(
        self,
        plan: RecommendationPlan,
        *,
        notional_per_plan: float,
        run_id: int | None = None,
        allow_amount_sizing: bool = False,
    ) -> ExecutionCandidateResult:
        if plan.id is None:
            return ExecutionCandidateResult(skip_reason="missing_plan_id")
        if plan.action not in {"long", "short"}:
            return ExecutionCandidateResult(skip_reason="non_actionable")
        if not self.execution_eligible(plan):
            return ExecutionCandidateResult(skip_reason="not_execution_eligible")
        entry_price = self.entry_reference(plan)
        if entry_price is None or entry_price <= 0:
            return ExecutionCandidateResult(skip_reason="missing_entry_price")
        if not math.isfinite(entry_price):
            return ExecutionCandidateResult(skip_reason="non_finite_trade_levels")
        stop_loss = finite_float(plan.stop_loss)
        take_profit = finite_float(plan.take_profit)
        if stop_loss is None or take_profit is None:
            if plan.stop_loss is not None or plan.take_profit is not None:
                return ExecutionCandidateResult(
                    skip_reason="non_finite_trade_levels", entry_price=entry_price
                )
            return ExecutionCandidateResult(
                skip_reason="missing_exit_levels", entry_price=entry_price
            )
        if not self.levels_are_directionally_valid(
            plan.action, entry_price, stop_loss, take_profit
        ):
            return ExecutionCandidateResult(
                skip_reason="invalid_trade_levels",
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        adjusted_notional = self.adjusted_notional_amount(plan, notional_per_plan)
        quantity = int(math.floor(float(adjusted_notional) / float(entry_price)))
        if quantity < 1 and not allow_amount_sizing:
            return ExecutionCandidateResult(
                skip_reason="quantity_below_minimum",
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        return ExecutionCandidateResult(
            candidate=ExecutionCandidate(
                plan=plan,
                entry_price=entry_price,
                stop_loss=float(stop_loss),
                take_profit=take_profit,
                quantity=max(0, quantity),
                notional_amount=round(float(adjusted_notional), 4),
                client_order_id=self.client_order_id(plan, run_id=run_id),
            ),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    @staticmethod
    def execution_eligible(plan: RecommendationPlan) -> bool:
        breakdown = plan.signal_breakdown
        if hasattr(breakdown, "get") and breakdown.get("execution_eligible") is False:
            return False
        if hasattr(breakdown, "get") and breakdown.get("decision_tier") in {
            "research_plan",
            "shadow_observation",
            "discarded",
        }:
            return False
        return True

    @staticmethod
    def entry_reference(plan: RecommendationPlan) -> float | None:
        low = finite_float(plan.entry_price_low)
        high = finite_float(plan.entry_price_high)
        if low is not None and high is not None:
            return (low + high) / 2.0
        if low is not None:
            return low
        if high is not None:
            return high
        if plan.entry_price_low is not None or plan.entry_price_high is not None:
            return float("nan")
        return None

    @staticmethod
    def levels_are_directionally_valid(
        action: str, entry_price: float, stop_loss: float, take_profit: float
    ) -> bool:
        if not all(math.isfinite(value) for value in (entry_price, stop_loss, take_profit)):
            return False
        if action == "long":
            return stop_loss < entry_price < take_profit
        if action == "short":
            return take_profit < entry_price < stop_loss
        return False

    @staticmethod
    def adjusted_notional_amount(plan: RecommendationPlan, notional_per_plan: float) -> float:
        multiplier = 1.0
        breakdown = plan.signal_breakdown
        if hasattr(breakdown, "get"):
            try:
                multiplier = float(breakdown.get("position_size_multiplier"))
            except (TypeError, ValueError):
                multiplier = 1.0
        multiplier = max(0.0, min(1.0, multiplier))
        return max(0.0, float(notional_per_plan) * multiplier)

    @staticmethod
    def client_order_id(plan: RecommendationPlan, *, run_id: int | None) -> str:
        run_part = f"run-{run_id}" if run_id is not None else "run-none"
        plan_part = f"plan-{plan.id or 'new'}"
        return f"tp-{run_part}-{plan_part}-{plan.ticker.lower()}"
