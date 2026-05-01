from __future__ import annotations

import math
from dataclasses import dataclass

from trade_proposer_app.domain.models import RecommendationPlan


@dataclass(frozen=True)
class ExecutionCandidate:
    plan: RecommendationPlan
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: int
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

    def build(self, plan: RecommendationPlan, *, notional_per_plan: float, run_id: int | None = None) -> ExecutionCandidateResult:
        if plan.id is None:
            return ExecutionCandidateResult(skip_reason="missing_plan_id")
        if plan.action not in {"long", "short"}:
            return ExecutionCandidateResult(skip_reason="non_actionable")
        entry_price = self.entry_reference(plan)
        if entry_price is None or entry_price <= 0:
            return ExecutionCandidateResult(skip_reason="missing_entry_price")
        stop_loss = float(plan.stop_loss) if plan.stop_loss is not None else None
        take_profit = float(plan.take_profit) if plan.take_profit is not None else None
        if stop_loss is None or take_profit is None:
            return ExecutionCandidateResult(skip_reason="missing_exit_levels", entry_price=entry_price)
        if not self.levels_are_directionally_valid(plan.action, entry_price, stop_loss, take_profit):
            return ExecutionCandidateResult(skip_reason="invalid_trade_levels", entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit)
        quantity = int(math.floor(float(notional_per_plan) / float(entry_price)))
        if quantity < 1:
            return ExecutionCandidateResult(skip_reason="quantity_below_minimum", entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit)
        return ExecutionCandidateResult(
            candidate=ExecutionCandidate(
                plan=plan,
                entry_price=entry_price,
                stop_loss=float(stop_loss),
                take_profit=take_profit,
                quantity=quantity,
                client_order_id=self.client_order_id(plan, run_id=run_id),
            ),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    @staticmethod
    def entry_reference(plan: RecommendationPlan) -> float | None:
        if plan.entry_price_low is not None and plan.entry_price_high is not None:
            return (float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0
        if plan.entry_price_low is not None:
            return float(plan.entry_price_low)
        if plan.entry_price_high is not None:
            return float(plan.entry_price_high)
        return None

    @staticmethod
    def levels_are_directionally_valid(action: str, entry_price: float, stop_loss: float, take_profit: float) -> bool:
        if action == "long":
            return stop_loss < entry_price < take_profit
        if action == "short":
            return take_profit < entry_price < stop_loss
        return False

    @staticmethod
    def client_order_id(plan: RecommendationPlan, *, run_id: int | None) -> str:
        run_part = f"run-{run_id}" if run_id is not None else "run-none"
        plan_part = f"plan-{plan.id or 'new'}"
        return f"tp-{run_part}-{plan_part}-{plan.ticker.lower()}"
