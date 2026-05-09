from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanResolutionConfig:
    friction_pct: float = 0.0
    stop_buffer_pct: float = 0.0
    take_profit_buffer_pct: float = 0.0
    near_entry_miss_threshold_percent: float = 0.25


class PlanResolutionEngine:
    """Pure plan-crossing engine for simulated recommendation outcome resolution."""

    def __init__(self, config: PlanResolutionConfig | None = None) -> None:
        self.config = config or PlanResolutionConfig()

    def evaluate_plan(
        self,
        plan: RecommendationPlan,
        price_data: pd.DataFrame | None,
        *,
        intended_action: str | None = None,
        run_id: int | None,
        as_of: datetime | None = None,
        intraday_only: bool = False,
    ) -> RecommendationPlanOutcome:
        setup_family = self._setup_family(plan)
        confidence_bucket = self._confidence_bucket(plan.confidence_percent)
        effective_action = intended_action if plan.action in {"no_action", "watchlist"} and intended_action in {"long", "short"} else plan.action

        if effective_action not in {"long", "short"}:
            return RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome=plan.action,
                status="resolved",
                evaluated_at=datetime.now(timezone.utc),
                confidence_bucket=confidence_bucket,
                setup_family=setup_family,
                notes="Non-trade action preserved as a first-class evaluated outcome.",
                run_id=run_id,
            )
        if price_data is None or price_data.empty:
            return RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome="pending",
                status="open",
                evaluated_at=datetime.now(timezone.utc),
                confidence_bucket=confidence_bucket,
                setup_family=setup_family,
                notes="No price history available for evaluation.",
                run_id=run_id,
            )

        sliced = self.rows_on_or_after(price_data, plan.computed_at, intraday_only=intraday_only)
        if sliced.empty:
            return RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome="pending",
                status="open",
                evaluated_at=datetime.now(timezone.utc),
                confidence_bucket=confidence_bucket,
                setup_family=setup_family,
                notes="No post-plan price bars available yet.",
                run_id=run_id,
            )

        entry_reference = self.entry_reference(plan)
        entry_index = self.find_entry_index(plan, sliced)
        if entry_index is None:
            horizon_1d = self.horizon_return(effective_action, sliced, 1, entry_reference)
            horizon_3d = self.horizon_return(effective_action, sliced, 3, entry_reference)
            horizon_5d = self.horizon_return(effective_action, sliced, 5, entry_reference)
            direction_worked = self.direction_correct_from_horizons(horizon_1d, horizon_3d, horizon_5d)
            entry_miss_distance_percent = self.entry_miss_distance_percent(plan, sliced, entry_reference)
            near_entry_miss = (
                entry_miss_distance_percent is not None
                and entry_miss_distance_percent <= self.config.near_entry_miss_threshold_percent
            )
            notes = "Entry zone has not been touched yet."
            if near_entry_miss and direction_worked:
                notes += " Price came very close to entry and still moved in the forecasted direction."
            elif near_entry_miss:
                notes += " Price came very close to entry without filling."
            return RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome="phantom_no_entry" if plan.action in {"no_action", "watchlist"} else "no_entry",
                status="open",
                evaluated_at=self.last_timestamp(sliced) or datetime.now(timezone.utc),
                entry_touched=False,
                horizon_return_1d=horizon_1d,
                horizon_return_3d=horizon_3d,
                horizon_return_5d=horizon_5d,
                entry_miss_distance_percent=entry_miss_distance_percent,
                near_entry_miss=near_entry_miss,
                direction_worked_without_entry=direction_worked,
                direction_correct=direction_worked,
                confidence_bucket=confidence_bucket,
                setup_family=setup_family,
                notes=notes,
                run_id=run_id,
            )

        active = sliced.iloc[entry_index:]
        first_stop_hit, first_take_hit, decisive_timestamp = self.resolve_exit(effective_action, plan, active)
        realized_holding = self.realized_holding_days(plan.computed_at, decisive_timestamp or self.last_timestamp(active))
        mfe = self.max_favorable_excursion(effective_action, active, entry_reference)
        mae = self.max_adverse_excursion(effective_action, active, entry_reference)
        horizon_1d = self.horizon_return(effective_action, active, 1, entry_reference)
        horizon_3d = self.horizon_return(effective_action, active, 3, entry_reference)
        horizon_5d = self.horizon_return(effective_action, active, 5, entry_reference)
        direction_correct = self.direction_correct_from_horizons(horizon_1d, horizon_3d, horizon_5d)
        outcome = "phantom_pending" if plan.action in {"no_action", "watchlist"} else "open"
        status = "open"
        notes = "Entry touched; waiting for stop, take, or more bars."
        if first_take_hit and not first_stop_hit:
            outcome = "phantom_win" if plan.action in {"no_action", "watchlist"} else "win"
            status = "resolved"
            notes = "Take profit was reached before stop loss."
        elif first_stop_hit and not first_take_hit:
            outcome = "phantom_loss" if plan.action in {"no_action", "watchlist"} else "loss"
            status = "resolved"
            notes = "Stop loss was reached before take profit."
        elif first_stop_hit and first_take_hit:
            outcome = "phantom_loss" if plan.action in {"no_action", "watchlist"} else "loss"
            status = "resolved"
            notes = "Stop loss and take profit were both touched on the same bar; conservative resolution marked as loss."

        return RecommendationPlanOutcome(
            recommendation_plan_id=plan.id or 0,
            ticker=plan.ticker,
            action=plan.action,
            outcome=outcome,
            status=status,
            evaluated_at=decisive_timestamp or self.last_timestamp(active) or datetime.now(timezone.utc),
            entry_touched=True,
            stop_loss_hit=first_stop_hit,
            take_profit_hit=first_take_hit,
            horizon_return_1d=horizon_1d,
            horizon_return_3d=horizon_3d,
            horizon_return_5d=horizon_5d,
            max_favorable_excursion=mfe,
            max_adverse_excursion=mae,
            realized_holding_period_days=realized_holding,
            direction_correct=direction_correct,
            confidence_bucket=confidence_bucket,
            setup_family=setup_family,
            notes=notes,
            run_id=run_id,
        )

    def resolve_exit(self, effective_action: str, plan: RecommendationPlan, data: pd.DataFrame) -> tuple[bool, bool, datetime | None]:
        stop_buffer = self.config.stop_buffer_pct / 100.0
        take_buffer = self.config.take_profit_buffer_pct / 100.0
        for timestamp, row in data.iterrows():
            row_high = self.float_or_none(row.get("High"))
            row_low = self.float_or_none(row.get("Low"))
            if row_high is None or row_low is None:
                continue
            stop_hit = self.check_stop_with_buffer(effective_action, row_high, row_low, plan.stop_loss, stop_buffer)
            take_hit = self.check_take_with_buffer(effective_action, row_high, row_low, plan.take_profit, take_buffer)
            if stop_hit or take_hit:
                return stop_hit, take_hit, self.normalize_datetime(timestamp)
        return False, False, None

    @staticmethod
    def _setup_family(plan: RecommendationPlan) -> str:
        value = plan.signal_breakdown.get("setup_family")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "uncategorized"

    @staticmethod
    def _confidence_bucket(confidence_percent: float) -> str:
        if confidence_percent >= 80:
            return "80_plus"
        if confidence_percent >= 65:
            return "65_to_79"
        if confidence_percent >= 50:
            return "50_to_64"
        return "below_50"

    @staticmethod
    def entry_reference(plan: RecommendationPlan) -> float:
        low = float(plan.entry_price_low or 0.0)
        high = float(plan.entry_price_high if plan.entry_price_high is not None else low)
        if low and high:
            return (low + high) / 2.0
        return high or low or 0.0

    @classmethod
    def find_entry_index(cls, plan: RecommendationPlan, data: pd.DataFrame) -> int | None:
        low = float(plan.entry_price_low if plan.entry_price_low is not None else plan.entry_price_high or 0.0)
        high = float(plan.entry_price_high if plan.entry_price_high is not None else plan.entry_price_low or 0.0)
        if high < low:
            low, high = high, low
        for index, (_, row) in enumerate(data.iterrows()):
            row_high = cls.float_or_none(row.get("High"))
            row_low = cls.float_or_none(row.get("Low"))
            if row_high is None or row_low is None:
                continue
            if row_low <= high and row_high >= low:
                return index
        return None

    @staticmethod
    def check_stop_with_buffer(action: str, high: float, low: float, stop_loss: float | None, buffer_pct: float) -> bool:
        if stop_loss is None:
            return False
        buffer = stop_loss * buffer_pct
        if action == "long":
            return low <= (stop_loss + buffer)
        if action == "short":
            return high >= (stop_loss - buffer)
        return False

    @staticmethod
    def check_take_with_buffer(action: str, high: float, low: float, take_profit: float | None, buffer_pct: float) -> bool:
        if take_profit is None:
            return False
        buffer = take_profit * buffer_pct
        if action == "long":
            return high >= (take_profit + buffer)
        if action == "short":
            return low <= (take_profit - buffer)
        return False

    def horizon_return(self, effective_action: str, data: pd.DataFrame, sessions: int, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        close_index = min(max(sessions - 1, 0), len(data) - 1)
        close_value = self.float_or_none(data.iloc[close_index].get("Close"))
        if close_value is None:
            return None
        raw_return = ((close_value - entry_reference) / entry_reference) * 100.0
        if effective_action == "short":
            return round(-raw_return - self.config.friction_pct, 4)
        return round(raw_return - self.config.friction_pct, 4)

    @classmethod
    def max_favorable_excursion(cls, effective_action: str, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        if effective_action == "short":
            values = [cls.float_or_none(row.get("Low")) for _, row in data.iterrows()]
            numeric = [value for value in values if value is not None]
            return None if not numeric else round(((entry_reference - min(numeric)) / entry_reference) * 100.0, 4)
        values = [cls.float_or_none(row.get("High")) for _, row in data.iterrows()]
        numeric = [value for value in values if value is not None]
        return None if not numeric else round(((max(numeric) - entry_reference) / entry_reference) * 100.0, 4)

    @classmethod
    def max_adverse_excursion(cls, effective_action: str, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        if effective_action == "short":
            values = [cls.float_or_none(row.get("High")) for _, row in data.iterrows()]
            numeric = [value for value in values if value is not None]
            return None if not numeric else round(((max(numeric) - entry_reference) / entry_reference) * 100.0, 4)
        values = [cls.float_or_none(row.get("Low")) for _, row in data.iterrows()]
        numeric = [value for value in values if value is not None]
        return None if not numeric else round(((entry_reference - min(numeric)) / entry_reference) * 100.0, 4)

    @staticmethod
    def entry_zone_bounds(plan: RecommendationPlan) -> tuple[float, float] | None:
        low = float(plan.entry_price_low if plan.entry_price_low is not None else plan.entry_price_high or 0.0)
        high = float(plan.entry_price_high if plan.entry_price_high is not None else plan.entry_price_low or 0.0)
        if low <= 0.0 and high <= 0.0:
            return None
        if high < low:
            low, high = high, low
        return low, high

    @classmethod
    def entry_miss_distance_percent(cls, plan: RecommendationPlan, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        bounds = cls.entry_zone_bounds(plan)
        if bounds is None:
            return None
        low, high = bounds
        closest_distance: float | None = None
        for _, row in data.iterrows():
            row_high = cls.float_or_none(row.get("High"))
            row_low = cls.float_or_none(row.get("Low"))
            if row_high is None or row_low is None:
                continue
            if row_low <= high and row_high >= low:
                return 0.0
            distance = low - row_high if row_high < low else row_low - high if row_low > high else 0.0
            if closest_distance is None or distance < closest_distance:
                closest_distance = distance
        if closest_distance is None:
            return None
        return round((closest_distance / entry_reference) * 100.0, 4)

    @staticmethod
    def direction_correct_from_horizons(horizon_1d: float | None, horizon_3d: float | None, horizon_5d: float | None) -> bool | None:
        for candidate in (horizon_5d, horizon_3d, horizon_1d):
            if candidate is not None:
                return candidate > 0
        return None

    @classmethod
    def rows_on_or_after(cls, data: pd.DataFrame, start_at: datetime, *, intraday_only: bool = False) -> pd.DataFrame:
        normalized_start = cls.normalize_datetime(start_at)
        if normalized_start is None:
            return pd.DataFrame(columns=data.columns)
        if "available_at" in data.columns:
            normalized_available = data["available_at"].apply(cls.normalize_datetime)
            mask = normalized_available.map(lambda value: value is not None and value >= normalized_start)
            rows = data.loc[mask]
            if not rows.empty:
                return rows
            if not intraday_only:
                date_mask = data.index.map(
                    lambda timestamp: (
                        (normalized_timestamp := cls.normalize_datetime(timestamp)) is not None
                        and normalized_timestamp.date() >= normalized_start.date()
                    )
                )
                fallback_rows = data.loc[date_mask]
                if not fallback_rows.empty:
                    return fallback_rows
            return pd.DataFrame(columns=data.columns)
        indexes = [timestamp for timestamp, _ in data.iterrows() if (normalized := cls.normalize_datetime(timestamp)) is not None and normalized >= normalized_start]
        return data.loc[indexes] if indexes else pd.DataFrame(columns=data.columns)

    @classmethod
    def last_timestamp(cls, data: pd.DataFrame) -> datetime | None:
        if data.empty:
            return None
        if "available_at" in data.columns:
            available = cls.normalize_datetime(data.iloc[-1].get("available_at"))
            if available is not None:
                return available
        return cls.normalize_datetime(data.index[-1])

    @classmethod
    def realized_holding_days(cls, start_at: datetime, end_at: datetime | None) -> float | None:
        if end_at is None:
            return None
        normalized_start = cls.normalize_datetime(start_at)
        normalized_end = cls.normalize_datetime(end_at)
        if normalized_start is None or normalized_end is None:
            return None
        return round(max(0.0, (normalized_end - normalized_start).total_seconds() / 86400.0), 4)

    @staticmethod
    def float_or_none(value: object) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def normalize_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, pd.Timestamp):
            dt = value.to_pydatetime()
        elif isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = pd.to_datetime(value).to_pydatetime()
            except Exception:
                return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
