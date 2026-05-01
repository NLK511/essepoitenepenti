from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.statuses import BROKER_RESOLVED_POSITION_STATUSES, OutcomeStatus, TradeOutcome
from trade_proposer_app.persistence.models import BrokerPositionRecord
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository


@dataclass(frozen=True)
class BrokerClosedPositionSummary:
    closed_positions: int
    wins: int
    losses: int
    win_rate_percent: float | None
    realized_pnl: float
    average_return_percent: float | None
    average_r_multiple: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "closed_positions": self.closed_positions,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_percent": self.win_rate_percent,
            "realized_pnl": self.realized_pnl,
            "average_return_percent": self.average_return_percent,
            "average_r_multiple": self.average_r_multiple,
        }


@dataclass(frozen=True)
class EffectiveOutcomeSummary:
    total_outcomes: int
    resolved_outcomes: int
    open_outcomes: int
    wins: int
    losses: int
    win_rate_percent: float | None
    broker_outcomes: int
    simulation_outcomes: int
    plan_outcomes: int
    realized_pnl: float
    average_return_percent: float | None
    average_r_multiple: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "total_outcomes": self.total_outcomes,
            "resolved_outcomes": self.resolved_outcomes,
            "open_outcomes": self.open_outcomes,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_percent": self.win_rate_percent,
            "broker_outcomes": self.broker_outcomes,
            "simulation_outcomes": self.simulation_outcomes,
            "plan_outcomes": self.plan_outcomes,
            "realized_pnl": self.realized_pnl,
            "average_return_percent": self.average_return_percent,
            "average_r_multiple": self.average_r_multiple,
        }


class TradingPerformanceMetricsService:
    """Shared performance metric definitions for broker and effective outcomes."""

    def __init__(self, session: Session, effective_outcomes: EffectivePlanOutcomeRepository | None = None) -> None:
        self.session = session
        self.effective_outcomes = effective_outcomes or EffectivePlanOutcomeRepository(session)

    def summarize_broker_closed_positions(
        self,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
    ) -> BrokerClosedPositionSummary:
        before = self._normalize_datetime(evaluated_before) if evaluated_before is not None else datetime.now(timezone.utc)
        query = select(BrokerPositionRecord).where(BrokerPositionRecord.status.in_(BROKER_RESOLVED_POSITION_STATUSES))
        if evaluated_after is not None:
            query = query.where(BrokerPositionRecord.exit_filled_at >= self._normalize_datetime(evaluated_after))
        query = query.where(BrokerPositionRecord.exit_filled_at <= before)
        positions = self.session.scalars(query).all()
        wins = sum(1 for position in positions if position.status == TradeOutcome.WIN.value)
        losses = sum(1 for position in positions if position.status == TradeOutcome.LOSS.value)
        closed = wins + losses
        returns = [float(position.realized_return_pct) for position in positions if position.realized_return_pct is not None]
        r_multiples = [float(position.realized_r_multiple) for position in positions if position.realized_r_multiple is not None]
        return BrokerClosedPositionSummary(
            closed_positions=closed,
            wins=wins,
            losses=losses,
            win_rate_percent=self._percentage(wins, closed),
            realized_pnl=round(sum(float(position.realized_pnl or 0.0) for position in positions), 4),
            average_return_percent=self._average(returns, digits=2),
            average_r_multiple=self._average(r_multiples, digits=4),
        )

    def summarize_effective_outcomes(
        self,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500_000,
    ) -> EffectiveOutcomeSummary:
        outcomes = self.effective_outcomes.list_outcomes(
            evaluated_after=evaluated_after,
            evaluated_before=evaluated_before,
            limit=limit,
        )
        resolved = [item for item in outcomes if item.status == OutcomeStatus.RESOLVED.value and item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        wins = sum(1 for item in resolved if item.outcome == TradeOutcome.WIN.value)
        losses = sum(1 for item in resolved if item.outcome == TradeOutcome.LOSS.value)
        returns = [float(item.realized_return_pct) for item in resolved if item.realized_return_pct is not None]
        r_multiples = [float(item.realized_r_multiple) for item in resolved if item.realized_r_multiple is not None]
        return EffectiveOutcomeSummary(
            total_outcomes=len(outcomes),
            resolved_outcomes=len(resolved),
            open_outcomes=sum(1 for item in outcomes if item.status != OutcomeStatus.RESOLVED.value),
            wins=wins,
            losses=losses,
            win_rate_percent=self._percentage(wins, len(resolved)),
            broker_outcomes=sum(1 for item in outcomes if item.outcome_source == "broker"),
            simulation_outcomes=sum(1 for item in outcomes if item.outcome_source == "simulation"),
            plan_outcomes=sum(1 for item in outcomes if item.outcome_source == "plan"),
            realized_pnl=round(sum(float(item.realized_pnl or 0.0) for item in resolved), 4),
            average_return_percent=self._average(returns, digits=2),
            average_r_multiple=self._average(r_multiples, digits=4),
        )

    @staticmethod
    def _percentage(part: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round((part / total) * 100.0, 1)

    @staticmethod
    def _average(values: list[float], *, digits: int) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), digits)

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
