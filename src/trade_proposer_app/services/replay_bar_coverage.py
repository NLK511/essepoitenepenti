from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord


@dataclass(frozen=True)
class ReplayBarCoverageDiagnostic:
    ticker: str
    required_start: datetime
    required_end: datetime
    status: str
    reason: str
    earliest_1m_bar: datetime | None
    latest_1m_bar: datetime | None
    rows_in_window: int
    trading_dates_in_window: int
    required_row_limit: int

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "required_start": self.required_start.isoformat(),
            "required_end": self.required_end.isoformat(),
            "status": self.status,
            "reason": self.reason,
            "earliest_1m_bar": self.earliest_1m_bar.isoformat() if self.earliest_1m_bar else None,
            "latest_1m_bar": self.latest_1m_bar.isoformat() if self.latest_1m_bar else None,
            "rows_in_window": self.rows_in_window,
            "trading_dates_in_window": self.trading_dates_in_window,
            "required_row_limit": self.required_row_limit,
        }


class ReplayBarCoverageService:
    """Classify replay resolution bar coverage without fetching remote data."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._ticker_bounds_cache: dict[str, tuple[datetime | None, datetime | None]] = {}
        self._window_counts_cache: dict[tuple[str, datetime, datetime], tuple[int, int]] = {}

    def diagnose_plan(
        self,
        plan: RecommendationPlan,
        *,
        required_end: datetime | None = None,
    ) -> ReplayBarCoverageDiagnostic:
        ticker = str(plan.ticker or "").strip().upper()
        start = self._normalize(plan.computed_at) or datetime.now(timezone.utc)
        end = self._normalize(required_end) or self.plan_horizon_cutoff(plan)
        required_row_limit = self.intraday_row_limit(start, end)
        earliest, latest = self._ticker_bounds(ticker)
        if earliest is None or latest is None:
            return self._diagnostic(
                ticker,
                start,
                end,
                "blocked",
                "ticker_not_in_cache",
                earliest,
                latest,
                0,
                0,
                required_row_limit,
            )
        rows, trading_dates = self._window_counts(ticker, start, end)
        if self._is_current_session_incomplete(end, latest) and rows > 0:
            reason = "current_session_incomplete"
        elif start < earliest:
            reason = "outside_local_intraday_cache"
        elif rows == 0:
            reason = "internal_cache_gap"
        elif required_row_limit > 2_000:
            reason = "loader_limit_truncated"
        else:
            reason = "covered"
        status = "covered" if reason == "covered" else "blocked"
        return self._diagnostic(
            ticker,
            start,
            end,
            status,
            reason,
            earliest,
            latest,
            rows,
            trading_dates,
            required_row_limit,
        )

    def latest_complete_cached_session_as_of(self, tickers: list[str]) -> datetime | None:
        normalized = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
        if not normalized:
            return None
        table = HistoricalMarketBarRecord.__table__
        rows = self.session.execute(
            select(table.c.ticker, func.max(table.c.bar_time))
            .where(table.c.timeframe == "1m")
            .where(table.c.ticker.in_(normalized))
            .group_by(table.c.ticker)
        ).all()
        latest_dates = [self._normalize(row[1]).date() for row in rows if self._normalize(row[1]) is not None]
        if not latest_dates:
            return None
        latest_shared_date = min(latest_dates)
        return datetime.combine(latest_shared_date, time(23, 59, 59), tzinfo=timezone.utc)

    @staticmethod
    def plan_horizon_cutoff(plan: RecommendationPlan) -> datetime:
        computed = ReplayBarCoverageService._normalize(plan.computed_at) or datetime.now(timezone.utc)
        if plan.holding_period_days is not None:
            days = max(1, int(plan.holding_period_days))
        elif str(plan.horizon or "") == "1d":
            days = 1
        elif str(plan.horizon or "") == "1m":
            days = 30
        else:
            days = 7
        return computed + timedelta(days=days)

    @staticmethod
    def intraday_row_limit(start: datetime, end: datetime) -> int:
        normalized_start = ReplayBarCoverageService._normalize(start)
        normalized_end = ReplayBarCoverageService._normalize(end)
        if normalized_start is None or normalized_end is None or normalized_end <= normalized_start:
            return 2_000
        calendar_days = max(1, (normalized_end.date() - normalized_start.date()).days + 1)
        return max(2_000, min(50_000, calendar_days * 1_440))

    def _ticker_bounds(self, ticker: str) -> tuple[datetime | None, datetime | None]:
        if ticker in self._ticker_bounds_cache:
            return self._ticker_bounds_cache[ticker]
        table = HistoricalMarketBarRecord.__table__
        row = self.session.execute(
            select(func.min(table.c.bar_time), func.max(table.c.bar_time))
            .where(table.c.ticker == ticker)
            .where(table.c.timeframe == "1m")
        ).one()
        bounds = self._normalize(row[0]), self._normalize(row[1])
        self._ticker_bounds_cache[ticker] = bounds
        return bounds

    def _window_counts(self, ticker: str, start: datetime, end: datetime) -> tuple[int, int]:
        key = (ticker, start, end)
        if key in self._window_counts_cache:
            return self._window_counts_cache[key]
        table = HistoricalMarketBarRecord.__table__
        row = self.session.execute(
            select(func.count(), func.count(func.distinct(func.date(table.c.bar_time))))
            .where(table.c.ticker == ticker)
            .where(table.c.timeframe == "1m")
            .where(table.c.bar_time >= start)
            .where(table.c.bar_time <= end)
            .where(table.c.available_at <= end)
        ).one()
        counts = int(row[0] or 0), int(row[1] or 0)
        self._window_counts_cache[key] = counts
        return counts

    @staticmethod
    def _is_current_session_incomplete(required_end: datetime, latest: datetime) -> bool:
        today = datetime.now(timezone.utc).date()
        return required_end.date() >= today and latest.date() < required_end.date()

    @staticmethod
    def _diagnostic(
        ticker: str,
        start: datetime,
        end: datetime,
        status: str,
        reason: str,
        earliest: datetime | None,
        latest: datetime | None,
        rows: int,
        trading_dates: int,
        required_row_limit: int,
    ) -> ReplayBarCoverageDiagnostic:
        return ReplayBarCoverageDiagnostic(
            ticker=ticker,
            required_start=start,
            required_end=end,
            status=status,
            reason=reason,
            earliest_1m_bar=earliest,
            latest_1m_bar=latest,
            rows_in_window=rows,
            trading_dates_in_window=trading_dates,
            required_row_limit=required_row_limit,
        )

    @staticmethod
    def _normalize(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
