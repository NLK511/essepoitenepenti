from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import RecommendationOutcomeRecord, ReplayEligibilityRecord


@dataclass(frozen=True, slots=True)
class PlanOutcomeEvidence:
    recommendation_plan_id: int
    outcome: str
    status: str
    evidence_source: str
    resolution_source: str
    tier: str
    eligible_for_tuning: bool
    evaluated_at: datetime | None
    updated_at: datetime | None


class PlanOutcomeEvidenceService:
    """Reads best available outcome evidence without exposing storage quirks."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def best_by_plan_id(self, plan_ids: list[int]) -> dict[int, PlanOutcomeEvidence]:
        normalized_ids = sorted({int(plan_id) for plan_id in plan_ids if int(plan_id) > 0})
        if not normalized_ids:
            return {}

        evidence: dict[int, PlanOutcomeEvidence] = {}
        for item in self._recommendation_outcome_evidence(normalized_ids):
            evidence[item.recommendation_plan_id] = item
        for item in self._replay_eligibility_evidence(normalized_ids):
            current = evidence.get(item.recommendation_plan_id)
            if current is None or self._rank(item) > self._rank(current):
                evidence[item.recommendation_plan_id] = item
        return evidence

    def _recommendation_outcome_evidence(
        self, plan_ids: list[int]
    ) -> list[PlanOutcomeEvidence]:
        rows = self.session.scalars(
            select(RecommendationOutcomeRecord).where(
                RecommendationOutcomeRecord.recommendation_plan_id.in_(plan_ids)
            )
        ).all()
        evidence: list[PlanOutcomeEvidence] = []
        for row in rows:
            outcome = self._clean(row.outcome)
            if outcome in {"", "unknown", "open", "pending"}:
                continue
            evidence.append(
                PlanOutcomeEvidence(
                    recommendation_plan_id=int(row.recommendation_plan_id),
                    outcome=outcome,
                    status=self._clean(row.status) or "unknown",
                    evidence_source="live_evaluation",
                    resolution_source="recommendation_evaluation",
                    tier="live",
                    eligible_for_tuning=False,
                    evaluated_at=self._as_utc(row.evaluated_at),
                    updated_at=self._as_utc(row.updated_at),
                )
            )
        return evidence

    def _replay_eligibility_evidence(self, plan_ids: list[int]) -> list[PlanOutcomeEvidence]:
        rows = self.session.scalars(
            select(ReplayEligibilityRecord)
            .where(ReplayEligibilityRecord.recommendation_plan_id.in_(plan_ids))
            .order_by(
                ReplayEligibilityRecord.recommendation_plan_id.asc(),
                ReplayEligibilityRecord.tier.asc(),
                ReplayEligibilityRecord.updated_at.desc(),
                ReplayEligibilityRecord.id.desc(),
            )
        ).all()
        best: dict[int, PlanOutcomeEvidence] = {}
        for row in rows:
            outcome = self._clean(row.outcome)
            if outcome in {"", "unknown", "open", "pending"}:
                continue
            item = PlanOutcomeEvidence(
                recommendation_plan_id=int(row.recommendation_plan_id),
                outcome=outcome,
                status="resolved",
                evidence_source="historical_replay",
                resolution_source=self._clean(row.resolution_source) or "unknown",
                tier=self._clean(row.tier) or "tier_c",
                eligible_for_tuning=bool(row.eligible_for_tuning),
                evaluated_at=None,
                updated_at=self._as_utc(row.updated_at),
            )
            current = best.get(item.recommendation_plan_id)
            if current is None or self._rank(item) > self._rank(current):
                best[item.recommendation_plan_id] = item
        return list(best.values())

    @classmethod
    def _rank(cls, item: PlanOutcomeEvidence) -> tuple[int, int, int, datetime]:
        source_rank = 2 if item.evidence_source == "historical_replay" else 1
        resolution_rank = 2 if item.resolution_source == "intraday" else 1
        tier_rank = {"tier_a": 3, "tier_b": 2, "tier_c": 1, "live": 0}.get(item.tier, 0)
        updated_at = item.updated_at or item.evaluated_at or datetime.min.replace(tzinfo=timezone.utc)
        return (source_rank, resolution_rank, tier_rank, updated_at)

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
