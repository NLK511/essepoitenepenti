#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import (
    RecommendationPlanRecord,
    ReplayEligibilityRecord,
)
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_outcome_evidence import PlanOutcomeEvidenceService
from trade_proposer_app.utils.json_payloads import loads_json_object


@dataclass(frozen=True, slots=True)
class LineageReplayRow:
    replay: ReplayEligibilityRecord
    computed_at: datetime | None


def run_audit(
    *,
    artifact_path: Path,
    tiers: set[str],
    limit: int | None = None,
) -> dict[str, object]:
    session = SessionLocal()
    try:
        tagged_plans = _tagged_plan_rows(session, limit=limit)
        evidence_by_plan_id = PlanOutcomeEvidenceService(session).best_by_plan_id(
            [int(row.id) for row in tagged_plans]
        )
        replay_rows = _replay_rows(session, limit=limit)
        current_versions = (
            PlanGenerationTuningService._current_replay_artifact_versions()  # noqa: SLF001
        )
        current_replay_rows = [
            row
            for row in replay_rows
            if PlanGenerationTuningService._replay_artifact_versions_current(  # noqa: SLF001
                loads_json_object(row.replay.diagnostics_json),
                current_versions,
            )
        ]
        phantom_rows = [
            row
            for row in replay_rows
            if bool(row.replay.eligible_for_tuning)
            and str(row.replay.tier or "").strip() in tiers
            and str(row.replay.resolution_source or "").strip().lower() == "intraday"
            and str(row.replay.outcome or "").strip().lower() in {"phantom_win", "phantom_loss"}
        ]
        current_phantom_rows = [
            row
            for row in current_replay_rows
            if bool(row.replay.eligible_for_tuning)
            and str(row.replay.tier or "").strip() in tiers
            and str(row.replay.resolution_source or "").strip().lower() == "intraday"
            and str(row.replay.outcome or "").strip().lower() in {"phantom_win", "phantom_loss"}
        ]
        replay_labeled_tagged_plans = [
            row
            for row in tagged_plans
            if (evidence_by_plan_id.get(int(row.id)) is not None)
            and evidence_by_plan_id[int(row.id)].evidence_source == "historical_replay"
        ]
        report = {
            "schema_version": "evidence-lineage-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "tiers": sorted(tiers),
                "limit": limit,
            },
            "current_replay_artifact_versions": current_versions,
            "populations": {
                "prospective_tagged_plans": _plan_population_payload(tagged_plans),
                "replay_labeled_tagged_plans": _plan_population_payload(
                    replay_labeled_tagged_plans
                ),
                "all_replay_eligibility_rows": _replay_population_payload(replay_rows),
                "current_version_replay_eligibility_rows": _replay_population_payload(
                    current_replay_rows
                ),
                "phantom_selectivity_replay_eligible_rows": _replay_population_payload(
                    phantom_rows
                ),
                "current_version_phantom_selectivity_replay_eligible_rows": (
                    _replay_population_payload(current_phantom_rows)
                ),
            },
            "tagged_plan_evidence_mix": _tagged_plan_evidence_mix(
                tagged_plans,
                evidence_by_plan_id,
            ),
            "artifact_version_mix": _artifact_version_mix(replay_rows, current_versions),
        }
        report["freshness_alignment"] = _freshness_alignment(report["populations"])
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report
    finally:
        session.close()


def _tagged_plan_rows(session, *, limit: int | None):
    query = (
        select(RecommendationPlanRecord)
        .where(
            RecommendationPlanRecord.signal_breakdown_json.like(
                "%upstream_signal_quality_drivers%"
            )
        )
        .order_by(RecommendationPlanRecord.computed_at.asc(), RecommendationPlanRecord.id.asc())
    )
    if limit is not None:
        query = query.limit(max(1, int(limit)))
    return list(session.scalars(query).all())


def _replay_rows(session, *, limit: int | None):
    query = (
        select(ReplayEligibilityRecord, RecommendationPlanRecord.computed_at)
        .join(
            RecommendationPlanRecord,
            RecommendationPlanRecord.id == ReplayEligibilityRecord.recommendation_plan_id,
        )
        .order_by(RecommendationPlanRecord.computed_at.asc(), ReplayEligibilityRecord.id.asc())
    )
    if limit is not None:
        query = query.limit(max(1, int(limit)))
    return [
        LineageReplayRow(replay=row[0], computed_at=row[1])
        for row in session.execute(query).all()
    ]


def _plan_population_payload(rows: list[RecommendationPlanRecord]) -> dict[str, object]:
    dates = [_as_date(row.computed_at) for row in rows if row.computed_at is not None]
    tickers = [str(row.ticker or "").upper() for row in rows]
    return {
        "count": len(rows),
        "distinct_date_count": len(set(dates)),
        "date_range": _date_range_payload(dates),
        "ticker_count": len({item for item in tickers if item}),
        "ticker_mix": _top_values(tickers),
    }


def _replay_population_payload(rows: list[LineageReplayRow]) -> dict[str, object]:
    dates = [_as_date(row.computed_at) for row in rows if row.computed_at is not None]
    tickers = [str(row.replay.ticker or "").upper() for row in rows]
    return {
        "count": len(rows),
        "distinct_date_count": len(set(dates)),
        "date_range": _date_range_payload(dates),
        "ticker_count": len({item for item in tickers if item}),
        "tier_mix": _counter_payload(str(row.replay.tier or "").strip().lower() for row in rows),
        "resolution_source_mix": _counter_payload(
            str(row.replay.resolution_source or "").strip().lower() for row in rows
        ),
        "outcome_mix": _counter_payload(
            str(row.replay.outcome or "").strip().lower() for row in rows
        ),
        "eligible_for_tuning_mix": _counter_payload(
            "eligible" if bool(row.replay.eligible_for_tuning) else "not_eligible"
            for row in rows
        ),
        "ticker_mix": _top_values(tickers),
    }


def _tagged_plan_evidence_mix(
    tagged_plans: list[RecommendationPlanRecord],
    evidence_by_plan_id: dict[int, object],
) -> dict[str, object]:
    source_counter: Counter[str] = Counter()
    outcome_counter: Counter[str] = Counter()
    resolution_counter: Counter[str] = Counter()
    tier_counter: Counter[str] = Counter()
    for row in tagged_plans:
        evidence = evidence_by_plan_id.get(int(row.id))
        if evidence is None:
            source_counter["unlabeled"] += 1
            outcome_counter["unknown"] += 1
            resolution_counter["unknown"] += 1
            tier_counter["unknown"] += 1
            continue
        source_counter[str(evidence.evidence_source or "unknown")] += 1
        outcome_counter[str(evidence.outcome or "unknown")] += 1
        resolution_counter[str(evidence.resolution_source or "unknown")] += 1
        tier_counter[str(evidence.tier or "unknown")] += 1
    return {
        "evidence_source_mix": dict(sorted(source_counter.items())),
        "outcome_mix": dict(sorted(outcome_counter.items())),
        "resolution_source_mix": dict(sorted(resolution_counter.items())),
        "tier_mix": dict(sorted(tier_counter.items())),
    }


def _artifact_version_mix(
    rows: list[LineageReplayRow],
    current_versions: dict[str, str],
) -> dict[str, object]:
    counter: Counter[str] = Counter()
    for row in rows:
        diagnostics = loads_json_object(row.replay.diagnostics_json)
        if PlanGenerationTuningService._replay_artifact_versions_current(  # noqa: SLF001
            diagnostics,
            current_versions,
        ):
            counter["current"] += 1
        else:
            counter["stale_or_missing"] += 1
    return dict(sorted(counter.items()))


def _freshness_alignment(populations: dict[str, object]) -> dict[str, object]:
    tagged = populations["prospective_tagged_plans"]
    labeled = populations["replay_labeled_tagged_plans"]
    phantom = populations["current_version_phantom_selectivity_replay_eligible_rows"]
    raw_phantom = populations["phantom_selectivity_replay_eligible_rows"]
    assert isinstance(tagged, dict)
    assert isinstance(labeled, dict)
    assert isinstance(phantom, dict)
    assert isinstance(raw_phantom, dict)
    tagged_latest = _parse_date((tagged["date_range"] or {}).get("end"))
    labeled_latest = _parse_date((labeled["date_range"] or {}).get("end"))
    phantom_latest = _parse_date((phantom["date_range"] or {}).get("end"))
    raw_phantom_latest = _parse_date((raw_phantom["date_range"] or {}).get("end"))
    lag_days = (
        (tagged_latest - phantom_latest).days
        if tagged_latest is not None and phantom_latest is not None
        else None
    )
    if int(tagged["count"]) == 0:
        verdict = "no_tagged_evidence"
    elif int(phantom["count"]) == 0:
        verdict = "no_phantom_selectivity_evidence"
    elif raw_phantom_latest and phantom_latest and raw_phantom_latest > phantom_latest:
        verdict = "replay_stale_or_filtered"
    elif tagged_latest and phantom_latest and tagged_latest > phantom_latest:
        verdict = "tagged_ahead_of_replay"
    else:
        verdict = "aligned"
    return {
        "verdict": verdict,
        "latest_prospective_tag_date": tagged_latest.isoformat() if tagged_latest else None,
        "latest_replay_labeled_tag_date": labeled_latest.isoformat() if labeled_latest else None,
        "latest_phantom_selectivity_eligible_date": (
            phantom_latest.isoformat() if phantom_latest else None
        ),
        "latest_raw_phantom_selectivity_eligible_date": (
            raw_phantom_latest.isoformat() if raw_phantom_latest else None
        ),
        "tagged_minus_phantom_latest_lag_days": lag_days,
    }


def _as_date(value: datetime) -> date:
    return value.date()


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    return date.fromisoformat(value)


def _date_range_payload(dates: list[date]) -> dict[str, str | None]:
    if not dates:
        return {"start": None, "end": None}
    ordered = sorted(dates)
    return {"start": ordered[0].isoformat(), "end": ordered[-1].isoformat()}


def _counter_payload(values) -> dict[str, int]:
    counter = Counter(str(item or "unknown").strip().lower() or "unknown" for item in values)
    return dict(sorted(counter.items()))


def _top_values(values: list[str], *, limit: int = 10) -> list[dict[str, object]]:
    counter = Counter(str(item or "unknown").strip().upper() or "UNKNOWN" for item in values)
    total = max(1, sum(counter.values()))
    payloads = [
        {
            "value": value,
            "count": count,
            "share_percent": round((count / total) * 100.0, 4),
        }
        for value, count in counter.items()
    ]
    payloads.sort(key=lambda item: (int(item["count"]), str(item["value"])), reverse=True)
    return payloads[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit evidence lineage between prospective tags and replay eligibility."
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/evidence-lineage.json"),
    )
    parser.add_argument("--replay-tier", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    report = run_audit(
        artifact_path=args.artifact,
        tiers={str(item).strip() for item in args.replay_tier if str(item).strip()} or {"tier_a"},
        limit=args.limit,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "freshness_alignment": report["freshness_alignment"],
                "populations": {
                    key: {
                        "count": value["count"],
                        "distinct_date_count": value["distinct_date_count"],
                        "date_range": value["date_range"],
                    }
                    for key, value in report["populations"].items()
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
