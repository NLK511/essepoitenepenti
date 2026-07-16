from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base, HistoricalReplayBatchRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.replay_plan_outcomes import ReplayPlanOutcomeRepository
from trade_proposer_app.services.replay_outcome_refresh import ReplayOutcomeRefreshService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_replay_outcome_refresh_updates_only_open_rows_by_default() -> None:
    session = create_session()
    try:
        as_of = datetime(2026, 1, 5, 23, 59, 59, tzinfo=timezone.utc)
        session.add(
            HistoricalReplayBatchRecord(
                id=1,
                name="refresh-batch",
                status="completed",
                mode="research",
                tickers_json='["AAPL", "MSFT"]',
                as_of_start=as_of - timedelta(days=1),
                as_of_end=as_of,
            )
        )
        plans = RecommendationPlanRepository(session)
        open_plan = plans.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70,
                entry_price_low=100,
                entry_price_high=101,
                stop_loss=95,
                take_profit=105,
                computed_at=as_of,
                signal_breakdown={"replay_provenance": {"as_of": as_of.isoformat()}},
            )
        )
        resolved_plan = plans.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70,
                entry_price_low=200,
                entry_price_high=201,
                stop_loss=195,
                take_profit=205,
                computed_at=as_of,
            )
        )
        session.add_all(
            [
                ReplayPlanOutcomeRecord(
                    id=1,
                    replay_batch_id=1,
                    replay_slice_id=1,
                    recommendation_plan_id=open_plan.id or 0,
                    candidate_config_hash="baseline",
                    resolution_source="none",
                    outcome="open",
                    status="open",
                    outcome_json=json.dumps({"outcome": "open", "status": "open"}),
                ),
                ReplayPlanOutcomeRecord(
                    id=2,
                    replay_batch_id=1,
                    replay_slice_id=1,
                    recommendation_plan_id=resolved_plan.id or 0,
                    candidate_config_hash="baseline",
                    resolution_source="intraday",
                    outcome="loss",
                    status="resolved",
                    outcome_json=json.dumps({"outcome": "loss", "status": "resolved"}),
                ),
            ]
        )
        market = HistoricalMarketDataRepository(session)
        for offset, high, low, close in [(timedelta(minutes=1), 102, 99, 101), (timedelta(minutes=2), 106, 101, 105.5)]:
            bar_time = as_of + offset
            market.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=bar_time,
                    available_at=bar_time,
                    open_price=100,
                    high_price=high,
                    low_price=low,
                    close_price=close,
                    volume=1000,
                    source="fixture",
                )
            )
        session.commit()

        with patch(
            "trade_proposer_app.services.recommendation_plan_evaluations.RecommendationPlanEvaluationService._download_price_history",
            side_effect=AssertionError("cache-only refresh must not call remote price history"),
        ):
            summary = ReplayOutcomeRefreshService(session).refresh_batch(1, as_of=as_of + timedelta(days=1), reclassify=False)

        assert summary.selected_outcome_count == 1
        assert summary.refreshed_outcome_count == 1
        assert summary.before_status_counts == {"open": 1}
        assert summary.after_outcome_counts == {"win": 1}
        refreshed_open = session.get(ReplayPlanOutcomeRecord, 1)
        untouched_resolved = session.get(ReplayPlanOutcomeRecord, 2)
        assert refreshed_open is not None and refreshed_open.outcome == "win"
        assert untouched_resolved is not None and untouched_resolved.outcome == "loss"
    finally:
        session.close()


def test_replay_outcome_refresh_filters_by_resolution_source() -> None:
    session = create_session()
    try:
        as_of = datetime(2026, 1, 5, 23, 59, 59, tzinfo=timezone.utc)
        session.add(
            HistoricalReplayBatchRecord(
                id=1,
                name="refresh-pending-source-batch",
                status="completed",
                mode="research",
                tickers_json='["AAPL", "MSFT"]',
                as_of_start=as_of - timedelta(days=1),
                as_of_end=as_of,
            )
        )
        plans = RecommendationPlanRepository(session)
        pending_source_plan = plans.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70,
                entry_price_low=100,
                entry_price_high=101,
                stop_loss=95,
                take_profit=105,
                computed_at=as_of - timedelta(days=14),
            )
        )
        clean_plan = plans.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70,
                entry_price_low=200,
                entry_price_high=201,
                stop_loss=195,
                take_profit=205,
                computed_at=as_of,
            )
        )
        session.add_all(
            [
                ReplayPlanOutcomeRecord(
                    id=1,
                    replay_batch_id=1,
                    replay_slice_id=1,
                    recommendation_plan_id=pending_source_plan.id or 0,
                    candidate_config_hash="baseline",
                    resolution_source="pending",
                    outcome="expired",
                    status="resolved",
                    outcome_json=json.dumps({"outcome": "expired", "status": "resolved"}),
                ),
                ReplayPlanOutcomeRecord(
                    id=2,
                    replay_batch_id=1,
                    replay_slice_id=1,
                    recommendation_plan_id=clean_plan.id or 0,
                    candidate_config_hash="baseline",
                    resolution_source="intraday",
                    outcome="loss",
                    status="resolved",
                    outcome_json=json.dumps({"outcome": "loss", "status": "resolved"}),
                ),
            ]
        )
        session.commit()

        with patch(
            "trade_proposer_app.services.recommendation_plan_evaluations.RecommendationPlanEvaluationService._download_price_history",
            side_effect=AssertionError("cache-only refresh must not call remote price history"),
        ):
            summary = ReplayOutcomeRefreshService(session).refresh_batch(
                1,
                as_of=as_of,
                include_resolved=True,
                reclassify=False,
                resolution_sources={"pending"},
            )

        assert summary.selected_outcome_count == 1
        assert summary.refreshed_outcome_count == 1
        refreshed_pending = session.get(ReplayPlanOutcomeRecord, 1)
        untouched_clean = session.get(ReplayPlanOutcomeRecord, 2)
        assert refreshed_pending is not None and refreshed_pending.resolution_source == "pending"
        assert untouched_clean is not None
        assert untouched_clean.resolution_source == "intraday"
        assert untouched_clean.outcome == "loss"
    finally:
        session.close()


def test_replay_outcome_refresh_can_use_latest_complete_cached_session_as_of() -> None:
    session = create_session()
    try:
        repository = HistoricalMarketDataRepository(session)
        latest = datetime(2026, 1, 7, 19, 59, tzinfo=timezone.utc)
        repository.upsert_bar(
            HistoricalMarketBar(
                ticker="AAPL",
                timeframe="1m",
                bar_time=latest,
                available_at=latest + timedelta(minutes=1),
                open_price=100,
                high_price=101,
                low_price=99,
                close_price=100,
                volume=1000,
                source="fixture",
            )
        )
        plan = RecommendationPlan(
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            action="long",
            confidence_percent=70,
            entry_price_low=100,
            entry_price_high=101,
            stop_loss=95,
            take_profit=105,
            computed_at=datetime(2026, 1, 5, 23, 59, 59, tzinfo=timezone.utc),
        )

        resolved = ReplayOutcomeRefreshService(session)._resolve_as_of(  # noqa: SLF001
            [plan],
            explicit_as_of=None,
            mode="latest_complete_cached_session",
        )

        assert resolved == datetime(2026, 1, 7, 23, 59, 59, tzinfo=timezone.utc)
    finally:
        session.close()


def test_replay_outcome_refresh_uses_lightweight_loader_and_bulk_persistence() -> None:
    session = create_session()
    try:
        as_of = datetime(2026, 1, 5, 23, 59, 59, tzinfo=timezone.utc)
        session.add(
            HistoricalReplayBatchRecord(
                id=1,
                name="refresh-lightweight-batch",
                status="completed",
                mode="research",
                tickers_json='["AAPL"]',
                as_of_start=as_of - timedelta(days=1),
                as_of_end=as_of,
            )
        )
        plans = RecommendationPlanRepository(session)
        plan = plans.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70,
                entry_price_low=100,
                entry_price_high=101,
                stop_loss=95,
                take_profit=105,
                computed_at=as_of,
                signal_breakdown={"setup_family": "fixture_family"},
            )
        )
        session.add(
            ReplayPlanOutcomeRecord(
                id=1,
                replay_batch_id=1,
                replay_slice_id=1,
                recommendation_plan_id=plan.id or 0,
                candidate_config_hash="baseline",
                resolution_source="pending",
                outcome="open",
                status="open",
                outcome_json=json.dumps({"outcome": "open", "status": "open"}),
            )
        )
        market = HistoricalMarketDataRepository(session)
        for offset, high, low, close in [(timedelta(minutes=1), 102, 99, 101), (timedelta(minutes=2), 106, 101, 105.5)]:
            bar_time = as_of + offset
            market.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=bar_time,
                    available_at=bar_time,
                    open_price=100,
                    high_price=high,
                    low_price=low,
                    close_price=close,
                    volume=1000,
                    source="fixture",
                )
            )
        session.commit()

        with patch.object(RecommendationPlanRepository, "get_plan", side_effect=AssertionError("full plan hydration forbidden")), patch.object(
            ReplayPlanOutcomeRepository,
            "upsert_outcome",
            side_effect=AssertionError("per-row outcome upsert forbidden"),
        ), patch(
            "trade_proposer_app.services.recommendation_plan_evaluations.RecommendationPlanEvaluationService._download_price_history",
            side_effect=AssertionError("cache-only refresh must not call remote price history"),
        ):
            summary = ReplayOutcomeRefreshService(session).refresh_batch(
                1,
                as_of=as_of + timedelta(days=1),
                reclassify=False,
                limit=1,
                profile=True,
            )

        assert summary.selected_outcome_count == 1
        assert summary.refreshed_outcome_count == 1
        assert summary.timing_seconds
        assert "plan_loading" in summary.timing_seconds
        assert "outcome_persistence" in summary.timing_seconds
        refreshed = session.get(ReplayPlanOutcomeRecord, 1)
        assert refreshed is not None
        assert refreshed.outcome == "win"
    finally:
        session.close()


def test_replay_plan_outcomes_bulk_upsert_updates_existing_rows() -> None:
    session = create_session()
    try:
        evaluated_at = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)
        session.add(
            ReplayPlanOutcomeRecord(
                id=1,
                replay_batch_id=1,
                replay_slice_id=1,
                recommendation_plan_id=11,
                candidate_config_hash="baseline",
                resolution_source="pending",
                outcome="open",
                status="open",
                outcome_json=json.dumps({"outcome": "open", "status": "open"}),
            )
        )
        session.commit()

        count = ReplayPlanOutcomeRepository(session).bulk_upsert_outcomes(
            [
                {
                    "replay_batch_id": 1,
                    "replay_slice_id": 1,
                    "run_id": None,
                    "recommendation_plan_id": 11,
                    "candidate_config_hash": "baseline",
                    "resolution_source": "intraday",
                    "outcome": RecommendationPlanOutcome(
                        recommendation_plan_id=11,
                        ticker="AAPL",
                        action="long",
                        outcome="win",
                        status="resolved",
                        evaluated_at=evaluated_at,
                    ),
                },
                {
                    "replay_batch_id": 1,
                    "replay_slice_id": 1,
                    "run_id": None,
                    "recommendation_plan_id": 12,
                    "candidate_config_hash": "baseline",
                    "resolution_source": "intraday",
                    "outcome": RecommendationPlanOutcome(
                        recommendation_plan_id=12,
                        ticker="MSFT",
                        action="long",
                        outcome="loss",
                        status="resolved",
                        evaluated_at=evaluated_at,
                    ),
                },
            ]
        )

        assert count == 2
        rows = session.query(ReplayPlanOutcomeRecord).order_by(ReplayPlanOutcomeRecord.recommendation_plan_id).all()
        assert [row.recommendation_plan_id for row in rows] == [11, 12]
        assert [row.outcome for row in rows] == ["win", "loss"]
        assert rows[0].resolution_source == "intraday"
    finally:
        session.close()


def test_replay_outcome_refresh_skips_intraday_load_when_daily_prefilter_is_enough() -> None:
    session = create_session()
    try:
        as_of = datetime(2026, 1, 5, 23, 59, 59, tzinfo=timezone.utc)
        session.add(
            HistoricalReplayBatchRecord(
                id=1,
                name="refresh-daily-prefilter-batch",
                status="completed",
                mode="research",
                tickers_json='["AAPL"]',
                as_of_start=as_of - timedelta(days=1),
                as_of_end=as_of,
            )
        )
        plans = RecommendationPlanRepository(session)
        plan = plans.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=70,
                entry_price_low=100,
                entry_price_high=101,
                stop_loss=95,
                take_profit=105,
                computed_at=as_of,
            )
        )
        session.add(
            ReplayPlanOutcomeRecord(
                id=1,
                replay_batch_id=1,
                replay_slice_id=1,
                recommendation_plan_id=plan.id or 0,
                candidate_config_hash="baseline",
                resolution_source="pending",
                outcome="open",
                status="open",
                outcome_json=json.dumps({"outcome": "open", "status": "open"}),
            )
        )
        market = HistoricalMarketDataRepository(session)
        market.upsert_bar(
            HistoricalMarketBar(
                ticker="AAPL",
                timeframe="1d",
                bar_time=as_of + timedelta(days=1),
                available_at=as_of + timedelta(days=1, hours=23),
                open_price=98,
                high_price=99,
                low_price=96,
                close_price=98,
                volume=1000,
                source="fixture",
            )
        )
        session.commit()

        with patch(
            "trade_proposer_app.services.recommendation_plan_evaluations.RecommendationPlanEvaluationService._download_price_history",
            side_effect=AssertionError("cache-only refresh must not call remote price history"),
        ):
            summary = ReplayOutcomeRefreshService(session).refresh_batch(
                1,
                as_of=as_of + timedelta(days=2),
                reclassify=False,
                profile=True,
            )

        refreshed = session.get(ReplayPlanOutcomeRecord, 1)
        assert refreshed is not None
        assert refreshed.resolution_source == "daily_prefilter"
        assert summary.price_history_diagnostics["intraday_required_plan_count"] == 0
        assert summary.price_history_diagnostics["daily_prefilter_plan_count"] == 1
    finally:
        session.close()
