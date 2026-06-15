from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    ObservabilityEventRecord,
    RecommendationDecisionSampleRecord,
    RecommendationPlanRecord,
)
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository


@dataclass(frozen=True)
class GatingSeverityThresholds:
    min_samples: int = 100
    warning_high_priority_non_shortlisted: int = 50
    warning_near_miss_non_shortlisted: int = 100
    warning_positive_gap_non_shortlisted_rate_percent: float = 10.0
    critical_zero_actionable: bool = True


class GatingSeverityAlertService:
    """Detects symptoms that shortlist/signal gating may be too severe."""

    EVENT_TYPE = "decision_gating.severity_check"

    def __init__(
        self,
        session: Session,
        *,
        observability: ObservabilityEventRepository | None = None,
        thresholds: GatingSeverityThresholds | None = None,
    ) -> None:
        self.session = session
        self.observability = observability or ObservabilityEventRepository(session)
        self.thresholds = thresholds or GatingSeverityThresholds()

    def evaluate(
        self,
        *,
        now: datetime | None = None,
        window_days: int = 7,
        record_event: bool = True,
    ) -> dict[str, Any]:
        effective_now = self._normalize(now) or datetime.now(timezone.utc)
        window_start = effective_now - timedelta(days=max(1, int(window_days)))
        metrics = self._metrics(window_start=window_start, window_end=effective_now)
        severity, reasons = self._severity(metrics)
        payload: dict[str, Any] = {
            "window_start": window_start.isoformat(),
            "window_end": effective_now.isoformat(),
            "window_days": max(1, int(window_days)),
            "severity": severity,
            "reasons": reasons,
            "metrics": metrics,
            "interpretation": "Diagnostic only: review near misses and benchmark outcomes before changing gates.",
        }
        if record_event:
            self.observability.record(
                event_type=self.EVENT_TYPE,
                severity=severity,
                source="gating_severity_alerts",
                message=self._message(severity, reasons),
                payload=payload,
            )
        return payload

    def latest_alert(self) -> dict[str, Any] | None:
        record = self.session.scalars(
            select(ObservabilityEventRecord)
            .where(ObservabilityEventRecord.event_type == self.EVENT_TYPE)
            .order_by(
                ObservabilityEventRecord.created_at.desc(), ObservabilityEventRecord.id.desc()
            )
            .limit(1)
        ).first()
        if record is None:
            return None
        payload = self._loads_json_object(record.payload_json)
        return {
            "id": record.id,
            "event_type": record.event_type,
            "severity": record.severity,
            "source": record.source,
            "message": record.message,
            "created_at": self._normalize(record.created_at).isoformat()
            if self._normalize(record.created_at)
            else None,
            "payload": payload,
            **payload,
        }

    def _metrics(self, *, window_start: datetime, window_end: datetime) -> dict[str, Any]:
        sample_base = [
            RecommendationDecisionSampleRecord.created_at >= self._db_dt(window_start),
            RecommendationDecisionSampleRecord.created_at <= self._db_dt(window_end),
        ]
        non_shortlisted = [*sample_base, RecommendationDecisionSampleRecord.shortlisted.is_(False)]
        total_samples = self._count_samples(*sample_base)
        shortlisted_count = self._count_samples(
            *sample_base, RecommendationDecisionSampleRecord.shortlisted.is_(True)
        )
        non_shortlisted_count = self._count_samples(*non_shortlisted)
        near_miss_non_shortlisted = self._count_samples(
            *non_shortlisted, RecommendationDecisionSampleRecord.decision_type == "near_miss"
        )
        high_priority_non_shortlisted = self._count_samples(
            *non_shortlisted, RecommendationDecisionSampleRecord.review_priority == "high"
        )
        positive_gap_non_shortlisted = self._count_samples(
            *non_shortlisted, RecommendationDecisionSampleRecord.confidence_gap_percent > 0
        )
        benchmark_evaluated_non_shortlisted = self._count_samples(
            *non_shortlisted, RecommendationDecisionSampleRecord.benchmark_status != "pending"
        )
        actionable_plans = int(
            self.session.scalar(
                select(func.count())
                .select_from(RecommendationPlanRecord)
                .where(RecommendationPlanRecord.computed_at >= self._db_dt(window_start))
                .where(RecommendationPlanRecord.computed_at <= self._db_dt(window_end))
                .where(RecommendationPlanRecord.action.in_(["long", "short"]))
            )
            or 0
        )
        return {
            "total_samples": total_samples,
            "shortlisted_count": shortlisted_count,
            "non_shortlisted_count": non_shortlisted_count,
            "shortlist_rate_percent": self._pct(shortlisted_count, total_samples),
            "near_miss_non_shortlisted": near_miss_non_shortlisted,
            "high_priority_non_shortlisted": high_priority_non_shortlisted,
            "positive_gap_non_shortlisted": positive_gap_non_shortlisted,
            "positive_gap_non_shortlisted_rate_percent": self._pct(
                positive_gap_non_shortlisted, non_shortlisted_count
            ),
            "benchmark_evaluated_non_shortlisted": benchmark_evaluated_non_shortlisted,
            "benchmark_coverage_non_shortlisted_percent": self._pct(
                benchmark_evaluated_non_shortlisted, non_shortlisted_count
            ),
            "actionable_plans": actionable_plans,
        }

    def _severity(self, metrics: dict[str, Any]) -> tuple[str, list[str]]:
        t = self.thresholds
        reasons: list[str] = []
        if int(metrics["total_samples"]) < t.min_samples:
            return "info", ["insufficient_sample_count"]
        if int(metrics["high_priority_non_shortlisted"]) >= t.warning_high_priority_non_shortlisted:
            reasons.append("many_high_priority_non_shortlisted")
        if int(metrics["near_miss_non_shortlisted"]) >= t.warning_near_miss_non_shortlisted:
            reasons.append("many_near_miss_non_shortlisted")
        if (
            float(metrics["positive_gap_non_shortlisted_rate_percent"] or 0.0)
            >= t.warning_positive_gap_non_shortlisted_rate_percent
        ):
            reasons.append("high_positive_gap_non_shortlisted_rate")
        if (
            int(metrics["benchmark_evaluated_non_shortlisted"]) == 0
            and int(metrics["non_shortlisted_count"]) > 0
        ):
            reasons.append("benchmark_coverage_missing")
        if reasons and t.critical_zero_actionable and int(metrics["actionable_plans"]) == 0:
            reasons.append("zero_actionable_plans")
            return "critical", reasons
        if reasons:
            return "warning", reasons
        return "info", ["gating_severity_within_thresholds"]

    def _count_samples(self, *conditions: object) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(RecommendationDecisionSampleRecord)
                .where(*conditions)
            )
            or 0
        )

    @staticmethod
    def _message(severity: str, reasons: list[str]) -> str:
        return f"Decision gating severity check: {severity} ({', '.join(reasons)})"

    @staticmethod
    def _pct(numerator: int, denominator: int) -> float:
        return round((numerator / denominator) * 100.0, 2) if denominator else 0.0

    @staticmethod
    def _normalize(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _loads_json_object(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _db_dt(cls, value: datetime) -> datetime:
        # Project SQLite/Postgres models commonly persist naive UTC timestamps.
        return cls._normalize(value).replace(tzinfo=None)  # type: ignore[union-attr]
