from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextQualityAssessment:
    score: float
    status: str
    flags: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def assess_context_quality(
    *,
    primary_evidence_present: bool,
    primary_coverage_quality: str,
    primary_item_count: int,
    source_priority_counts: dict[str, int] | None = None,
    feed_errors: list[str] | None = None,
    contradiction_count: int = 0,
    summary_error: str | None = None,
) -> ContextQualityAssessment:
    counts = source_priority_counts or {}
    feed_errors = feed_errors or []
    notes: list[str] = []
    flags: dict[str, bool] = {
        "hard_missing": False,
        "partial_coverage": False,
        "provider_failure": False,
        "summary_failure": False,
        "contradictory_evidence": False,
    }

    if not primary_evidence_present or primary_item_count <= 0 or primary_coverage_quality == "missing":
        flags["hard_missing"] = True
        notes.append("primary evidence is missing")

    score = 100.0
    if flags["hard_missing"]:
        score = 12.0
    else:
        if primary_coverage_quality == "medium":
            score -= 10.0
            flags["partial_coverage"] = True
            notes.append("primary evidence coverage is only medium")
        elif primary_coverage_quality == "low":
            score -= 22.0
            flags["partial_coverage"] = True
            notes.append("primary evidence coverage is low")

        if primary_item_count == 1:
            score -= 8.0
            flags["partial_coverage"] = True
            notes.append("primary evidence is thin")
        elif primary_item_count == 2:
            score -= 4.0
            flags["partial_coverage"] = True

        if counts.get("official", 0) == 0 and counts.get("major", 0) == 0:
            score -= 7.0
            flags["partial_coverage"] = True
            notes.append("primary evidence lacks official or major-source coverage")

    if feed_errors:
        flags["provider_failure"] = True
        score -= min(18.0, len(feed_errors) * 6.0)
        notes.append("provider issues were reported while gathering evidence")

    if contradiction_count > 0:
        flags["contradictory_evidence"] = True
        score -= min(24.0, contradiction_count * 8.0)
        notes.append("evidence is contradictory")

    if summary_error:
        flags["summary_failure"] = True
        score -= 8.0
        notes.append("summary generation failed")

    score = max(0.0, min(100.0, score))
    if flags["hard_missing"]:
        status = "blocked"
    elif score >= 80.0:
        status = "usable"
    elif score >= 35.0:
        status = "degraded"
    else:
        status = "blocked"

    return ContextQualityAssessment(score=round(score, 1), status=status, flags=flags, notes=list(dict.fromkeys(notes)))
