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
from trade_proposer_app.services.upstream_driver_quality import (
    build_upstream_driver_quality_report,
    markdown_summary,
)
from trade_proposer_app.services.upstream_signal_driver_audit import (
    UpstreamSignalDriverObservation,
)
from trade_proposer_app.utils.json_payloads import loads_json_object


def run_audit(
    *,
    separability_artifact_path: Path,
    upstream_audit_artifact_path: Path,
    drilldown_artifact_path: Path,
    candidate_replay_artifact_path: Path | None,
    artifact_dir: Path,
    tiers: set[str],
    limit: int | None = None,
    driver_specs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    separability = json.loads(separability_artifact_path.read_text(encoding="utf-8"))
    upstream_audit = json.loads(upstream_audit_artifact_path.read_text(encoding="utf-8"))
    drilldown = json.loads(drilldown_artifact_path.read_text(encoding="utf-8"))
    candidate_replay = (
        json.loads(candidate_replay_artifact_path.read_text(encoding="utf-8"))
        if candidate_replay_artifact_path is not None and candidate_replay_artifact_path.exists()
        else None
    )
    candidate_groups = list(separability.get("candidate_groups") or [])
    drivers = (
        driver_specs
        or _drivers_from_drilldown(drilldown)
        or _drivers_from_audit(upstream_audit)
    )
    observations = _load_observations(tiers=tiers, limit=limit)
    report = build_upstream_driver_quality_report(
        observations,
        candidate_groups,
        drivers,
        source_artifacts={
            "separability": str(separability_artifact_path),
            "upstream_audit": str(upstream_audit_artifact_path),
            "drilldown": str(drilldown_artifact_path),
            "candidate_replay": str(candidate_replay_artifact_path)
            if candidate_replay_artifact_path
            else "",
        },
    )
    report["input"]["source_verdicts"] = {
        "separability": separability.get("verdict"),
        "upstream_audit": upstream_audit.get("verdict"),
        "drilldown": drilldown.get("verdict"),
        "candidate_replay": candidate_replay.get("verdict") if candidate_replay else None,
    }
    report["input"]["tiers"] = sorted(tiers)
    report["input"]["limit"] = limit
    report["input"]["loaded_observation_count"] = len(observations)
    _write_artifacts(report, artifact_dir=artifact_dir)
    return report


def _load_observations(
    *,
    tiers: set[str],
    limit: int | None,
) -> list[UpstreamSignalDriverObservation]:
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
            intended_action = str(signal_breakdown.get("intended_action") or "").strip().lower()
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
                        intended_action=intended_action or None,
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
        return observations
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
    return {int(row.id): loads_json_object(row.signal_breakdown_json) for row in rows}


def _write_artifacts(report: dict[str, object], *, artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_json(artifact_dir / "driver-quality-scorecard.json", report)
    _write_json(
        artifact_dir / "preflight.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "source_artifacts": report["input"].get("source_artifacts", {}),
            "source_verdicts": report["input"].get("source_verdicts", {}),
            "tiers": report["input"].get("tiers", []),
            "limit": report["input"].get("limit"),
            "loaded_observation_count": report["input"].get("loaded_observation_count"),
            "read_only_scope": {
                "changed_tuning_config": False,
                "changed_broker_settings": False,
                "changed_orders": False,
                "changed_scheduler_state": False,
            },
        },
    )
    (artifact_dir / "driver-quality-scorecard.md").write_text(
        markdown_summary(report),
        encoding="utf-8",
    )
    _write_json(
        artifact_dir / "driver-inventory.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "candidate_groups": report["candidate_groups"],
            "drivers": [
                {
                    "feature": item["feature"],
                    "value": item["value"],
                    "scorecard_status": item["scorecard_status"],
                    "metrics": item["metrics"],
                    "mix": item["mix"],
                }
                for item in report["drivers"]
            ],
        },
    )
    _write_json(
        artifact_dir / "driver-stability.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "drivers": [
                {
                    "feature": item["feature"],
                    "value": item["value"],
                    "discovery_metrics": item["discovery_metrics"],
                    "selection_metrics": item["selection_metrics"],
                    "weekly_stability": item["weekly_stability"],
                }
                for item in report["drivers"]
            ],
        },
    )
    _write_json(
        artifact_dir / "driver-neighbor-shape.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "drivers": [
                {
                    "feature": item["feature"],
                    "value": item["value"],
                    "neighbor_shape": item["neighbor_shape"],
                }
                for item in report["drivers"]
            ],
        },
    )
    _write_json(
        artifact_dir / "driver-lineage-audit.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "drivers": [
                {
                    "feature": item["feature"],
                    "value": item["value"],
                    "lineage_quality": item["lineage_quality"],
                }
                for item in report["drivers"]
            ],
        },
    )
    _write_json(
        artifact_dir / "driver-ablation.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "drivers": [
                {
                    "feature": item["feature"],
                    "value": item["value"],
                    "ablations": item["ablations"],
                }
                for item in report["drivers"]
            ],
        },
    )
    _write_markdown_report(artifact_dir / "driver-contracts.md", report, "contract")
    _write_markdown_report(artifact_dir / "driver-stability-summary.md", report, "stability")
    _write_markdown_report(artifact_dir / "driver-neighbor-shape-summary.md", report, "shape")
    _write_markdown_report(artifact_dir / "driver-ablation-summary.md", report, "ablation")
    _write_markdown_report(artifact_dir / "driver-lineage-examples.md", report, "lineage")


def _write_markdown_report(path: Path, report: dict[str, object], section: str) -> None:
    lines = [f"# Driver {section}", ""]
    for item in report["drivers"]:
        lines.append(f"## {item['feature']}={item['value']}")
        if section == "contract":
            lines.append(_contract_text(str(item["feature"]), str(item["value"])))
        elif section == "stability":
            lines.append(f"Discovery: `{item['discovery_metrics']}`")
            lines.append(f"Selection: `{item['selection_metrics']}`")
        elif section == "shape":
            lines.append(f"`{item['neighbor_shape']}`")
        elif section == "ablation":
            lines.append(f"`{item['ablations']}`")
        elif section == "lineage":
            lines.append(f"`{item['lineage_quality']}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _contract_text(feature: str, value: str) -> str:
    if feature == "volatility_bucket":
        return f"`{value}` should represent a reusable volatility regime, not ticker identity."
    if feature == "confidence_component_bucket":
        return f"`{value}` should represent a reusable confidence-component signal."
    if feature == "catalyst_intensity_bucket":
        return f"`{value}` should represent reusable catalyst strength."
    if feature == "shortlist_rank_bucket":
        return f"`{value}` should represent shortlist positioning quality."
    return f"`{value}` should represent reusable upstream signal quality."


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _drivers_from_drilldown(
    report: dict[str, object],
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    drivers: list[dict[str, object]] = []
    for item in list(report.get("drivers") or []):
        if not isinstance(item, dict):
            continue
        feature = str(item.get("feature") or "").strip()
        value = str(item.get("value") or "").strip()
        if feature and value:
            drivers.append({"feature": feature, "value": value})
        if len(drivers) >= limit:
            break
    return drivers


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
        description="Score upstream driver quality without changing tuning or broker behavior."
    )
    parser.add_argument("--separability-artifact", type=Path, required=True)
    parser.add_argument("--upstream-audit-artifact", type=Path, required=True)
    parser.add_argument("--drilldown-artifact", type=Path, required=True)
    parser.add_argument("--candidate-replay-artifact", type=Path)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--driver", action="append", type=_parse_driver, default=[])
    parser.add_argument("--replay-tier", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    report = run_audit(
        separability_artifact_path=args.separability_artifact,
        upstream_audit_artifact_path=args.upstream_audit_artifact,
        drilldown_artifact_path=args.drilldown_artifact,
        candidate_replay_artifact_path=args.candidate_replay_artifact,
        artifact_dir=args.artifact_dir,
        tiers={str(item).strip() for item in args.replay_tier if str(item).strip()} or {"tier_a"},
        limit=args.limit,
        driver_specs=args.driver or None,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact_dir / "driver-quality-scorecard.json"),
                "verdict": report["verdict"],
                "blockers": report["blockers"],
                "scorecard_counts": report["scorecard_counts"],
                "drivers": [
                    {
                        "feature": item["feature"],
                        "value": item["value"],
                        "scorecard_status": item["scorecard_status"],
                        "blockers": item["blockers"],
                    }
                    for item in report["drivers"]
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
