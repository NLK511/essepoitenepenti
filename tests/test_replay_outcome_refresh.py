from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar, RecommendationPlan
from trade_proposer_app.persistence.models import Base, HistoricalReplayBatchRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
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
