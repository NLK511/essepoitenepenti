from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scripts.recover_recommendation_plan_evaluations import select_recovery_candidate_ids
from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _plan(ticker: str, *, tagged: bool = False) -> RecommendationPlan:
    signal: dict[str, object] = {"setup_family": "breakout"}
    if tagged:
        signal["upstream_signal_quality_drivers"] = [
            {
                "key": "confidence_35_40",
                "feature": "confidence_bucket",
                "value": "35-40",
                "reason": "test",
            }
        ]
    return RecommendationPlan(
        ticker=ticker,
        horizon=StrategyHorizon.ONE_WEEK,
        action="watchlist",
        confidence_percent=60.0,
        entry_price_low=100.0,
        entry_price_high=100.0,
        stop_loss=94.0,
        take_profit=112.0,
        signal_breakdown=signal,
        computed_at=datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc),
    )


def test_recovery_selector_prioritizes_tagged_missing_outcomes() -> None:
    session = _session()
    try:
        repo = RecommendationPlanRepository(session)
        plain = repo.create_plan(_plan("PLN"))
        tagged = repo.create_plan(_plan("TAG", tagged=True))

        ids = select_recovery_candidate_ids(session, limit=1)

        assert ids == [tagged.id]
        assert plain.id not in ids
    finally:
        session.close()


def test_recovery_selector_skips_existing_outcomes_unless_stale_requested() -> None:
    session = _session()
    try:
        repo = RecommendationPlanRepository(session)
        plan = repo.create_plan(_plan("OLD"))
        RecommendationOutcomeRepository(session).upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="OLD",
                action="watchlist",
                outcome="pending",
                status="open",
                confidence_bucket="50_to_64",
                setup_family="breakout",
            )
        )

        assert select_recovery_candidate_ids(session, limit=10) == []
        assert select_recovery_candidate_ids(
            session, limit=10, include_stale_unresolved=True
        ) == [plan.id]
    finally:
        session.close()
