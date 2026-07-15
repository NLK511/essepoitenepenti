from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    Base,
    PlanGenerationTuningEligibleRecordRecord,
    RecommendationDecisionSampleRecord,
    RecommendationOutcomeRecord,
    RecommendationPlanRecord,
)
from trade_proposer_app.services.historical_confidence_backfill import HistoricalConfidenceBackfillService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _signal_payload() -> dict[str, object]:
    return {
        "setup_family": "catalyst_follow_through",
        "confidence_components": {
            "context_confidence": 80.0,
            "directional_confidence": 80.0,
            "catalyst_confidence": 80.0,
            "market_intelligence_confidence": 80.0,
            "technical_clarity": 80.0,
            "execution_clarity": 80.0,
            "data_quality_cap": 100.0,
        },
        "raw_confidence_percent": 80.0,
        "raw_plan_confidence_percent": 80.0,
        "calibrated_confidence_percent": 80.0,
        "confidence_bucket": "80_plus",
        "calibration_review": {
            "raw_confidence_percent": 80.0,
            "calibrated_confidence_percent": 80.0,
            "confidence_adjustment": 2.0,
        },
    }


def test_historical_confidence_backfill_updates_plan_and_copied_confidence_rows() -> None:
    session = _session()
    try:
        payload = _signal_payload()
        plan = RecommendationPlanRecord(
            ticker="ABC",
            horizon="1w",
            action="long",
            status="ok",
            confidence_percent=80.0,
            signal_breakdown_json=json.dumps(payload),
            computed_at=datetime.now(timezone.utc),
        )
        session.add(plan)
        session.flush()
        session.add(
            RecommendationDecisionSampleRecord(
                recommendation_plan_id=plan.id,
                ticker="ABC",
                horizon="1w",
                action="long",
                decision_type="action",
                confidence_percent=80.0,
                calibrated_confidence_percent=80.0,
                effective_threshold_percent=60.0,
                confidence_gap_percent=20.0,
                signal_breakdown_json=json.dumps(payload),
            )
        )
        session.add(
            PlanGenerationTuningEligibleRecordRecord(
                plan_id=plan.id,
                ticker="ABC",
                action="long",
                computed_at=datetime.now(timezone.utc),
                setup_family="catalyst_follow_through",
                confidence_percent=80.0,
                signal_breakdown_json=json.dumps(payload),
                source_updated_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            RecommendationOutcomeRecord(
                recommendation_plan_id=plan.id,
                outcome="win",
                status="resolved",
                confidence_bucket="80_plus",
            )
        )
        session.commit()

        summary = HistoricalConfidenceBackfillService(session).backfill(dry_run=False)
        session.commit()

        assert summary.updated_plans == 1
        assert summary.updated_decision_samples == 1
        assert summary.updated_tuning_eligible_records == 1
        assert summary.updated_outcome_buckets == 1
        assert plan.confidence_percent == 64.4
        revised_payload = json.loads(plan.signal_breakdown_json)
        assert revised_payload["raw_confidence_percent"] == 64.4
        assert revised_payload["calibrated_confidence_percent"] == 64.4
        assert revised_payload["confidence_bucket"] == "50_to_64"
        assert revised_payload["calibration_review"]["confidence_adjustment"] == 0.0
        sample = session.query(RecommendationDecisionSampleRecord).one()
        assert sample.confidence_percent == 64.4
        assert sample.confidence_gap_percent == 4.4
        eligible = session.query(PlanGenerationTuningEligibleRecordRecord).one()
        assert eligible.confidence_percent == 64.4
        outcome = session.query(RecommendationOutcomeRecord).one()
        assert outcome.confidence_bucket == "50_to_64"
    finally:
        session.close()


def test_historical_confidence_backfill_dry_run_does_not_mutate() -> None:
    session = _session()
    try:
        plan = RecommendationPlanRecord(
            ticker="ABC",
            horizon="1w",
            action="long",
            status="ok",
            confidence_percent=80.0,
            signal_breakdown_json=json.dumps(_signal_payload()),
            computed_at=datetime.now(timezone.utc),
        )
        session.add(plan)
        session.commit()

        summary = HistoricalConfidenceBackfillService(session).backfill(dry_run=True)
        session.rollback()

        assert summary.updated_plans == 1
        assert summary.dry_run is True
        assert plan.confidence_percent == 80.0
    finally:
        session.close()
