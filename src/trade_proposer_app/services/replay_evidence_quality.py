from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReplayEvidenceQualityThresholds:
    min_eligible_rows: int = 10
    min_execution_rows: int = 8
    max_unresolved_ratio: float = 0.5
    max_phantom_ratio_without_execution_sample: float = 0.5

    def to_dict(self) -> dict[str, object]:
        return {
            "min_eligible_rows": self.min_eligible_rows,
            "min_execution_rows": self.min_execution_rows,
            "max_unresolved_ratio": self.max_unresolved_ratio,
            "max_phantom_ratio_without_execution_sample": self.max_phantom_ratio_without_execution_sample,
        }


@dataclass(frozen=True)
class ReplayEvidenceQualityResult:
    ready_for_promotion: bool
    rejection_reasons: list[str]
    thresholds: ReplayEvidenceQualityThresholds
    metrics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "ready_for_promotion": self.ready_for_promotion,
            "rejection_reasons": list(self.rejection_reasons),
            "thresholds": self.thresholds.to_dict(),
            "metrics": dict(self.metrics),
        }


def replay_outcome_population_rejection_reasons(
    outcome_population: dict[str, object] | None,
    *,
    min_execution_rows: int,
    phantom_reason: str,
    empty_reason: str | None = None,
    max_phantom_ratio_without_execution_sample: float = 0.5,
) -> list[str]:
    """Return replay evidence-quality failures derived only from outcome population.

    This is intentionally small and side-effect free so tuning promotion and audit
    reporting cannot drift on phantom/execution sample semantics.
    """
    if not outcome_population:
        return []
    row_count = _int(outcome_population.get("row_count"))
    if row_count <= 0:
        return [empty_reason] if empty_reason else []
    phantom_count = _int(outcome_population.get("phantom_count"))
    execution_count = _int(outcome_population.get("execution_count"))
    phantom_ratio = phantom_count / row_count if row_count else 0.0
    if phantom_ratio > max_phantom_ratio_without_execution_sample and execution_count < max(1, min_execution_rows):
        return [phantom_reason]
    return []


def evaluate_replay_evidence_quality(
    *,
    outcome_count: int,
    eligible_count: int,
    unresolved_count: int,
    outcome_population: dict[str, object] | None,
    thresholds: ReplayEvidenceQualityThresholds | None = None,
) -> ReplayEvidenceQualityResult:
    thresholds = thresholds or ReplayEvidenceQualityThresholds()
    population = outcome_population or {}
    population_count = _int(population.get("row_count")) or eligible_count
    execution_count = _int(population.get("execution_count"))
    phantom_count = _int(population.get("phantom_count"))
    unresolved_ratio = (unresolved_count / outcome_count) if outcome_count else 0.0
    phantom_ratio = (phantom_count / population_count) if population_count else 0.0
    reasons: list[str] = []
    if outcome_count > 0 and eligible_count <= 0:
        reasons.append("zero_eligible_rows")
    if eligible_count < thresholds.min_eligible_rows:
        reasons.append("insufficient_eligible_rows")
    if unresolved_ratio > thresholds.max_unresolved_ratio:
        reasons.append("unresolved_heavy_outcomes")
    reasons.extend(
        replay_outcome_population_rejection_reasons(
            population,
            min_execution_rows=thresholds.min_execution_rows,
            phantom_reason="phantom_dominated_without_execution_sample",
            max_phantom_ratio_without_execution_sample=thresholds.max_phantom_ratio_without_execution_sample,
        )
    )
    return ReplayEvidenceQualityResult(
        ready_for_promotion=not reasons,
        rejection_reasons=reasons,
        thresholds=thresholds,
        metrics={
            "eligible_count": eligible_count,
            "execution_count": execution_count,
            "phantom_count": phantom_count,
            "phantom_ratio": round(phantom_ratio, 4),
            "unresolved_ratio": round(unresolved_ratio, 4),
        },
    )


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
