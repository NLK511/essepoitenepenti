from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import EvaluationRunResult, HistoricalMarketBar, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


logger = logging.getLogger(__name__)


class RecommendationPlanEvaluationService:
    _preferred_timeframes = ("1d", "1wk", "1mo", "1h", "60m", "30m", "15m", "5m", "2m", "1m")
    _intraday_timeframes = ("1m", "2m", "5m", "15m", "30m", "60m", "1h")
    _intraday_interval = "5m"
    _market_open_time = time(9, 30)
    _market_close_time = time(16, 0)
    _market_timezone_by_region = {
        "US": "America/New_York",
        "USA": "America/New_York",
        "CA": "America/Toronto",
        "CANADA": "America/Toronto",
        "UK": "Europe/London",
        "GB": "Europe/London",
        "DE": "Europe/Berlin",
        "FR": "Europe/Paris",
        "EU": "Europe/Berlin",
        "JP": "Asia/Tokyo",
        "AU": "Australia/Sydney",
    }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.plans = RecommendationPlanRepository(session)
        self.outcomes = RecommendationOutcomeRepository(session)
        self.market_data = HistoricalMarketDataRepository(session)
        self.taxonomy = TickerTaxonomyService()

    def run_evaluation(
        self,
        recommendation_plan_ids: list[int] | None = None,
        *,
        run_id: int | None = None,
        as_of: datetime | None = None,
    ) -> EvaluationRunResult:
        plans = self._list_plans(recommendation_plan_ids)
        logger.info(
            "recommendation evaluation started: run_id=%s requested_plan_ids=%s plan_count=%s as_of=%s",
            run_id,
            recommendation_plan_ids,
            len(plans),
            self._format_datetime(as_of),
        )
        if plans:
            logger.debug(
                "recommendation evaluation plans: %s",
                [self._plan_log_summary(plan) for plan in plans],
            )
        if not plans:
            logger.info("recommendation evaluation finished: no recommendation plans available")
            return EvaluationRunResult(output="no recommendation plans available for evaluation")

        price_history_cache, price_errors = self._prepare_price_histories(plans, as_of=as_of)
        if price_errors:
            logger.warning("recommendation evaluation history errors: %s", price_errors)
        logger.debug("recommendation evaluation history cache keys: %s", sorted(price_history_cache.keys()))
        processed = 0
        synced = 0
        detail_lines: list[str] = []
        outcome_labels: list[str] = []

        for plan in plans:
            processed += 1
            ticker = (plan.ticker or "").strip().upper()
            current_market_date = self._current_market_date(plan, as_of=as_of)
            use_intraday = self._uses_intraday_evaluation(plan, current_market_date, as_of=as_of)
            price_data = price_history_cache.get((ticker, use_intraday))
            source_mode = "intraday" if use_intraday else "daily"
            if price_data is None and use_intraday:
                logger.debug(
                    "plan %s ticker=%s intraday history missing; falling back to daily",
                    plan.id,
                    ticker,
                )
                price_data = price_history_cache.get((ticker, False))
                source_mode = "daily"
            logger.debug(
                "plan evaluation input: plan_id=%s ticker=%s action=%s computed_at=%s market_date=%s source_mode=%s price_rows=%s",
                plan.id,
                ticker,
                plan.action,
                self._format_datetime(plan.computed_at),
                current_market_date,
                source_mode,
                0 if price_data is None else len(price_data),
            )
            outcome = self._evaluate_plan(plan, price_data, run_id=run_id, as_of=as_of, intraday_only=use_intraday)
            stored = self.outcomes.upsert_outcome(outcome)
            synced += 1
            outcome_labels.append(stored.outcome)
            detail_lines.append(f"{plan.ticker}: {stored.outcome} ({stored.status})")
            logger.info(
                "plan evaluated: plan_id=%s ticker=%s outcome=%s status=%s entry_touched=%s stop_loss_hit=%s take_profit_hit=%s evaluated_at=%s",
                stored.recommendation_plan_id,
                stored.ticker,
                stored.outcome,
                stored.status,
                stored.entry_touched,
                stored.stop_loss_hit,
                stored.take_profit_hit,
                self._format_datetime(stored.evaluated_at),
            )

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

    def _prepare_price_histories(
        self,
        plans: list[RecommendationPlan],
        *,
        as_of: datetime | None = None,
    ) -> tuple[dict[tuple[str, bool], pd.DataFrame | None], list[str]]:
        groups = self._group_by_ticker(plans)
        cache: dict[tuple[str, bool], pd.DataFrame | None] = {}
        errors: list[str] = []
        end_time = self._normalize_datetime(as_of) or datetime.now(timezone.utc)
        logger.debug(
            "price history preparation started: groups=%s as_of=%s end_time=%s",
            len(groups),
            self._format_datetime(as_of),
            self._format_datetime(end_time),
        )
        for ticker, grouped_plans in groups.items():
            computed_times = [self._normalize_datetime(plan.computed_at) for plan in grouped_plans]
            normalized_times = [dt for dt in computed_times if dt is not None]
            if not normalized_times:
                continue
            earliest = min(normalized_times)
            start_time = earliest - timedelta(days=2)
            current_market_date = self._current_market_date(grouped_plans[0], as_of=as_of)
            needs_daily = any(not self._uses_intraday_evaluation(plan, current_market_date, as_of=as_of) for plan in grouped_plans)
            needs_intraday = any(self._uses_intraday_evaluation(plan, current_market_date, as_of=as_of) for plan in grouped_plans)
            logger.debug(
                "price history group: ticker=%s plan_ids=%s earliest=%s start=%s current_market_date=%s needs_daily=%s needs_intraday=%s",
                ticker,
                [plan.id for plan in grouped_plans],
                self._format_datetime(earliest),
                self._format_datetime(start_time),
                current_market_date,
                needs_daily,
                needs_intraday,
            )
            try:
                if needs_daily:
                    daily_data = self._load_price_history(ticker, start_time, end_time, intraday_only=False)
                    cache[(ticker, False)] = daily_data.sort_index() if daily_data is not None and not daily_data.empty else None
                    logger.debug(
                        "price history loaded: ticker=%s mode=daily rows=%s first=%s last=%s",
                        ticker,
                        0 if cache[(ticker, False)] is None else len(cache[(ticker, False)]),
                        self._format_datetime(None if cache[(ticker, False)] is None or cache[(ticker, False)].empty else cache[(ticker, False)].index[0]),
                        self._format_datetime(None if cache[(ticker, False)] is None or cache[(ticker, False)].empty else self._last_timestamp(cache[(ticker, False)])),
                    )
                    if cache[(ticker, False)] is None:
                        errors.append(f"{ticker}: daily price history is unavailable")
                if needs_intraday:
                    intraday_data = self._load_price_history(ticker, start_time, end_time, intraday_only=True)
                    cache[(ticker, True)] = intraday_data.sort_index() if intraday_data is not None and not intraday_data.empty else None
                    logger.debug(
                        "price history loaded: ticker=%s mode=intraday rows=%s first=%s last=%s",
                        ticker,
                        0 if cache[(ticker, True)] is None else len(cache[(ticker, True)]),
                        self._format_datetime(None if cache[(ticker, True)] is None or cache[(ticker, True)].empty else cache[(ticker, True)].index[0]),
                        self._format_datetime(None if cache[(ticker, True)] is None or cache[(ticker, True)].empty else self._last_timestamp(cache[(ticker, True)])),
                    )
                    if cache[(ticker, True)] is None:
                        errors.append(f"{ticker}: intraday price history is unavailable")
            except Exception as exc:  # pragma: no cover
                cache[(ticker, False)] = None
                cache[(ticker, True)] = None
                errors.append(f"{ticker}: {exc}")
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
        as_of: datetime | None = None,
        intraday_only: bool = False,
    ) -> RecommendationPlanOutcome:
        setup_family = self._setup_family(plan)
        confidence_bucket = self._confidence_bucket(plan.confidence_percent)
        logger.debug(
            "evaluate_plan start: plan_id=%s ticker=%s action=%s confidence=%s bucket=%s price_rows=%s",
            plan.id,
            plan.ticker,
            plan.action,
            plan.confidence_percent,
            confidence_bucket,
            0 if price_data is None else len(price_data),
        )
        if plan.action in {"no_action", "watchlist"}:
            logger.info("evaluate_plan short-circuit: plan_id=%s action=%s outcome=%s", plan.id, plan.action, plan.action)
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
            logger.warning(
                "evaluate_plan missing price data: plan_id=%s ticker=%s action=%s as_of=%s",
                plan.id,
                plan.ticker,
                plan.action,
                self._format_datetime(as_of),
            )
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

        sliced = self._rows_on_or_after(price_data, plan.computed_at, intraday_only=intraday_only)
        if sliced.empty:
            logger.warning(
                "evaluate_plan no post-plan bars: plan_id=%s ticker=%s computed_at=%s as_of=%s price_rows=%s first_available_at=%s last_available_at=%s first_bar_time=%s last_bar_time=%s",
                plan.id,
                plan.ticker,
                self._format_datetime(plan.computed_at),
                self._format_datetime(as_of),
                0 if price_data is None else len(price_data),
                self._frame_bound(price_data, "first", "available_at"),
                self._frame_bound(price_data, "last", "available_at"),
                self._frame_bound(price_data, "first", "bar_time"),
                self._frame_bound(price_data, "last", "bar_time"),
            )
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
            logger.info(
                "evaluate_plan no_entry: plan_id=%s ticker=%s entry_low=%s entry_high=%s rows=%s last_bar=%s",
                plan.id,
                plan.ticker,
                plan.entry_price_low,
                plan.entry_price_high,
                len(sliced),
                self._format_datetime(self._last_timestamp(sliced)),
            )
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

        logger.debug(
            "evaluate_plan exit resolution: plan_id=%s ticker=%s entry_index=%s stop_loss_hit=%s take_profit_hit=%s decisive_timestamp=%s outcome=%s status=%s",
            plan.id,
            plan.ticker,
            entry_index,
            first_stop_hit,
            first_take_hit,
            self._format_datetime(decisive_timestamp),
            outcome,
            status,
        )

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
        if "available_at" in data.columns:
            available = RecommendationPlanEvaluationService._normalize_datetime(data.iloc[-1].get("available_at"))
            if available is not None:
                return available
        return RecommendationPlanEvaluationService._normalize_datetime(data.index[-1])

    @staticmethod
    def _frame_bound(data: pd.DataFrame | None, position: str, column: str) -> str:
        if data is None or data.empty:
            return "None"
        row = data.iloc[0] if position == "first" else data.iloc[-1]
        value: object
        if column == "bar_time":
            value = data.index[0] if position == "first" else data.index[-1]
        else:
            value = row.get(column)
        return RecommendationPlanEvaluationService._format_datetime(value)

    @staticmethod
    def _rows_on_or_after(data: pd.DataFrame, start_at: datetime, *, intraday_only: bool = False) -> pd.DataFrame:
        normalized_start = RecommendationPlanEvaluationService._normalize_datetime(start_at)
        if normalized_start is None:
            return pd.DataFrame(columns=data.columns)

        if "available_at" in data.columns:
            normalized_available = data["available_at"].apply(RecommendationPlanEvaluationService._normalize_datetime)
            mask = normalized_available.map(lambda value: value is not None and value >= normalized_start)
            rows = data.loc[mask]
            if not rows.empty:
                return rows
            if not intraday_only:
                date_mask = data.index.map(
                    lambda timestamp: (
                        (normalized_timestamp := RecommendationPlanEvaluationService._normalize_datetime(timestamp)) is not None
                        and normalized_timestamp.date() >= normalized_start.date()
                    )
                )
                fallback_rows = data.loc[date_mask]
                if not fallback_rows.empty:
                    logger.debug(
                        "rows_on_or_after daily-date fallback used: start_at=%s rows=%s first_available_at=%s last_available_at=%s",
                        RecommendationPlanEvaluationService._format_datetime(normalized_start),
                        len(fallback_rows),
                        RecommendationPlanEvaluationService._format_datetime(fallback_rows.iloc[0].get("available_at")),
                        RecommendationPlanEvaluationService._format_datetime(fallback_rows.iloc[-1].get("available_at")),
                    )
                    return fallback_rows
            return pd.DataFrame(columns=data.columns)

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
    def _format_datetime(value: object) -> str:
        normalized = RecommendationPlanEvaluationService._normalize_datetime(value)
        return normalized.isoformat() if normalized is not None else "None"

    @staticmethod
    def _plan_log_summary(plan: RecommendationPlan) -> dict[str, object]:
        return {
            "id": plan.id,
            "ticker": plan.ticker,
            "action": plan.action,
            "horizon": plan.horizon,
            "confidence_percent": plan.confidence_percent,
            "computed_at": RecommendationPlanEvaluationService._format_datetime(plan.computed_at),
            "entry_low": plan.entry_price_low,
            "entry_high": plan.entry_price_high,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
        }

    def _uses_intraday_evaluation(
        self,
        plan: RecommendationPlan,
        current_market_date: date | None = None,
        *,
        as_of: datetime | None = None,
    ) -> bool:
        local_zone = self._market_timezone_for_plan(plan)
        if local_zone is None:
            return False
        computed_at = self._normalize_datetime(plan.computed_at)
        if computed_at is None:
            return False
        local_computed = computed_at.astimezone(local_zone)
        if local_computed.weekday() >= 5:
            return False
        if current_market_date is not None and local_computed.date() != current_market_date:
            return False
        local_time = local_computed.timetz().replace(tzinfo=None)
        if not (self._market_open_time <= local_time < self._market_close_time):
            return False
        if as_of is not None:
            normalized_as_of = self._normalize_datetime(as_of)
            if normalized_as_of is None:
                return False
            local_as_of = normalized_as_of.astimezone(local_zone)
            if local_as_of.date() != current_market_date:
                return False
            local_as_of_time = local_as_of.timetz().replace(tzinfo=None)
            if not (self._market_open_time <= local_as_of_time < self._market_close_time):
                return False
        return True

    def _market_timezone_for_plan(self, plan: RecommendationPlan) -> ZoneInfo | None:
        profile = self.taxonomy.get_ticker_profile(plan.ticker)
        region = str(profile.get("region") or "").strip().upper()
        timezone_name = self._market_timezone_by_region.get(region)
        if not timezone_name:
            return None
        try:
            return ZoneInfo(timezone_name)
        except Exception:  # pragma: no cover - invalid zone fallback
            return None

    def _current_market_date(self, plan: RecommendationPlan, as_of: datetime | None = None) -> date | None:
        local_zone = self._market_timezone_for_plan(plan)
        if local_zone is None:
            return None
        if as_of is None:
            return datetime.now(local_zone).date()
        normalized_as_of = self._normalize_datetime(as_of)
        if normalized_as_of is None:
            return None
        return normalized_as_of.astimezone(local_zone).date()

    def _load_price_history(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        *,
        intraday_only: bool = False,
    ) -> pd.DataFrame:
        logger.debug(
            "load_price_history request: ticker=%s intraday_only=%s start=%s end=%s",
            ticker,
            intraday_only,
            self._format_datetime(start_date),
            self._format_datetime(end_date),
        )
        persisted = self._load_persisted_price_history(ticker, start_date, end_date, intraday_only=intraday_only)
        if persisted is not None and not persisted.empty:
            logger.debug(
                "load_price_history source=persisted ticker=%s intraday_only=%s rows=%s first=%s last=%s",
                ticker,
                intraday_only,
                len(persisted),
                self._format_datetime(persisted.index[0]),
                self._format_datetime(persisted.index[-1]),
            )
            return persisted
        logger.debug(
            "load_price_history source=yfinance ticker=%s intraday_only=%s",
            ticker,
            intraday_only,
        )
        return self._download_price_history(ticker, start_date, end_date, intraday_only=intraday_only)

    def _load_persisted_price_history(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        *,
        intraday_only: bool = False,
    ) -> pd.DataFrame | None:
        timeframes = self._intraday_timeframes if intraday_only else self._preferred_timeframes
        for timeframe in timeframes:
            bars = self.market_data.list_bars(
                ticker=ticker,
                timeframe=timeframe,
                start_at=start_date,
                end_at=end_date,
                available_at=end_date,
                limit=2000,
            )
            if not bars:
                continue
            frame = self._bars_to_frame(bars, start_date=start_date)
            if frame is not None and not frame.empty:
                return frame
        return None

    @staticmethod
    def _bars_to_frame(bars: list[HistoricalMarketBar], *, start_date: datetime) -> pd.DataFrame | None:
        records: list[dict[str, object]] = []
        normalized_start = RecommendationPlanEvaluationService._normalize_datetime(start_date)
        if normalized_start is None:
            return None
        for bar in bars:
            available_at = RecommendationPlanEvaluationService._normalize_datetime(bar.available_at or bar.bar_time)
            bar_time = RecommendationPlanEvaluationService._normalize_datetime(bar.bar_time)
            if available_at is None or bar_time is None:
                continue
            if available_at < normalized_start:
                continue
            records.append(
                {
                    "bar_time": bar_time,
                    "available_at": available_at,
                    "Open": bar.open_price,
                    "High": bar.high_price,
                    "Low": bar.low_price,
                    "Close": bar.close_price,
                    "Volume": bar.volume,
                    "timeframe": bar.timeframe,
                    "source": bar.source,
                }
            )
        if not records:
            return None
        frame = pd.DataFrame.from_records(records)
        frame = frame.sort_values(by=["available_at", "bar_time"]).set_index("bar_time")
        return frame

    @classmethod
    def _download_price_history(
        cls,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        *,
        intraday_only: bool = False,
    ) -> pd.DataFrame:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
        interval = cls._intraday_interval if intraday_only else "1d"
        logger.debug(
            "download_price_history: ticker=%s intraday_only=%s interval=%s start=%s end=%s",
            ticker,
            intraday_only,
            interval,
            start_str,
            end_str,
        )
        frame = yf.download(
            ticker,
            start=start_str,
            end=end_str,
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
        if frame is None or frame.empty:
            return frame
        frame = frame.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            if len(frame.columns.levels) > 1:
                ticker_level = None
                for candidate in ("Ticker", "ticker"):
                    if candidate in frame.columns.names:
                        ticker_level = frame.columns.names.index(candidate)
                        break
                if ticker_level is None:
                    ticker_level = 1 if frame.columns.nlevels > 1 else 0
                try:
                    frame = frame.xs(ticker, axis=1, level=ticker_level)
                except Exception:
                    # Fall back to the first ticker slice for single-ticker downloads.
                    frame = frame.xs(frame.columns.levels[ticker_level][0], axis=1, level=ticker_level)
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = [column[0] if isinstance(column, tuple) else column for column in frame.columns]
        normalized_index = pd.to_datetime(frame.index, utc=True)
        frame.index = normalized_index
        if intraday_only:
            bar_delta = pd.to_timedelta(interval)
            frame["available_at"] = [ts + bar_delta for ts in normalized_index]
        else:
            frame["available_at"] = [
                datetime.combine(ts.date(), datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc) for ts in normalized_index
            ]
        return frame

    @staticmethod
    def _build_output(processed: int, details: list[str], errors: list[str]) -> str:
        parts: list[str] = []
        if processed:
            parts.append(f"Processed {processed} recommendation plan{'s' if processed != 1 else ''}.")
        parts.extend(errors)
        parts.extend(details)
        return " ".join(parts) if parts else "no recommendation plans were evaluated"
