#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
)
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)
from trade_proposer_app.services.upstream_signal_driver_audit import (
    UpstreamSignalDriverAuditGates,
    UpstreamSignalDriverObservation,
    build_upstream_signal_driver_audit_report,
)
from trade_proposer_app.utils.json_payloads import loads_json_object


def run_audit(
    *,
    separability_artifact_path: Path,
    artifact_path: Path,
    tiers: set[str],
    limit: int | None = None,
    min_candidate_rows: int = 100,
    min_candidate_dates: int = 10,
    min_feature_rows: int = 30,
    min_feature_dates: int = 5,
) -> dict[str, object]:
    separability = json.loads(separability_artifact_path.read_text(encoding="utf-8"))
    candidate_groups = list(separability.get("candidate_groups") or [])
    session = SessionLocal()
    try:
        service = PlanGenerationTuningService(session)
        active_config = normalize_plan_generation_tuning_config(
            service._resolve_active_config_version().config  # noqa: SLF001
        )
        records = service._replay_eligible_records(  # noqa: SLF001
            ticker=None,
            setup_family=None,
            limit=limit,
            tiers=tiers,
            evidence_profile="phantom_selectivity",
        )
        plan_ids = sorted({int(getattr(record.plan, "id", 0) or 0) for record in records})
        raw_signal_by_plan_id = _raw_signal_breakdowns_by_plan_id(session, plan_ids)
        observations: list[UpstreamSignalDriverObservation] = []
        for record in records:
            computed_at = record.plan.computed_at
            if computed_at is None:
                continue
            risk_reward = service._candidate_risk_reward(record, active_config)  # noqa: SLF001
            if risk_reward is None:
                continue
            reward_pct, risk_pct = risk_reward
            signal_breakdown = raw_signal_by_plan_id.get(int(record.plan.id), {})
            intended_action = str(signal_breakdown.get("intended_action") or "").strip().lower() or None
            effective_action = (
                intended_action
                if record.plan.action in {"no_action", "watchlist"}
                and intended_action in {"long", "short"}
                else record.plan.action
            )
            volatility_score = signal_breakdown.get("cheap_scan_volatility_score")
            observations.append(
                UpstreamSignalDriverObservation(
                    base=PhantomSelectivityObservation(
                        evidence_date=computed_at.date(),
                        outcome=str(record.replay_outcome or "").strip().lower(),
                        ticker=str(getattr(record.plan, "ticker", "") or "").upper(),
                        setup_family=str(record.setup_family or "uncategorized").strip().lower(),
                        context_bias=record.context_bias,
                        action=str(record.plan.action or "").strip().lower(),
                        intended_action=intended_action,
                        effective_action=str(effective_action or "").strip().lower() or None,
                        confidence_percent=float(record.plan.confidence_percent or 0.0),
                        volatility_score=float(volatility_score)
                        if isinstance(volatility_score, (int, float))
                        else None,
                        reward_pct=float(reward_pct),
                        risk_pct=float(risk_pct),
                    ),
                    signal_breakdown=signal_breakdown,
                )
            )
        gates = UpstreamSignalDriverAuditGates(
            min_candidate_rows=min_candidate_rows,
            min_candidate_dates=min_candidate_dates,
            min_feature_rows=min_feature_rows,
            min_feature_dates=min_feature_dates,
        )
        report = build_upstream_signal_driver_audit_report(
            observations,
            candidate_groups,
            gates=gates,
        )
        report["input"] = {
            "separability_artifact": str(separability_artifact_path),
            "separability_verdict": separability.get("verdict"),
            "replay_evidence_profile": "phantom_selectivity",
            "tiers": sorted(tiers),
            "limit": limit,
            "loaded_record_count": len(records),
            "usable_observation_count": len(observations),
        }
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report
    finally:
        session.close()


def _raw_signal_breakdowns_by_plan_id(session, plan_ids: list[int]) -> dict[int, dict[str, object]]:
    if not plan_ids:
        return {}
    rows = session.execute(
        select(
            RecommendationPlanRecord.id,
            RecommendationPlanRecord.signal_breakdown_json,
        ).where(RecommendationPlanRecord.id.in_(plan_ids))
    ).all()
    return {
        int(row.id): loads_json_object(row.signal_breakdown_json)
        for row in rows
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit upstream signal drivers behind phantom selectivity candidate groups."
    )
    parser.add_argument("--separability-artifact", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/upstream-signal-driver-audit.json"),
    )
    parser.add_argument("--replay-tier", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-candidate-rows", type=int, default=100)
    parser.add_argument("--min-candidate-dates", type=int, default=10)
    parser.add_argument("--min-feature-rows", type=int, default=30)
    parser.add_argument("--min-feature-dates", type=int, default=5)
    args = parser.parse_args()

    report = run_audit(
        separability_artifact_path=args.separability_artifact,
        artifact_path=args.artifact,
        tiers={str(item).strip() for item in args.replay_tier if str(item).strip()} or {"tier_a"},
        limit=args.limit,
        min_candidate_rows=args.min_candidate_rows,
        min_candidate_dates=args.min_candidate_dates,
        min_feature_rows=args.min_feature_rows,
        min_feature_dates=args.min_feature_dates,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "verdict": report["verdict"],
                "blockers": report["blockers"],
                "record_counts": report["record_counts"],
                "reusable_signal_feature_coverage_percent": report[
                    "reusable_signal_feature_coverage_percent"
                ],
                "top_reusable_candidate_win_loss_drivers": report[
                    "top_reusable_candidate_win_loss_drivers"
                ][:5],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
