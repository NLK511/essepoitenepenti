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

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import EvaluationRunResult, HistoricalMarketBar, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
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
        self.settings = SettingsRepository(session)
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
            daily_data = price_history_cache.get((ticker, False))
            intraday_data = price_history_cache.get((ticker, True))
            outcome, source_mode = self._resolve_plan_outcome(
                plan,
                daily_data,
                intraday_data,
                run_id=run_id,
                as_of=as_of,
            )
            logger.debug(
                "plan evaluation input: plan_id=%s ticker=%s action=%s computed_at=%s source_mode=%s daily_rows=%s intraday_rows=%s",
                plan.id,
                ticker,
                plan.action,
                self._format_datetime(plan.computed_at),
                source_mode,
                0 if daily_data is None else len(daily_data),
                0 if intraday_data is None else len(intraday_data),
            )
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
            outcome_map = self.outcomes.get_outcomes_by_plan_ids([row.id for row in rows if row.id is not None])
            rows = [
                row
                for row in rows
                if outcome_map.get(row.id or 0) is None or outcome_map[row.id or 0].status != "resolved"
            ]
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
            needs_history = any(plan.action in {"long", "short"} for plan in grouped_plans)
            logger.debug(
                "price history group: ticker=%s plan_ids=%s earliest=%s start=%s needs_history=%s",
                ticker,
                [plan.id for plan in grouped_plans],
                self._format_datetime(earliest),
                self._format_datetime(start_time),
                needs_history,
            )
            try:
                if needs_history:
                    daily_data = self._load_price_history(
                        ticker,
                        start_time,
                        end_time,
                        intraday_only=False,
                        require_full_coverage=as_of is not None,
                        plan_ids=[plan.id for plan in grouped_plans if plan.id is not None],
                    )
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
                    intraday_data = self._load_price_history(
                        ticker,
                        start_time,
                        end_time,
                        intraday_only=True,
                        require_full_coverage=as_of is not None,
                        plan_ids=[plan.id for plan in grouped_plans if plan.id is not None],
                    )
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
        intended_action: str | None = None,
        run_id: int | None,
        as_of: datetime | None = None,
        intraday_only: bool = False,
    ) -> RecommendationPlanOutcome:
        setup_family = self._setup_family(plan)
        confidence_bucket = self._confidence_bucket(plan.confidence_percent)
        effective_action = intended_action if plan.action in {"no_action", "watchlist"} and intended_action in {"long", "short"} else plan.action

        logger.debug(
            "evaluate_plan start: plan_id=%s ticker=%s action=%s effective=%s confidence=%s bucket=%s price_rows=%s",
            plan.id,
            plan.ticker,
            plan.action,
            effective_action,
            plan.confidence_percent,
            confidence_bucket,
            0 if price_data is None else len(price_data),
        )
        
        if effective_action not in {"long", "short"}:
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

        sliced = self._rows_on_or_after(
            price_data,
            plan.computed_at,
            intraday_only=intraday_only,
            plan_id=plan.id,
            ticker=plan.ticker,
        )
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
                outcome="phantom_no_entry" if plan.action in {"no_action", "watchlist"} else "no_entry",
                status="open",
                evaluated_at=self._last_timestamp(sliced) or datetime.now(timezone.utc),
                entry_touched=False,
                horizon_return_1d=self._horizon_return(effective_action, sliced, 1, entry_reference),
                horizon_return_3d=self._horizon_return(effective_action, sliced, 3, entry_reference),
                horizon_return_5d=self._horizon_return(effective_action, sliced, 5, entry_reference),
                confidence_bucket=confidence_bucket,
                setup_family=setup_family,
                notes="Entry zone has not been touched yet.",
                run_id=run_id,
            )

        active = sliced.iloc[entry_index:]
        first_stop_hit, first_take_hit, decisive_timestamp = self._resolve_exit(effective_action, plan, active)
        realized_holding = self._realized_holding_days(plan.computed_at, decisive_timestamp or self._last_timestamp(active))
        mfe = self._max_favorable_excursion(effective_action, active, entry_reference)
        mae = self._max_adverse_excursion(effective_action, active, entry_reference)
        horizon_1d = self._horizon_return(effective_action, active, 1, entry_reference)
        horizon_3d = self._horizon_return(effective_action, active, 3, entry_reference)
        horizon_5d = self._horizon_return(effective_action, active, 5, entry_reference)
        direction_correct = None
        for candidate in (horizon_5d, horizon_3d, horizon_1d):
            if candidate is not None:
                direction_correct = candidate > 0
                break
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

    def _resolve_exit(self, effective_action: str, plan: RecommendationPlan, data: pd.DataFrame) -> tuple[bool, bool, datetime | None]:
        realism = self.settings.get_evaluation_realism_config()
        stop_buffer = realism["stop_buffer_pct"] / 100.0
        take_buffer = realism["take_profit_buffer_pct"] / 100.0

        for timestamp, row in data.iterrows():
            row_high = self._float_or_none(row.get("High"))
            row_low = self._float_or_none(row.get("Low"))
            if row_high is None or row_low is None:
                continue
            
            # Use dynamic realism buffers
            stop_hit = self._check_stop_with_buffer(effective_action, row_high, row_low, plan.stop_loss, stop_buffer)
            take_hit = self._check_take_with_buffer(effective_action, row_high, row_low, plan.take_profit, take_buffer)
            
            if stop_hit or take_hit:
                return stop_hit, take_hit, self._normalize_datetime(timestamp)
        return False, False, None

    @staticmethod
    def _check_stop_with_buffer(action: str, high: float, low: float, stop_loss: float | None, buffer_pct: float) -> bool:
        if stop_loss is None:
            return False
        buffer = stop_loss * buffer_pct
        if action == "long":
            return low <= (stop_loss + buffer)
        if action == "short":
            return high >= (stop_loss - buffer)
        return False

    @staticmethod
    def _check_take_with_buffer(action: str, high: float, low: float, take_profit: float | None, buffer_pct: float) -> bool:
        if take_profit is None:
            return False
        buffer = take_profit * buffer_pct
        if action == "long":
            return high >= (take_profit + buffer)
        if action == "short":
            return low <= (take_profit - buffer)
        return False

    @staticmethod
    def _check_stop(action: str, high: float, low: float, stop_loss: float | None) -> bool:
        # Legacy method maintained for unit test compatibility if needed, 
        # but _resolve_exit now uses _check_stop_with_buffer.
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
        effective_action: str,
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
        
        # Gross Return
        raw_return = ((close_value - entry_reference) / entry_reference) * 100.0
        
        # Realism Buffer: Use dynamic friction from settings
        realism = self.settings.get_evaluation_realism_config()
        friction_pct = realism["friction_pct"]
        
        if effective_action == "short":
            return round(-raw_return - friction_pct, 4)
        return round(raw_return - friction_pct, 4)

    def _max_favorable_excursion(self, effective_action: str, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        if effective_action == "short":
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

    def _max_adverse_excursion(self, effective_action: str, data: pd.DataFrame, entry_reference: float) -> float | None:
        if data.empty or entry_reference <= 0:
            return None
        if effective_action == "short":
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
    def _rows_on_or_after(
        data: pd.DataFrame,
        start_at: datetime,
        *,
        intraday_only: bool = False,
        plan_id: int | None = None,
        ticker: str | None = None,
    ) -> pd.DataFrame:
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
                    logger.info(
                        "rows_on_or_after daily-date fallback used: plan_id=%s ticker=%s start_at=%s rows=%s first_available_at=%s last_available_at=%s",
                        plan_id,
                        ticker,
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

    def _resolve_plan_outcome(
        self,
        plan: RecommendationPlan,
        daily_data: pd.DataFrame | None,
        intraday_data: pd.DataFrame | None,
        *,
        run_id: int | None,
        as_of: datetime | None = None,
    ) -> tuple[RecommendationPlanOutcome, str]:
        intended_action = self._phantom_intended_action(plan)
        if plan.action in {"no_action", "watchlist"} and intended_action is None:
            outcome = self._evaluate_plan(plan, None, run_id=run_id, as_of=as_of, intraday_only=False)
            return self._finalize_outcome(plan, outcome, as_of=as_of), "none"

        return self._resolve_trade_like_outcome(
            plan,
            daily_data,
            intraday_data,
            run_id=run_id,
            as_of=as_of,
            intended_action=intended_action,
        )

    def _resolve_trade_like_outcome(
        self,
        plan: RecommendationPlan,
        daily_data: pd.DataFrame | None,
        intraday_data: pd.DataFrame | None,
        *,
        run_id: int | None,
        as_of: datetime | None = None,
        intended_action: str | None = None,
    ) -> tuple[RecommendationPlanOutcome, str]:
        daily_outcome: RecommendationPlanOutcome | None = None
        if daily_data is not None and not daily_data.empty:
            daily_outcome = self._evaluate_plan(plan, daily_data, intended_action=intended_action, run_id=run_id, as_of=as_of, intraday_only=False)
            if daily_outcome.outcome in {"no_entry", "open", "phantom_no_entry", "phantom_pending"}:
                return self._finalize_outcome(plan, daily_outcome, as_of=as_of), "daily"
            if intraday_data is not None and not intraday_data.empty:
                intraday_outcome = self._evaluate_plan(plan, intraday_data, intended_action=intended_action, run_id=run_id, as_of=as_of, intraday_only=True)
                # Preserve daily horizon returns; intraday horizon metrics are skewed by bar frequency.
                intraday_outcome.horizon_return_1d = daily_outcome.horizon_return_1d
                intraday_outcome.horizon_return_3d = daily_outcome.horizon_return_3d
                intraday_outcome.horizon_return_5d = daily_outcome.horizon_return_5d
                return self._finalize_outcome(plan, intraday_outcome, as_of=as_of), "intraday"
            pending_outcome = self._pending_resolution_outcome(
                plan,
                run_id=run_id,
                confidence_bucket=self._confidence_bucket(plan.confidence_percent),
                setup_family=self._setup_family(plan),
                notes="Intraday price history is required for final resolution but is unavailable.",
            )
            return self._finalize_outcome(plan, pending_outcome, as_of=as_of), "pending"

        if intraday_data is not None and not intraday_data.empty:
            intraday_outcome = self._evaluate_plan(plan, intraday_data, intended_action=intended_action, run_id=run_id, as_of=as_of, intraday_only=True)
            return self._finalize_outcome(plan, intraday_outcome, as_of=as_of), "intraday"

        if daily_outcome is not None:
            if daily_outcome.outcome in {"no_entry", "open", "phantom_no_entry", "phantom_pending"}:
                return self._finalize_outcome(plan, daily_outcome, as_of=as_of), "daily"
            pending_outcome = self._pending_resolution_outcome(
                plan,
                run_id=run_id,
                confidence_bucket=self._confidence_bucket(plan.confidence_percent),
                setup_family=self._setup_family(plan),
                notes="Intraday price history is required for final resolution but is unavailable.",
            )
            return self._finalize_outcome(plan, pending_outcome, as_of=as_of), "pending"

        pending_outcome = self._pending_resolution_outcome(
            plan,
            run_id=run_id,
            confidence_bucket=self._confidence_bucket(plan.confidence_percent),
            setup_family=self._setup_family(plan),
            notes="No price history available for evaluation.",
        )
        return self._finalize_outcome(plan, pending_outcome, as_of=as_of), "pending"

    @staticmethod
    def _phantom_intended_action(plan: RecommendationPlan) -> str | None:
        if plan.action not in {"no_action", "watchlist"}:
            return None
        signal_breakdown = plan.signal_breakdown if hasattr(plan.signal_breakdown, "get") else {}
        intended_action = signal_breakdown.get("intended_action") if hasattr(signal_breakdown, "get") else None
        if intended_action not in {"long", "short"}:
            return None
        if plan.entry_price_low is None and plan.entry_price_high is None:
            return None
        if plan.stop_loss is None or plan.take_profit is None:
            return None
        return str(intended_action)

    def _finalize_outcome(
        self,
        plan: RecommendationPlan,
        outcome: RecommendationPlanOutcome,
        *,
        as_of: datetime | None,
    ) -> RecommendationPlanOutcome:
        if outcome.status == "resolved":
            return outcome
        if not self._is_past_plan_horizon(plan, as_of=as_of):
            return outcome
        expired = RecommendationPlanOutcome(**outcome.model_dump())
        expired.outcome = "expired"
        expired.status = "resolved"
        expired.evaluated_at = self._normalize_datetime(as_of) or datetime.now(timezone.utc)
        suffix = "Horizon elapsed without a terminal outcome; marked expired."
        expired.notes = f"{outcome.notes} {suffix}".strip() if outcome.notes else suffix
        return expired

    def _is_past_plan_horizon(self, plan: RecommendationPlan, *, as_of: datetime | None) -> bool:
        reference = self._normalize_datetime(as_of) or datetime.now(timezone.utc)
        cutoff = self._plan_horizon_cutoff(plan)
        return cutoff is not None and reference >= cutoff

    def _plan_horizon_cutoff(self, plan: RecommendationPlan) -> datetime | None:
        computed_at = self._normalize_datetime(plan.computed_at)
        if computed_at is None:
            return None
        session_count = self._plan_horizon_sessions(plan)
        market_tz = ZoneInfo("America/New_York")
        local_time = computed_at.astimezone(market_tz)
        session_date = local_time.date()
        if local_time.weekday() >= 5 or local_time.time() > self._market_close_time:
            session_date = self._next_business_day(session_date)
        remaining_sessions = max(session_count - 1, 0)
        while remaining_sessions > 0:
            session_date = self._next_business_day(session_date)
            remaining_sessions -= 1
        return datetime.combine(session_date, self._market_close_time, tzinfo=market_tz).astimezone(timezone.utc)

    @staticmethod
    def _next_business_day(current: date) -> date:
        candidate = current + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _plan_horizon_sessions(plan: RecommendationPlan) -> int:
        if isinstance(plan.holding_period_days, int) and plan.holding_period_days > 0:
            return plan.holding_period_days
        if plan.horizon == StrategyHorizon.ONE_DAY:
            return 1
        if plan.horizon == StrategyHorizon.ONE_MONTH:
            return 20
        return 5

    def _pending_resolution_outcome(
        self,
        plan: RecommendationPlan,
        *,
        run_id: int | None,
        confidence_bucket: str,
        setup_family: str,
        notes: str,
    ) -> RecommendationPlanOutcome:
        return RecommendationPlanOutcome(
            recommendation_plan_id=plan.id or 0,
            ticker=plan.ticker,
            action=plan.action,
            outcome="pending",
            status="open",
            evaluated_at=datetime.now(timezone.utc),
            confidence_bucket=confidence_bucket,
            setup_family=setup_family,
            notes=notes,
            run_id=run_id,
        )

    def _load_price_history(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        *,
        intraday_only: bool = False,
        require_full_coverage: bool = False,
        plan_ids: list[int] | None = None,
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
            if not require_full_coverage or self._persisted_history_covers_window(persisted, end_date=end_date, intraday_only=intraday_only):
                logger.debug(
                    "load_price_history source=persisted ticker=%s intraday_only=%s rows=%s first=%s last=%s",
                    ticker,
                    intraday_only,
                    len(persisted),
                    self._format_datetime(persisted.index[0]),
                    self._format_datetime(persisted.index[-1]),
                )
                return persisted
            logger.info(
                "load_price_history persisted history incomplete; falling back to yfinance ticker=%s plan_ids=%s intraday_only=%s rows=%s first=%s last=%s end=%s",
                ticker,
                plan_ids,
                intraday_only,
                len(persisted),
                self._format_datetime(persisted.index[0]),
                self._format_datetime(persisted.index[-1]),
                self._format_datetime(end_date),
            )
        logger.debug(
            "load_price_history source=yfinance ticker=%s intraday_only=%s",
            ticker,
            intraday_only,
        )
        downloaded = self._download_price_history(ticker, start_date, end_date, intraday_only=intraday_only)
        if not downloaded.empty:
            self._persist_downloaded_bars(ticker, downloaded, intraday_only=intraday_only)
        return downloaded

    def _persist_downloaded_bars(self, ticker: str, data: pd.DataFrame, *, intraday_only: bool) -> None:
        """Save downloaded bars to the local historical_market_bars table."""
        timeframe = self._intraday_interval if intraday_only else "1d"
        bars = []
        for timestamp, row in data.iterrows():
            bar_time = self._normalize_datetime(timestamp)
            available_at = self._normalize_datetime(row.get("available_at"))
            if bar_time is None:
                continue
            bars.append(
                HistoricalMarketBar(
                    ticker=ticker,
                    timeframe=timeframe,
                    bar_time=bar_time,
                    available_at=available_at,
                    open_price=float(row.get("Open", 0.0)),
                    high_price=float(row.get("High", 0.0)),
                    low_price=float(row.get("Low", 0.0)),
                    close_price=float(row.get("Close", 0.0)),
                    volume=float(row.get("Volume", 0.0)),
                    source="yfinance_auto_cache",
                )
            )
        if bars:
            try:
                self.market_data.upsert_bars(bars)
                logger.info("persisted %s downloaded %s bars for %s", len(bars), timeframe, ticker)
            except Exception as exc:
                logger.warning("failed to persist downloaded bars for %s: %s", ticker, exc)

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
    def _persisted_history_covers_window(data: pd.DataFrame, *, end_date: datetime, intraday_only: bool) -> bool:
        if data.empty:
            return False
        normalized_end = RecommendationPlanEvaluationService._normalize_datetime(end_date)
        if normalized_end is None:
            return False
        last_available = RecommendationPlanEvaluationService._normalize_datetime(data.iloc[-1].get("available_at"))
        if last_available is None:
            last_available = RecommendationPlanEvaluationService._normalize_datetime(data.index[-1])
        if last_available is None:
            return False
        if intraday_only:
            return last_available >= normalized_end
        return last_available.date() >= normalized_end.date()

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
