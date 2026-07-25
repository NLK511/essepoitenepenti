#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.services.plan_outcome_evidence import (
    PlanOutcomeEvidence,
    PlanOutcomeEvidenceService,
)
from trade_proposer_app.services.upstream_signal_driver_audit import (
    ProspectiveSignalDriverTagMonitorGates,
    ProspectiveSignalDriverTagObservation,
    build_prospective_signal_driver_tag_monitor_report,
)
from trade_proposer_app.utils.json_payloads import loads_json_object


def run_monitor(
    *,
    artifact_path: Path,
    limit: int | None = None,
    since_days: int | None = None,
    min_tagged_rows: int = 30,
    min_tagged_dates: int = 5,
    min_replay_labeled_rows: int = 30,
    min_replay_labeled_dates: int = 5,
    promotion_watch_date_floor: int = 20,
) -> dict[str, object]:
    session = SessionLocal()
    try:
        plans = _tagged_plan_rows(session, limit=limit, since_days=since_days)
        evidence_by_plan_id = PlanOutcomeEvidenceService(session).best_by_plan_id(
            [int(row.id) for row in plans]
        )
        observations = [
            _observation_from_plan(row, evidence_by_plan_id.get(int(row.id)))
            for row in plans
        ]
        gates = ProspectiveSignalDriverTagMonitorGates(
            min_tagged_rows=min_tagged_rows,
            min_tagged_dates=min_tagged_dates,
            min_replay_labeled_rows=min_replay_labeled_rows,
            min_replay_labeled_dates=min_replay_labeled_dates,
            promotion_watch_date_floor=promotion_watch_date_floor,
        )
        report = build_prospective_signal_driver_tag_monitor_report(
            observations,
            gates=gates,
        )
        report["input"] = {
            "limit": limit,
            "since_days": since_days,
            "loaded_tagged_plan_count": len(plans),
        }
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report
    finally:
        session.close()


def _tagged_plan_rows(session, *, limit: int | None, since_days: int | None):
    query = (
        select(RecommendationPlanRecord)
        .where(
            RecommendationPlanRecord.signal_breakdown_json.like(
                "%upstream_signal_quality_drivers%"
            )
        )
        .order_by(RecommendationPlanRecord.computed_at.asc(), RecommendationPlanRecord.id.asc())
    )
    if since_days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, int(since_days)))
        query = query.where(RecommendationPlanRecord.computed_at >= since)
    if limit is not None:
        query = query.limit(max(1, int(limit)))
    return list(session.scalars(query).all())


def _observation_from_plan(
    plan: RecommendationPlanRecord,
    evidence: PlanOutcomeEvidence | None,
) -> ProspectiveSignalDriverTagObservation:
    signal = loads_json_object(plan.signal_breakdown_json)
    setup_family = str(signal.get("setup_family") or "unknown").strip().lower()
    intended_action = str(signal.get("intended_action") or "").strip().lower()
    effective_action = intended_action if plan.action in {"no_action", "watchlist"} else plan.action
    reward_pct, risk_pct = _plan_geometry_percent(
        action=str(effective_action or plan.action or "").strip().lower(),
        entry_price_low=plan.entry_price_low,
        entry_price_high=plan.entry_price_high,
        stop_loss=plan.stop_loss,
        take_profit=plan.take_profit,
    )
    computed_at = plan.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return ProspectiveSignalDriverTagObservation(
        plan_id=int(plan.id),
        evidence_date=computed_at.date(),
        ticker=str(plan.ticker or "").upper(),
        action=str(plan.action or "").strip().lower(),
        setup_family=setup_family,
        signal_breakdown=signal,
        replay_outcome=evidence.outcome if evidence else None,
        replay_resolution_source=evidence.resolution_source if evidence else None,
        label_source=evidence.evidence_source if evidence else None,
        reward_pct=reward_pct,
        risk_pct=risk_pct,
    )


def _plan_geometry_percent(
    *,
    action: str,
    entry_price_low: float | None,
    entry_price_high: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> tuple[float | None, float | None]:
    if (
        entry_price_low is None
        or entry_price_high is None
        or stop_loss is None
        or take_profit is None
    ):
        return None, None
    entry = (float(entry_price_low) + float(entry_price_high)) / 2.0
    if entry <= 0:
        return None, None
    if action == "short":
        reward_pct = ((entry - float(take_profit)) / entry) * 100.0
        risk_pct = ((float(stop_loss) - entry) / entry) * 100.0
    else:
        reward_pct = ((float(take_profit) - entry) / entry) * 100.0
        risk_pct = ((entry - float(stop_loss)) / entry) * 100.0
    return round(reward_pct, 6), round(risk_pct, 6)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor prospective upstream signal-quality driver tags on stored plans."
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/upstream-signal-driver-tag-monitor.json"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--min-tagged-rows", type=int, default=30)
    parser.add_argument("--min-tagged-dates", type=int, default=5)
    parser.add_argument("--min-replay-labeled-rows", type=int, default=30)
    parser.add_argument("--min-replay-labeled-dates", type=int, default=5)
    parser.add_argument("--promotion-watch-date-floor", type=int, default=20)
    args = parser.parse_args()

    report = run_monitor(
        artifact_path=args.artifact,
        limit=args.limit,
        since_days=args.since_days,
        min_tagged_rows=args.min_tagged_rows,
        min_tagged_dates=args.min_tagged_dates,
        min_replay_labeled_rows=args.min_replay_labeled_rows,
        min_replay_labeled_dates=args.min_replay_labeled_dates,
        promotion_watch_date_floor=args.promotion_watch_date_floor,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "verdict": report["verdict"],
                "blockers": report["blockers"],
                "record_counts": report["record_counts"],
                "top_tags": [
                    {
                        "key": item["key"],
                        "tag_verdict": item["tag_verdict"],
                        "metrics": item["metrics"],
                        "replay_labeled_metrics": item["replay_labeled_metrics"],
                        "blockers": item["blockers"],
                    }
                    for item in report["tags"][:8]
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
