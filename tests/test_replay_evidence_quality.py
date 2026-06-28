from __future__ import annotations

from trade_proposer_app.services.replay_evidence_quality import (
    ReplayEvidenceQualityThresholds,
    evaluate_replay_evidence_quality,
    replay_outcome_population_rejection_reasons,
)


def test_replay_evidence_quality_flags_phantom_dominated_population_with_caller_reason() -> None:
    reasons = replay_outcome_population_rejection_reasons(
        {"row_count": 10, "phantom_count": 9, "execution_count": 1},
        min_execution_rows=4,
        phantom_reason="custom_phantom_reason",
        empty_reason="custom_empty_reason",
    )

    assert reasons == ["custom_phantom_reason"]


def test_replay_evidence_quality_summary_combines_audit_reasons() -> None:
    result = evaluate_replay_evidence_quality(
        outcome_count=20,
        eligible_count=4,
        unresolved_count=11,
        outcome_population={"row_count": 4, "phantom_count": 4, "execution_count": 0},
        thresholds=ReplayEvidenceQualityThresholds(min_eligible_rows=5, min_execution_rows=2),
    ).to_dict()

    assert result["ready_for_promotion"] is False
    assert result["rejection_reasons"] == [
        "insufficient_eligible_rows",
        "unresolved_heavy_outcomes",
        "phantom_dominated_without_execution_sample",
    ]
    assert result["metrics"]["phantom_ratio"] == 1.0
