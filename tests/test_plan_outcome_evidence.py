from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base, ReplayEligibilityRecord
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.plan_outcome_evidence import PlanOutcomeEvidenceService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _plan(ticker: str = "TAG") -> RecommendationPlan:
    return RecommendationPlan(
        ticker=ticker,
        horizon=StrategyHorizon.ONE_WEEK,
        action="watchlist",
        confidence_percent=60.0,
        entry_price_low=100.0,
        entry_price_high=100.0,
        stop_loss=94.0,
        take_profit=112.0,
        signal_breakdown={"setup_family": "breakout"},
        computed_at=datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc),
    )


def test_live_evaluation_outcome_is_canonical_evidence_when_replay_is_absent() -> None:
    session = _session()
    try:
        plan = RecommendationPlanRepository(session).create_plan(_plan())
        RecommendationOutcomeRepository(session).upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome="phantom_win",
                status="resolved",
                confidence_bucket="50_to_64",
                setup_family="breakout",
            )
        )

        evidence = PlanOutcomeEvidenceService(session).best_by_plan_id([plan.id or 0])

        item = evidence[plan.id or 0]
        assert item.outcome == "phantom_win"
        assert item.evidence_source == "live_evaluation"
        assert item.tier == "live"
        assert item.eligible_for_tuning is False
    finally:
        session.close()


def test_replay_evidence_wins_over_live_evaluation_outcome() -> None:
    session = _session()
    try:
        plan = RecommendationPlanRepository(session).create_plan(_plan())
        RecommendationOutcomeRepository(session).upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                action=plan.action,
                outcome="phantom_loss",
                status="resolved",
                confidence_bucket="50_to_64",
                setup_family="breakout",
            )
        )
        session.add(
            ReplayEligibilityRecord(
                replay_batch_id=1,
                replay_slice_id=1,
                recommendation_plan_id=plan.id or 0,
                ticker=plan.ticker,
                candidate_config_hash="",
                tier="tier_a",
                eligible_for_tuning=True,
                resolution_source="intraday",
                outcome="phantom_win",
                rejection_reasons_json="[]",
                diagnostics_json="{}",
            )
        )
        session.commit()

        evidence = PlanOutcomeEvidenceService(session).best_by_plan_id([plan.id or 0])

        item = evidence[plan.id or 0]
        assert item.outcome == "phantom_win"
        assert item.evidence_source == "historical_replay"
        assert item.tier == "tier_a"
        assert item.eligible_for_tuning is True
    finally:
        session.close()
