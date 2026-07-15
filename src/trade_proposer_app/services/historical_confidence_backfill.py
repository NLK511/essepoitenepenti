from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    PlanGenerationTuningEligibleRecordRecord,
    RecommendationDecisionSampleRecord,
    RecommendationOutcomeRecord,
    RecommendationPlanRecord,
)
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService
from trade_proposer_app.services.watchlist_calibration_review import WatchlistCalibrationReviewService
from trade_proposer_app.utils.json_payloads import loads_json_object


@dataclass(frozen=True)
class HistoricalConfidenceBackfillSummary:
    scanned_plans: int = 0
    updated_plans: int = 0
    skipped_missing_components: int = 0
    updated_decision_samples: int = 0
    updated_tuning_eligible_records: int = 0
    updated_outcome_buckets: int = 0
    average_old_confidence_percent: float | None = None
    average_new_confidence_percent: float | None = None
    average_delta_percent: float | None = None
    max_abs_delta_percent: float = 0.0
    dry_run: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned_plans": self.scanned_plans,
            "updated_plans": self.updated_plans,
            "skipped_missing_components": self.skipped_missing_components,
            "updated_decision_samples": self.updated_decision_samples,
            "updated_tuning_eligible_records": self.updated_tuning_eligible_records,
            "updated_outcome_buckets": self.updated_outcome_buckets,
            "average_old_confidence_percent": self.average_old_confidence_percent,
            "average_new_confidence_percent": self.average_new_confidence_percent,
            "average_delta_percent": self.average_delta_percent,
            "max_abs_delta_percent": self.max_abs_delta_percent,
            "dry_run": self.dry_run,
        }


class HistoricalConfidenceBackfillService:
    """Recompute persisted plan confidence from stored confidence components."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def backfill(self, *, batch_size: int = 1000, limit: int | None = None, dry_run: bool = True) -> HistoricalConfidenceBackfillSummary:
        scanned = 0
        updated = 0
        skipped_missing = 0
        updated_samples = 0
        updated_eligible = 0
        updated_outcomes = 0
        old_sum = 0.0
        new_sum = 0.0
        delta_sum = 0.0
        max_abs_delta = 0.0
        last_id = 0
        now = datetime.now(timezone.utc)
        requested = max(1, int(batch_size))

        while True:
            remaining = None if limit is None else max(0, int(limit) - scanned)
            if remaining == 0:
                break
            current_batch_size = requested if remaining is None else min(requested, remaining)
            plans = self.session.scalars(
                select(RecommendationPlanRecord)
                .where(RecommendationPlanRecord.id > last_id)
                .order_by(RecommendationPlanRecord.id.asc())
                .limit(current_batch_size)
            ).all()
            if not plans:
                break
            last_id = int(plans[-1].id or last_id)
            plan_ids = [int(plan.id or 0) for plan in plans if plan.id is not None]
            sample_by_plan = {
                int(row.recommendation_plan_id): row
                for row in self.session.scalars(
                    select(RecommendationDecisionSampleRecord).where(
                        RecommendationDecisionSampleRecord.recommendation_plan_id.in_(plan_ids)
                    )
                ).all()
                if row.recommendation_plan_id is not None
            }
            eligible_by_plan = {
                int(row.plan_id): row
                for row in self.session.scalars(
                    select(PlanGenerationTuningEligibleRecordRecord).where(
                        PlanGenerationTuningEligibleRecordRecord.plan_id.in_(plan_ids)
                    )
                ).all()
            }
            outcome_by_plan = {
                int(row.recommendation_plan_id): row
                for row in self.session.scalars(
                    select(RecommendationOutcomeRecord).where(
                        RecommendationOutcomeRecord.recommendation_plan_id.in_(plan_ids)
                    )
                ).all()
            }

            for plan in plans:
                scanned += 1
                payload = loads_json_object(plan.signal_breakdown_json)
                new_confidence = self.recompute_confidence(payload)
                if new_confidence is None:
                    skipped_missing += 1
                    continue
                old_confidence = float(plan.confidence_percent or 0.0)
                old_sum += old_confidence
                new_sum += new_confidence
                delta = new_confidence - old_confidence
                delta_sum += delta
                max_abs_delta = max(max_abs_delta, abs(delta))
                if abs(delta) < 0.005:
                    continue

                updated += 1
                plan_id = int(plan.id or 0)
                revised_payload = self.updated_signal_breakdown(payload, new_confidence)
                bucket = WatchlistCalibrationReviewService.confidence_bucket(new_confidence)
                if dry_run:
                    continue

                plan.confidence_percent = new_confidence
                plan.signal_breakdown_json = self._dump(revised_payload)

                sample = sample_by_plan.get(plan_id)
                if sample is not None:
                    sample.confidence_percent = new_confidence
                    sample.calibrated_confidence_percent = new_confidence
                    if sample.effective_threshold_percent is not None:
                        sample.confidence_gap_percent = round(new_confidence - float(sample.effective_threshold_percent), 2)
                    sample.signal_breakdown_json = self._dump(revised_payload)
                    updated_samples += 1

                eligible = eligible_by_plan.get(plan_id)
                if eligible is not None:
                    eligible.confidence_percent = new_confidence
                    eligible.signal_breakdown_json = self._dump(revised_payload)
                    eligible.source_updated_at = now
                    updated_eligible += 1

                outcome = outcome_by_plan.get(plan_id)
                if outcome is not None:
                    outcome.confidence_bucket = bucket
                    updated_outcomes += 1

            if not dry_run:
                self.session.flush()

        counted = scanned - skipped_missing
        return HistoricalConfidenceBackfillSummary(
            scanned_plans=scanned,
            updated_plans=updated,
            skipped_missing_components=skipped_missing,
            updated_decision_samples=updated_samples,
            updated_tuning_eligible_records=updated_eligible,
            updated_outcome_buckets=updated_outcomes,
            average_old_confidence_percent=self._average(old_sum, counted),
            average_new_confidence_percent=self._average(new_sum, counted),
            average_delta_percent=self._average(delta_sum, counted),
            max_abs_delta_percent=round(max_abs_delta, 4),
            dry_run=dry_run,
        )

    @classmethod
    def recompute_confidence(cls, signal_breakdown: dict[str, Any]) -> float | None:
        components = signal_breakdown.get("confidence_components")
        if not isinstance(components, dict) or not components:
            return None
        setup_family = str(signal_breakdown.get("setup_family") or "").strip().lower() or None
        return TickerDeepAnalysisService._compose_confidence(components, setup_family=setup_family)

    @staticmethod
    def updated_signal_breakdown(signal_breakdown: dict[str, Any], confidence_percent: float) -> dict[str, Any]:
        payload = dict(signal_breakdown)
        rounded = round(float(confidence_percent), 2)
        payload["raw_confidence_percent"] = rounded
        payload["raw_plan_confidence_percent"] = rounded
        payload["calibrated_confidence_percent"] = rounded
        payload["confidence_bucket"] = WatchlistCalibrationReviewService.confidence_bucket(rounded)
        review = payload.get("calibration_review")
        if isinstance(review, dict):
            revised_review = dict(review)
            revised_review["raw_confidence_percent"] = rounded
            revised_review["calibrated_confidence_percent"] = rounded
            revised_review["confidence_adjustment"] = 0.0
            payload["calibration_review"] = revised_review
        return payload

    @staticmethod
    def _average(total: float, count: int) -> float | None:
        if count <= 0:
            return None
        return round(total / count, 4)

    @staticmethod
    def _dump(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, default=str)
