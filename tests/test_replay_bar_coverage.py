from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar, RecommendationPlan
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.replay_bar_coverage import ReplayBarCoverageService
from scripts.repair_recent_intraday_bar_gaps import _candidate_windows


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _plan(ticker: str, computed_at: datetime, *, horizon=StrategyHorizon.ONE_WEEK) -> RecommendationPlan:
    return RecommendationPlan(
        id=1,
        ticker=ticker,
        action="long",
        horizon=horizon,
        confidence_percent=70,
        entry_price_low=100,
        entry_price_high=101,
        stop_loss=95,
        take_profit=105,
        computed_at=computed_at,
    )


def _bar(ticker: str, bar_time: datetime) -> HistoricalMarketBar:
    return HistoricalMarketBar(
        ticker=ticker,
        timeframe="1m",
        bar_time=bar_time,
        available_at=bar_time + timedelta(minutes=1),
        open_price=100,
        high_price=101,
        low_price=99,
        close_price=100,
        volume=1000,
        source="fixture",
    )


def test_replay_bar_coverage_marks_pre_cache_window_unrecoverable() -> None:
    session = create_session()
    try:
        repository = HistoricalMarketDataRepository(session)
        repository.upsert_bar(_bar("AAPL", datetime(2026, 4, 20, 13, 30, tzinfo=timezone.utc)))

        diagnostic = ReplayBarCoverageService(session).diagnose_plan(
            _plan("AAPL", datetime(2026, 2, 1, 23, 59, 59, tzinfo=timezone.utc)),
            required_end=datetime(2026, 2, 8, 23, 59, 59, tzinfo=timezone.utc),
        )

        assert diagnostic.reason == "outside_local_intraday_cache"
        assert diagnostic.status == "blocked"
    finally:
        session.close()


def test_replay_bar_coverage_marks_current_session_incomplete() -> None:
    session = create_session()
    try:
        repository = HistoricalMarketDataRepository(session)
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        repository.upsert_bar(_bar("AAPL", yesterday.replace(hour=19, minute=59, second=0, microsecond=0)))

        diagnostic = ReplayBarCoverageService(session).diagnose_plan(
            _plan("AAPL", yesterday.replace(hour=13, minute=30, second=0, microsecond=0)),
            required_end=now,
        )

        assert diagnostic.reason == "current_session_incomplete"
    finally:
        session.close()


def test_replay_bar_coverage_marks_loader_limit_truncation_risk() -> None:
    session = create_session()
    try:
        repository = HistoricalMarketDataRepository(session)
        start = datetime(2026, 1, 5, 13, 30, tzinfo=timezone.utc)
        bars = [_bar("AAPL", start + timedelta(minutes=index)) for index in range(2_100)]
        repository.upsert_bars(bars)

        diagnostic = ReplayBarCoverageService(session).diagnose_plan(
            _plan("AAPL", start),
            required_end=start + timedelta(days=7),
        )

        assert diagnostic.reason == "loader_limit_truncated"
        assert diagnostic.required_row_limit > 2_000
        assert diagnostic.rows_in_window == 2_100
    finally:
        session.close()


def test_recent_gap_repair_candidates_skip_old_and_non_gap_rows() -> None:
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    audit = {
        "diagnostics": [
            {
                "diagnostic": {
                    "ticker": "AAPL",
                    "reason": "internal_cache_gap",
                    "required_start": recent.isoformat(),
                    "required_end": (recent + timedelta(days=1)).isoformat(),
                }
            },
            {
                "diagnostic": {
                    "ticker": "MSFT",
                    "reason": "outside_local_intraday_cache",
                    "required_start": recent.isoformat(),
                    "required_end": recent.isoformat(),
                }
            },
            {
                "diagnostic": {
                    "ticker": "ORCL",
                    "reason": "internal_cache_gap",
                    "required_start": old.isoformat(),
                    "required_end": old.isoformat(),
                }
            },
        ]
    }

    windows = _candidate_windows(audit, provider_window_days=7)

    assert windows
    assert {window[0] for window in windows} == {"AAPL"}
