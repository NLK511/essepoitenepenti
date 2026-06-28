from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    HistoricalReplayBatchRecord,
    PlanGenerationTuningRunRecord,
    ReplayEligibilityRecord,
    ReplayPlanOutcomeRecord,
)
from trade_proposer_app.services.outcome_population import summarize_outcome_population
from trade_proposer_app.services.replay_evidence_quality import (
    ReplayEvidenceQualityThresholds,
    evaluate_replay_evidence_quality,
)
from trade_proposer_app.utils.json_payloads import loads_json_object


ReplayEvidenceAuditConfig = ReplayEvidenceQualityThresholds


class ReplayEvidenceAuditService:
    def __init__(self, session: Session, config: ReplayEvidenceAuditConfig | None = None) -> None:
        self.session = session
        self.config = config or ReplayEvidenceQualityThresholds()

    def audit_batch(self, replay_batch_id: int) -> dict[str, Any]:
        batch = self.session.get(HistoricalReplayBatchRecord, replay_batch_id)
        if batch is None:
            raise ValueError(f"replay batch {replay_batch_id} not found")
        outcomes = self.session.scalars(
            select(ReplayPlanOutcomeRecord).where(ReplayPlanOutcomeRecord.replay_batch_id == replay_batch_id)
        ).all()
        eligibility_rows = self.session.scalars(
            select(ReplayEligibilityRecord).where(ReplayEligibilityRecord.replay_batch_id == replay_batch_id)
        ).all()
        eligible_rows = [row for row in eligibility_rows if row.eligible_for_tuning]
        outcome_counts = self._count_by(outcomes, "outcome")
        status_counts = self._count_by(outcomes, "status")
        tier_counts = self._count_by(eligibility_rows, "tier")
        eligible_tier_counts = self._count_by(eligible_rows, "tier")
        unresolved_count = sum(1 for row in outcomes if str(row.status or "") != "resolved")
        outcome_population = summarize_outcome_population(
            eligible_rows,
            population="replay_eligible_rows",
            outcome_attr="outcome",
            tier_attr="tier",
        )
        checks = self._quality_checks(
            outcome_count=len(outcomes),
            eligible_count=len(eligible_rows),
            unresolved_count=unresolved_count,
            outcome_population=outcome_population,
        )
        return {
            "audit_type": "replay_batch",
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "replay_batch": {
                "id": batch.id,
                "name": batch.name,
                "status": batch.status,
                "mode": batch.mode,
                "as_of_start": batch.as_of_start.isoformat() if batch.as_of_start else None,
                "as_of_end": batch.as_of_end.isoformat() if batch.as_of_end else None,
            },
            "outcome_count": len(outcomes),
            "eligibility_count": len(eligibility_rows),
            "eligible_count": len(eligible_rows),
            "outcome_counts": outcome_counts,
            "outcome_status_counts": status_counts,
            "tier_counts": tier_counts,
            "eligible_tier_counts": eligible_tier_counts,
            "unresolved_count": unresolved_count,
            "unresolved_ratio": round((unresolved_count / len(outcomes)) if outcomes else 0.0, 4),
            "outcome_population": outcome_population,
            "promotion_readiness": checks,
        }

    def audit_tuning_run(self, run_id: int) -> dict[str, Any]:
        run = self.session.get(PlanGenerationTuningRunRecord, run_id)
        if run is None:
            raise ValueError(f"plan generation tuning run {run_id} not found")
        summary = loads_json_object(run.summary_json)
        population = summary.get("outcome_population") if isinstance(summary.get("outcome_population"), dict) else {}
        replay_batch_id = summary.get("replay_batch_id") or loads_json_object(run.filters_json).get("replay_batch_id")
        checks = self._quality_checks(
            outcome_count=int(population.get("row_count") or run.eligible_record_count or 0),
            eligible_count=int(run.eligible_record_count or 0),
            unresolved_count=0,
            outcome_population=population,
        )
        return {
            "audit_type": "plan_generation_tuning_run",
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "id": run.id,
                "status": run.status,
                "mode": run.mode,
                "promotion_mode": run.promotion_mode,
                "winning_candidate_id": run.winning_candidate_id,
                "promoted_config_version_id": run.promoted_config_version_id,
                "eligible_record_count": run.eligible_record_count,
                "validation_record_count": run.validation_record_count,
                "candidate_count": run.candidate_count,
            },
            "replay_batch_id": int(replay_batch_id) if replay_batch_id else None,
            "outcome_population": population,
            "promotion_readiness": checks,
        }

    def _quality_checks(
        self,
        *,
        outcome_count: int,
        eligible_count: int,
        unresolved_count: int,
        outcome_population: dict[str, object],
    ) -> dict[str, object]:
        return evaluate_replay_evidence_quality(
            outcome_count=outcome_count,
            eligible_count=eligible_count,
            unresolved_count=unresolved_count,
            outcome_population=outcome_population,
            thresholds=self.config,
        ).to_dict()

    @staticmethod
    def _count_by(rows: list[object], attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            key = str(getattr(row, attr, None) or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return counts

