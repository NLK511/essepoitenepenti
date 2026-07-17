#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
    PhantomSelectivitySeparabilityGates,
    build_phantom_selectivity_separability_report,
)
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)


def run_audit(
    *,
    artifact_path: Path,
    tiers: set[str],
    limit: int | None = None,
    min_total_rows: int = 500,
    min_selection_dates: int = 10,
    min_discovery_group_rows: int = 100,
    min_selection_group_rows: int = 30,
    min_selection_group_dates: int = 5,
    min_discovery_win_rate_lift_pct: float = 0.0,
    min_selection_win_rate_lift_pct: float = 5.0,
) -> dict[str, object]:
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
        observations: list[PhantomSelectivityObservation] = []
        for record in records:
            computed_at = record.plan.computed_at
            if computed_at is None:
                continue
            risk_reward = service._candidate_risk_reward(record, active_config)  # noqa: SLF001
            if risk_reward is None:
                continue
            reward_pct, risk_pct = risk_reward
            signal_breakdown = service._plan_signal_breakdown(record.plan)  # noqa: SLF001
            intended_action = str(signal_breakdown.get("intended_action") or "").strip().lower() or None
            effective_action = (
                intended_action
                if record.plan.action in {"no_action", "watchlist"}
                and intended_action in {"long", "short"}
                else record.plan.action
            )
            volatility_score = signal_breakdown.get("cheap_scan_volatility_score")
            observations.append(
                PhantomSelectivityObservation(
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
                )
            )

        gates = PhantomSelectivitySeparabilityGates(
            min_total_rows=min_total_rows,
            min_selection_dates=min_selection_dates,
            min_discovery_group_rows=min_discovery_group_rows,
            min_selection_group_rows=min_selection_group_rows,
            min_selection_group_dates=min_selection_group_dates,
            min_discovery_win_rate_lift_pct=min_discovery_win_rate_lift_pct,
            min_selection_win_rate_lift_pct=min_selection_win_rate_lift_pct,
        )
        report = build_phantom_selectivity_separability_report(
            observations,
            gates=gates,
            generated_at=datetime.now(timezone.utc),
        )
        report["input"] = {
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit whether phantom wins are separable from phantom losses."
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/phantom-selectivity-separability.json"),
    )
    parser.add_argument("--replay-tier", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-total-rows", type=int, default=500)
    parser.add_argument("--min-selection-dates", type=int, default=10)
    parser.add_argument("--min-discovery-group-rows", type=int, default=100)
    parser.add_argument("--min-selection-group-rows", type=int, default=30)
    parser.add_argument("--min-selection-group-dates", type=int, default=5)
    parser.add_argument("--min-discovery-win-rate-lift-pct", type=float, default=0.0)
    parser.add_argument("--min-selection-win-rate-lift-pct", type=float, default=5.0)
    args = parser.parse_args()

    report = run_audit(
        artifact_path=args.artifact,
        tiers={str(item).strip() for item in args.replay_tier if str(item).strip()} or {"tier_a"},
        limit=args.limit,
        min_total_rows=args.min_total_rows,
        min_selection_dates=args.min_selection_dates,
        min_discovery_group_rows=args.min_discovery_group_rows,
        min_selection_group_rows=args.min_selection_group_rows,
        min_selection_group_dates=args.min_selection_group_dates,
        min_discovery_win_rate_lift_pct=args.min_discovery_win_rate_lift_pct,
        min_selection_win_rate_lift_pct=args.min_selection_win_rate_lift_pct,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "verdict": report["verdict"],
                "candidate_specific_replay_recommended": report[
                    "candidate_specific_replay_recommended"
                ],
                "record_counts": report["record_counts"],
                "date_counts": report["date_counts"],
                "candidate_group_count": len(report["candidate_groups"]),
                "blockers": report["blockers"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
