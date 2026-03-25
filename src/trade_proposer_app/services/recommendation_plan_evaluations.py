from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import EvaluationRunResult, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository


class RecommendationPlanEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.plans = RecommendationPlanRepository(session)
        self.outcomes = RecommendationOutcomeRepository(session)

    def run_evaluation(self, recommendation_plan_ids: list[int] | None = None, *, run_id: int | None = None) -> EvaluationRunResult:
        plans = self._list_plans(recommendation_plan_ids)
        if not plans:
            return EvaluationRunResult(output="no recommendation plans available for evaluation")

        price_history_cache, price_errors = self._prepare_price_histories(plans)
        processed = 0
        synced = 0
        detail_lines: list[str] = []
        outcome_labels: list[str] = []

        for plan in plans:
            processed += 1
            price_data = price_history_cache.get(plan.ticker)
            outcome = self._evaluate_plan(plan, price_data, run_id=run_id)
            stored = self.outcomes.upsert_outcome(outcome)
            synced += 1
            outcome_labels.append(stored.outcome)
            detail_lines.append(f"{plan.ticker}: {stored.outcome} ({stored.status})")

        output = self._build_output(processed, detail_lines, price_errors)
        return EvaluationRunResult(
            evaluated_recommendation_plans=processed,
            synced_recommendation_plan_outcomes=synced,
            pending_recommendation_plan_outcomes=sum(1 for value in outcome_labels if value in {"open", "pending", "no_entry"}),
            win_recommendation_plan_outcomes=sum(1 for value in outcome_labels if value == "win"),
            loss_recommendation_plan_outcomes=sum(1 for value in outcome_labels if value == "loss"),
            no_action_recommendation_plan_outcomes=sum(1 for value in outcome_labels if value == "no_action"),
            watchlist_recommendation_plan_outcomes=sum(1 for value in outcome_labels if value == "watchlist"),
            output=output,
        )

    def _list_plans(self, recommendation_plan_ids: list[int] | None) -> list[RecommendationPlan]:
        query = select(RecommendationPlanRecord)
        if recommendation_plan_ids:
            query = query.where(RecommendationPlanRecord.id.in_(recommendation_plan_ids))
        rows = list(self.session.scalars(query).all())
        if not recommendation_plan_ids:
            rows = [row for row in rows if row.action in {"long", "short", "no_action", "watchlist"}]
        return [self.plans._to_model(row) for row in rows]

    def _prepare_price_histories(self, plans: list[RecommendationPlan]) -> tuple[dict[str, pd.DataFrame | None], list[str]]:
        groups = self._group_by_ticker(plans)
        cache: dict[str, pd.DataFrame | None] = {}
        errors: list[str] = []
        end_time = datetime.now(timezone.utc)
        for ticker, grouped_plans in groups.items():
            earliest = min(plan.computed_at for plan in grouped_plans)
            start_time = earliest - timedelta(days=2)
            try:
                data = self._download_price_history(ticker, start_time, end_time)
            except Exception as exc:  # pragma: no cover
                cache[ticker] = None
                errors.append(f"{ticker}: {exc}")
                continue
            if data is None or data.empty:
                cache[ticker] = None
                errors.append(f"{ticker}: price history is unavailable")
                continue
            cache[ticker] = data.sort_index()
        return cache, errors

    @staticmethod
    def _group_by_ticker(plans: Iterable[RecommendationPlan]) -> dict[str, list[RecommendationPlan]]:
        groups: dict[str, list[RecommendationPlan]] = defaultdict(list)
        for plan in plans:
            groups[(plan.ticker or "").strip().upper()].append(plan)
        return groups

    def _evaluate_plan(
        self,
        plan: RecommendationPlan,
        price_data: pd.DataFrame | None,
        *,
        run_id: int | None,
    ) -> RecommendationPlanOutcome:
        setup_family = self._setup_family(plan)
        confidence_bucket = self._confidence_bucket(plan.confidence_percent)
        if plan.action in {"no_action", "watchlist"}:
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

        sliced = self._rows_on_or_after(price_data, plan.computed_at)
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

        entry_reference = self._entry_reference(plan)
        entry_index = self._find_entry_index(plan, sliced)
        if entry_index is None:
            return RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome="no_entry",
                status="open",
                evaluated_at=self._last_timestamp(sliced) or datetime.now(timezone.utc),
                entry_touched=False,
                horizon_return_1d=self._horizon_return(plan, sliced, 1, entry_reference),
                horizon_return_3d=self._horizon_return(plan, sliced, 3, entry_reference),
                horizon_return_5d=self._horizon_return(plan, sliced, 5, entry_reference),
                confidence_bucket=confidence_bucket,
                setup_family=setup_family,
                notes="Entry zone has not been touched yet.",
                run_id=run_id,
            )

        active = sliced.iloc[entry_index:]
        first_stop_hit, first_take_hit, decisive_timestamp = self._resolve_exit(plan, active)
        realized_holding = self._realized_holding_days(plan.computed_at, decisive_timestamp or self._last_timestamp(active))
        mfe = self._max_favorable_excursion(plan, active, entry_reference)
        mae = self._max_adverse_excursion(plan, active, entry_reference)
        horizon_1d = self._horizon_return(plan, active, 1, entry_reference)
        horizon_3d = self._horizon_return(plan, active, 3, entry_reference)
        horizon_5d = self._horizon_return(plan, active, 5, entry_reference)
        direction_correct = None
        for candidate in (horizon_5d, horizon_3d, horizon_1d):
            if candidate is not None:
                direction_correct = candidate > 0
                break
        outcome = "open"
        status = "open"
        notes = "Entry touched; waiting for stop, take, or more bars."
        if first_take_hit and not first_stop_hit:
            outcome = "win"
            status = "resolved"
            notes = "Take profit was reached before stop loss."
        elif first_stop_hit and not first_take_hit:
            outcome = "loss"
            status = "resolved"
            notes = "Stop loss was reached before take profit."
        elif first_stop_hit and first_take_hit:
            outcome = "loss"
            status = "resolved"
            notes = "Stop loss and take profit were both touched on the same bar; conservative resolution marked as loss."

        return RecommendationPlanOutcome(
            recommendation_plan_id=plan.id or 0,
            ticker=plan.ticker,
            action=plan.action,
            outcome=outcome,
            status=status,
            evaluated_at=decisive_timestamp or self._last_timestamp(active) or datetime.now(timezone.utc),
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
    def _entry_reference(plan: RecommendationPlan) -> float:
        low = float(plan.entry_price_low or 0.0)
        high = float(plan.entry_price_high if plan.entry_price_high is not None else low)
        if low and high:
            return (low + high) / 2.0
        return high or low or 0.0

    def _find_entry_index(self, plan: RecommendationPlan, data: pd.DataFrame) -> int | None:
        low = float(plan.entry_price_low if plan.entry_price_low is not None else plan.entry_price_high or 0.0)
        high = float(plan.entry_price_high if plan.entry_price_high is not None else plan.entry_price_low or 0.0)
        if high < low:
            low, high = high, low
        for index, (_, row) in enumerate(data.iterrows()):
            row_high = self._float_or_none(row.get("High"))
            row_low = self._float_or_none(row.get("Low"))
            if row_high is None or row_low is None:
                continue
            if row_low <= high and row_high >= low:
                return index
        return None

    def _resolve_exit(self, plan: RecommendationPlan, data: pd.DataFrame) -> tuple[bool, bool, datetime | None]:
        for timestamp, row in data.iterrows():
            row_high = self._float_or_none(row.get("High"))
            row_low = self._float_or_none(row.get("Low"))
            if row_high is None or row_low is None:
                continue
            stop_hit = self._check_stop(plan.action, row_high, row_low, plan.stop_loss)
            take_hit = self._check_take(plan.action, row_high, row_low, plan.take_profit)
            if stop_hit or take_hit:
                return stop_hit, take_hit, self._normalize_datetime(timestamp)
        return False, False, None

    @staticmethod
    def _check_stop(action: str, high: float, low: float, stop_loss: float | None) -> bool:
        if stop_loss is None:
            return False
        if action == "long":
            return low <= stop_loss
        if action == "short":
            return high >= stop_loss
        return False

    @staticmethod
    def _check_take(action: str, high: float, low: float, take_profit: float | None) -> bool:
        if take_profit is None:
            return False
        if action == "long":
            return high >= take_profit
        if action == "short":
            return low <= take_profit
        return False

    def _horizon_return(
        self,
        plan: RecommendationPlan,
        data: pd.DataFrame,
        sessions: int,
        entry_reference: float,
    ) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        close_index = min(max(sessions - 1, 0), len(data) - 1)
        close_value = self._float_or_none(data.iloc[close_index].get("Close"))
        if close_value is None:
            return None
        raw_return = ((close_value - entry_reference) / entry_reference) * 100.0
        if plan.action == "short":
            return round(-raw_return, 4)
        return round(raw_return, 4)

    def _max_favorable_excursion(self, plan: RecommendationPlan, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        if plan.action == "short":
            lows = [self._float_or_none(row.get("Low")) for _, row in data.iterrows()]
            numeric_lows = [value for value in lows if value is not None]
            if not numeric_lows:
                return None
            candidate = min(numeric_lows)
            return round(((entry_reference - candidate) / entry_reference) * 100.0, 4)
        highs = [self._float_or_none(row.get("High")) for _, row in data.iterrows()]
        numeric_highs = [value for value in highs if value is not None]
        if not numeric_highs:
            return None
        candidate = max(numeric_highs)
        return round(((candidate - entry_reference) / entry_reference) * 100.0, 4)

    def _max_adverse_excursion(self, plan: RecommendationPlan, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        if plan.action == "short":
            highs = [self._float_or_none(row.get("High")) for _, row in data.iterrows()]
            numeric_highs = [value for value in highs if value is not None]
            if not numeric_highs:
                return None
            candidate = max(numeric_highs)
            return round(((candidate - entry_reference) / entry_reference) * 100.0, 4)
        lows = [self._float_or_none(row.get("Low")) for _, row in data.iterrows()]
        numeric_lows = [value for value in lows if value is not None]
        if not numeric_lows:
            return None
        candidate = min(numeric_lows)
        return round(((entry_reference - candidate) / entry_reference) * 100.0, 4)

    @staticmethod
    def _last_timestamp(data: pd.DataFrame) -> datetime | None:
        if data.empty:
            return None
        return RecommendationPlanEvaluationService._normalize_datetime(data.index[-1])

    @staticmethod
    def _rows_on_or_after(data: pd.DataFrame, start_at: datetime) -> pd.DataFrame:
        normalized_start = RecommendationPlanEvaluationService._normalize_datetime(start_at) or start_at
        rows = []
        for timestamp, row in data.iterrows():
            normalized_timestamp = RecommendationPlanEvaluationService._normalize_datetime(timestamp)
            if normalized_timestamp is None or normalized_timestamp < normalized_start:
                continue
            rows.append((timestamp, row))
        if not rows:
            return pd.DataFrame(columns=data.columns)
        indexes = [timestamp for timestamp, _ in rows]
        return data.loc[indexes]

    @staticmethod
    def _realized_holding_days(start_at: datetime, end_at: datetime | None) -> float | None:
        if end_at is None:
            return None
        normalized_start = RecommendationPlanEvaluationService._normalize_datetime(start_at)
        normalized_end = RecommendationPlanEvaluationService._normalize_datetime(end_at)
        if normalized_start is None or normalized_end is None:
            return None
        return round(max(0.0, (normalized_end - normalized_start).total_seconds() / 86400.0), 4)

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = value.to_pydatetime()
            except AttributeError:
                return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _download_price_history(ticker: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
        return yf.download(
            ticker,
            start=start_str,
            end=end_str,
            interval="1d",
            progress=False,
            auto_adjust=False,
        )

    @staticmethod
    def _build_output(processed: int, details: list[str], errors: list[str]) -> str:
        parts: list[str] = []
        if processed:
            parts.append(f"Processed {processed} recommendation plan{'s' if processed != 1 else ''}.")
        parts.extend(errors)
        parts.extend(details)
        return " ".join(parts) if parts else "no recommendation plans were evaluated"
