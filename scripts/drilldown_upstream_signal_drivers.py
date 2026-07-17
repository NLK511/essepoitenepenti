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
    UpstreamSignalDriverDrilldownGates,
    UpstreamSignalDriverObservation,
    build_upstream_signal_driver_drilldown_report,
)
from trade_proposer_app.utils.json_payloads import loads_json_object


def run_drilldown(
    *,
    separability_artifact_path: Path,
    upstream_audit_artifact_path: Path,
    artifact_path: Path,
    tiers: set[str],
    limit: int | None = None,
    driver_specs: list[dict[str, object]] | None = None,
    examples_per_outcome: int = 3,
) -> dict[str, object]:
    separability = json.loads(separability_artifact_path.read_text(encoding="utf-8"))
    upstream_audit = json.loads(upstream_audit_artifact_path.read_text(encoding="utf-8"))
    candidate_groups = list(separability.get("candidate_groups") or [])
    drivers = driver_specs or _drivers_from_audit(upstream_audit)
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
                    plan_id=int(record.plan.id),
                )
            )
        report = build_upstream_signal_driver_drilldown_report(
            observations,
            candidate_groups,
            drivers,
            gates=UpstreamSignalDriverDrilldownGates(),
            examples_per_outcome=examples_per_outcome,
        )
        report["input"] = {
            "separability_artifact": str(separability_artifact_path),
            "upstream_audit_artifact": str(upstream_audit_artifact_path),
            "upstream_audit_verdict": upstream_audit.get("verdict"),
            "replay_evidence_profile": "phantom_selectivity",
            "tiers": sorted(tiers),
            "limit": limit,
            "loaded_record_count": len(records),
            "usable_observation_count": len(observations),
            "drivers": drivers,
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


def _drivers_from_audit(report: dict[str, object], *, limit: int = 8) -> list[dict[str, object]]:
    drivers: list[dict[str, object]] = []
    for item in list(report.get("top_reusable_candidate_win_loss_drivers") or []):
        if not isinstance(item, dict) or not item.get("passes_feature_gates"):
            continue
        feature = str(item.get("feature") or "").strip()
        value = str(item.get("value") or "").strip()
        if feature and value:
            drivers.append({"feature": feature, "value": value})
        if len(drivers) >= limit:
            break
    return drivers


def _parse_driver(text: str) -> dict[str, object]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("driver must use feature=value")
    feature, value = text.split("=", 1)
    feature = feature.strip()
    value = value.strip()
    if not feature or not value:
        raise argparse.ArgumentTypeError("driver must use non-empty feature=value")
    return {"feature": feature, "value": value}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Drill into upstream signal drivers with compact example rows."
    )
    parser.add_argument("--separability-artifact", type=Path, required=True)
    parser.add_argument("--upstream-audit-artifact", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/upstream-signal-driver-drilldown.json"),
    )
    parser.add_argument("--driver", action="append", type=_parse_driver, default=[])
    parser.add_argument("--replay-tier", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--examples-per-outcome", type=int, default=3)
    args = parser.parse_args()

    report = run_drilldown(
        separability_artifact_path=args.separability_artifact,
        upstream_audit_artifact_path=args.upstream_audit_artifact,
        artifact_path=args.artifact,
        tiers={str(item).strip() for item in args.replay_tier if str(item).strip()} or {"tier_a"},
        limit=args.limit,
        driver_specs=args.driver or None,
        examples_per_outcome=max(1, int(args.examples_per_outcome)),
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "verdict": report["verdict"],
                "blockers": report["blockers"],
                "driver_count": report["driver_count"],
                "record_counts": report["record_counts"],
                "drivers": [
                    {
                        "feature": item["feature"],
                        "value": item["value"],
                        "driver_verdict": item["driver_verdict"],
                        "metrics": item["metrics"],
                        "top_ticker": (item["mix"]["tickers"] or [{}])[0],
                    }
                    for item in report["drivers"][:8]
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
