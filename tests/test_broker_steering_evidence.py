from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.services.broker_steering_evidence import BrokerSteeringEvidenceBuilder

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_broker_steering_evidence_builds_fresh_severe_invalidation_from_market_conflict() -> None:
    plan = RecommendationPlan(
        id=7,
        ticker="AAPL",
        action="long",
        confidence_percent=70.0,
        signal_breakdown={"market_intelligence_conflict_flags": ["thesis_invalidated"]},
        computed_at=NOW,
    )

    evidence = BrokerSteeringEvidenceBuilder().build(plan, now=NOW)

    assert evidence["freshness_status"] == "fresh"
    assert evidence["severe_invalidation_reasons"] == ["thesis_invalidated"]
    assert BrokerSteeringEvidenceBuilder.has_severe_invalidation(evidence)


def test_broker_steering_evidence_stale_payload_does_not_invalidate() -> None:
    plan = RecommendationPlan(
        id=7,
        ticker="AAPL",
        action="long",
        signal_breakdown={"market_intelligence_conflict_flags": ["thesis_invalidated"]},
        computed_at=NOW - timedelta(days=3),
    )

    evidence = BrokerSteeringEvidenceBuilder().build(plan, now=NOW)

    assert evidence["freshness_status"] == "stale"
    assert evidence["severe_invalidation_reasons"] == []
    assert not BrokerSteeringEvidenceBuilder.has_severe_invalidation(evidence)
