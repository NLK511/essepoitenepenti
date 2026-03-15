from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Iterable

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import RecommendationDirection, RecommendationState
from trade_proposer_app.domain.models import EvaluationRunResult
from trade_proposer_app.persistence.models import RecommendationRecord


class RecommendationEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run_evaluation(self, recommendation_ids: list[int] | None = None) -> EvaluationRunResult:
        recommendations = self._list_recommendations(recommendation_ids=recommendation_ids)
        if not recommendations:
            return EvaluationRunResult(output="no pending recommendations available")

        price_history_cache, price_errors = self._prepare_price_histories(recommendations)

        processed = 0
        synced = 0
        detail_lines: list[str] = []
        for recommendation in recommendations:
            processed += 1
            ticker_key = (recommendation.ticker or "").strip().upper()
            price_data = price_history_cache.get(ticker_key)
            new_state, evaluated_at, note = self._evaluate_against_history(recommendation, price_data)
            if new_state is None:
                if note:
                    detail_lines.append(f"{recommendation.ticker or ticker_key}: {note}")
                continue

            previous_state_value = recommendation.evaluation_state or RecommendationState.PENDING.value
            try:
                previous_state = RecommendationState(previous_state_value)
            except ValueError:
                previous_state = RecommendationState.PENDING

            has_new_timestamp = recommendation.evaluated_at != evaluated_at
            if previous_state != new_state or has_new_timestamp:
                recommendation.evaluation_state = new_state.value
                recommendation.evaluated_at = evaluated_at
                synced += 1
            detail_lines.append(f"{recommendation.ticker or ticker_key}: {new_state.value} on {evaluated_at.isoformat()}")

        if synced > 0:
            self.session.commit()

        pending_recommendations = sum(1 for recommendation in recommendations if recommendation.evaluation_state == RecommendationState.PENDING.value)
        win_recommendations = sum(1 for recommendation in recommendations if recommendation.evaluation_state == RecommendationState.WIN.value)
        loss_recommendations = sum(1 for recommendation in recommendations if recommendation.evaluation_state == RecommendationState.LOSS.value)

        output = self._build_output(processed, synced, detail_lines, price_errors)
        return EvaluationRunResult(
            evaluated_trade_log_entries=processed,
            synced_recommendations=synced,
            pending_recommendations=pending_recommendations,
            win_recommendations=win_recommendations,
            loss_recommendations=loss_recommendations,
            output=output,
        )

    def _prepare_price_histories(self, recommendations: list[RecommendationRecord]) -> tuple[dict[str, object], list[str]]:
        groups: dict[str, list[RecommendationRecord]] = self._group_recommendations_by_ticker(recommendations)
        cache: dict[str, object] = {}
        errors: list[str] = []
        end_time = datetime.now(timezone.utc)
        for ticker, grouped_recommendations in groups.items():
            earliest = min(
                (self._normalize_datetime(recommendation.created_at) or end_time)
                for recommendation in grouped_recommendations
            )
            start_time = earliest - timedelta(days=1)
            if start_time >= end_time:
                start_time = earliest - timedelta(days=2)
            try:
                data = self._download_price_history(ticker, start_time, end_time)
            except Exception as exc:  # pragma: no cover - handles live failures
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
    def _group_recommendations_by_ticker(recommendations: Iterable[RecommendationRecord]) -> dict[str, list[RecommendationRecord]]:
        groups: dict[str, list[RecommendationRecord]] = defaultdict(list)
        for recommendation in recommendations:
            ticker = (recommendation.ticker or "").strip().upper()
            if not ticker:
                continue
            groups[ticker].append(recommendation)
        return groups

    def _evaluate_against_history(self, recommendation: RecommendationRecord, price_data: object | None) -> tuple[RecommendationState | None, datetime | None, str | None]:
        if price_data is None:
            return None, None, "no price history available"

        normalized_created_at = self._normalize_datetime(recommendation.created_at) or datetime.now(timezone.utc)
        try:
            direction = RecommendationDirection(recommendation.direction)
        except ValueError:
            return None, None, "unsupported direction"

        data = price_data.sort_index()
        for timestamp, row in data.iterrows():
            row_datetime = self._normalize_datetime(timestamp)
            if row_datetime is None or row_datetime < normalized_created_at:
                continue

            high = row.get("High")
            low = row.get("Low")
            if not self._has_valid_price(high) or not self._has_valid_price(low):
                continue

            take_hit = self._check_take_profit(direction, high, low, recommendation.take_profit)
            stop_hit = self._check_stop_loss(direction, high, low, recommendation.stop_loss)
            if not take_hit and not stop_hit:
                continue

            new_state = self._resolve_state(direction, take_hit, stop_hit, recommendation)
            if new_state is None:
                continue
            return new_state, row_datetime, "targets triggered"

        return None, None, "thresholds not hit yet"

    @staticmethod
    def _check_take_profit(direction: RecommendationDirection, high: float, low: float, take_profit: float | None) -> bool:
        if take_profit is None:
            return False
        if direction == RecommendationDirection.LONG:
            return high >= take_profit
        if direction == RecommendationDirection.SHORT:
            return low <= take_profit
        return False

    @staticmethod
    def _check_stop_loss(direction: RecommendationDirection, high: float, low: float, stop_loss: float | None) -> bool:
        if stop_loss is None:
            return False
        if direction == RecommendationDirection.LONG:
            return low <= stop_loss
        if direction == RecommendationDirection.SHORT:
            return high >= stop_loss
        return False

    @staticmethod
    def _resolve_state(
        direction: RecommendationDirection,
        take_hit: bool,
        stop_hit: bool,
        recommendation: RecommendationRecord,
    ) -> RecommendationState | None:
        if take_hit and not stop_hit:
            return RecommendationState.WIN
        if stop_hit and not take_hit:
            return RecommendationState.LOSS
        if take_hit and stop_hit:
            entry_price = recommendation.entry_price or 0.0
            stop_distance = abs(entry_price - (recommendation.stop_loss or entry_price))
            take_distance = abs((recommendation.take_profit or entry_price) - entry_price)
            if direction == RecommendationDirection.LONG:
                return RecommendationState.LOSS if stop_distance <= take_distance else RecommendationState.WIN
            if direction == RecommendationDirection.SHORT:
                return RecommendationState.WIN if take_distance <= stop_distance else RecommendationState.LOSS
        return None

    @staticmethod
    def _has_valid_price(value: float | None) -> bool:
        if value is None:
            return False
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return not math.isnan(numeric)

    @staticmethod
    def _normalize_datetime(value: datetime | object | None) -> datetime | None:
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
    def _download_price_history(ticker: str, start_date: datetime, end_date: datetime) -> object:
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
    def _build_output(processed: int, synced: int, details: list[str], errors: list[str]) -> str:
        parts: list[str] = []
        if processed:
            parts.append(f"Processed {processed} recommendation{'s' if processed != 1 else ''}.")
        if synced:
            parts.append(f"Updated {synced} state{'s' if synced != 1 else ''}.")
        parts.extend(errors)
        parts.extend(details)
        if not parts:
            return "no recommendations were evaluated"
        return " ".join(parts)

    def _list_recommendations(self, recommendation_ids: list[int] | None = None) -> list[RecommendationRecord]:
        query = select(RecommendationRecord)
        if recommendation_ids:
            query = query.where(RecommendationRecord.id.in_(recommendation_ids))
        else:
            query = query.where(RecommendationRecord.evaluation_state == RecommendationState.PENDING.value)
        return list(self.session.scalars(query).all())
