from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import Base, RecommendationPlanRecord, ReplayEligibilityRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.services.replay_validation_efficiency import (
    CandidateEarlyStopPolicy,
    CandidateReplayPlanner,
    FrozenInputPlanRegenerationService,
    ReplayValidationAggregateService,
)


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_frozen_input_plan_regeneration_adjusts_geometry_without_remote_inputs() -> None:
    plan = RecommendationPlanRecord(
        id=10,
        ticker="AAPL",
        horizon="1w",
        action="long",
        status="ok",
        confidence_percent=70.0,
        entry_price_low=100.0,
        entry_price_high=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        evidence_summary_json='{"setup_family":"breakout","volatility_score":50}',
        signal_breakdown_json="{}",
        computed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    result = FrozenInputPlanRegenerationService().regenerate_levels(
        plan,
        tuning_config={
            "global.entry_band_risk_fraction": 0.1,
            "setup_family.breakout.stop_distance_multiplier": 0.8,
            "setup_family.breakout.take_profit_distance_multiplier": 1.2,
        },
    )

    assert result["status"] == "ok"
    assert result["validation_depth"] == "frozen_input_plan_regeneration"
    assert result["remote_fetch_used"] is False
    assert result["entry_price_low"] == 99.5
    assert result["entry_price_high"] == 100.5
    assert result["stop_loss"] == 96.0
    assert result["take_profit"] == 112.0


def test_candidate_replay_planner_deduplicates_and_labels_depths() -> None:
    candidates = [
        SimpleNamespace(id=1, rank=1, changed_keys=["global.actionable_confidence_floor_percent"], config={"global.actionable_confidence_floor_percent": 65.0}),
        SimpleNamespace(id=2, rank=2, changed_keys=["setup_family.breakout.stop_distance_multiplier"], config={"setup_family.breakout.stop_distance_multiplier": 0.8}),
        SimpleNamespace(id=3, rank=3, changed_keys=["setup_family.breakout.stop_distance_multiplier"], config={"setup_family.breakout.stop_distance_multiplier": 0.8}),
    ]

    plans = CandidateReplayPlanner().plan(candidates)

    assert plans[0].validation_depth == "rescore_only"
    assert plans[0].replay_required is False
    assert plans[1].validation_depth == "frozen_input_plan_regeneration"
    assert plans[1].replay_required is True
    assert plans[2].replay_required is False
    assert plans[2].skip_reason == "duplicate config of candidate 2"


def test_replay_validation_aggregate_and_early_stop_policy() -> None:
    session = create_session()
    try:
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)
        for index in range(60):
            outcome = "loss" if index < 50 else "win"
            session.add(
                ReplayPlanOutcomeRecord(
                    replay_batch_id=1,
                    replay_slice_id=1,
                    recommendation_plan_id=index + 1,
                    candidate_config_hash="candidate-a",
                    resolution_source="intraday",
                    outcome=outcome,
                    status="resolved",
                    evaluated_at=now,
                    outcome_json="{}",
                )
            )
            session.add(
                ReplayEligibilityRecord(
                    replay_batch_id=1,
                    replay_slice_id=1,
                    recommendation_plan_id=index + 1,
                    candidate_config_hash="candidate-a",
                    ticker="AAPL" if index < 30 else f"T{index}",
                    tier="tier_c" if index < 40 else "tier_a",
                    eligible_for_tuning=index >= 40,
                    resolution_source="intraday",
                    outcome=outcome,
                    diagnostics_json='{"setup_family":"breakout"}',
                )
            )
        session.commit()

        aggregate = ReplayValidationAggregateService(session).aggregate_batch(1, candidate_config_hash="candidate-a")
        decision = CandidateEarlyStopPolicy(min_evidence_count=50).evaluate(aggregate)

        assert aggregate["eligibility_count"] == 60
        assert aggregate["resolved_count"] == 60
        assert aggregate["loss_count"] == 50
        assert aggregate["win_count"] == 10
        assert aggregate["top_ticker_concentration_percent"] == 50.0
        assert decision.should_stop is True
        assert decision.reason in {"tier_a_ratio_too_low", "ticker_concentration_too_high", "loss_to_win_ratio_too_high"}
    finally:
        session.close()
