from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    Base,
    HistoricalReplayBatchRecord,
    PlanGenerationTuningRunRecord,
    ReplayEligibilityRecord,
    ReplayPlanOutcomeRecord,
)
from trade_proposer_app.services.replay_evidence_audit import ReplayEvidenceAuditConfig, ReplayEvidenceAuditService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_batch(session: Session, *, batch_id: int = 1) -> None:
    session.add(
        HistoricalReplayBatchRecord(
            id=batch_id,
            name=f"batch-{batch_id}",
            status="completed",
            mode="research",
            tickers_json='["AAPL"]',
            as_of_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            as_of_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    )


def test_replay_evidence_audit_flags_phantom_dominated_batch() -> None:
    session = create_session()
    try:
        _seed_batch(session)
        for idx, outcome in enumerate(["phantom_win", "phantom_loss", "phantom_loss", "loss"], start=1):
            session.add(
                ReplayPlanOutcomeRecord(
                    id=idx,
                    replay_batch_id=1,
                    replay_slice_id=idx,
                    recommendation_plan_id=idx,
                    candidate_config_hash="baseline",
                    resolution_source="intraday",
                    outcome=outcome,
                    status="resolved",
                )
            )
            session.add(
                ReplayEligibilityRecord(
                    replay_batch_id=1,
                    replay_slice_id=idx,
                    replay_plan_outcome_id=idx,
                    recommendation_plan_id=idx,
                    ticker="AAPL",
                    candidate_config_hash="baseline",
                    tier="tier_a",
                    eligible_for_tuning=True,
                    resolution_source="intraday",
                    outcome=outcome,
                )
            )
        session.commit()

        audit = ReplayEvidenceAuditService(
            session,
            ReplayEvidenceAuditConfig(min_eligible_rows=1, min_execution_rows=2),
        ).audit_batch(1)

        assert audit["eligible_count"] == 4
        assert audit["outcome_population"]["phantom_count"] == 3
        assert audit["promotion_readiness"]["ready_for_promotion"] is False
        assert "phantom_dominated_without_execution_sample" in audit["promotion_readiness"]["rejection_reasons"]
    finally:
        session.close()


def test_replay_evidence_audit_reads_tuning_run_outcome_population() -> None:
    session = create_session()
    try:
        session.add(
            PlanGenerationTuningRunRecord(
                id=7,
                status="completed",
                mode="fixed_floor_replay_rescore",
                eligible_record_count=10,
                validation_record_count=4,
                candidate_count=20,
                summary_json=json.dumps(
                    {
                        "replay_batch_id": 15,
                        "outcome_population": {
                            "row_count": 10,
                            "phantom_count": 1,
                            "execution_count": 9,
                            "tier_counts": {"tier_a": 10},
                        },
                    }
                ),
                filters_json=json.dumps({"replay_batch_id": 15}),
            )
        )
        session.commit()

        audit = ReplayEvidenceAuditService(
            session,
            ReplayEvidenceAuditConfig(min_eligible_rows=10, min_execution_rows=8),
        ).audit_tuning_run(7)

        assert audit["replay_batch_id"] == 15
        assert audit["promotion_readiness"]["ready_for_promotion"] is True
        assert audit["promotion_readiness"]["rejection_reasons"] == []
    finally:
        session.close()
