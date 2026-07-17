#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityCandidateReplayGates,
    PhantomSelectivityObservation,
    build_phantom_selectivity_candidate_replay_report,
)
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)


def run_candidate_replay(
    *,
    separability_artifact_path: Path,
    artifact_path: Path,
    tiers: set[str],
    limit: int | None = None,
    min_selection_rows: int = 100,
    min_selection_dates: int = 20,
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
        gates = PhantomSelectivityCandidateReplayGates(
            min_selection_rows=min_selection_rows,
            min_selection_dates=min_selection_dates,
        )
        report = build_phantom_selectivity_candidate_replay_report(
            observations,
            candidate_groups,
            min_selection_dates=int((separability.get("gates") or {}).get("min_selection_dates") or 10),
            selection_date_fraction=float(
                (separability.get("gates") or {}).get("selection_date_fraction") or 0.25
            ),
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay concrete phantom-selectivity candidate groups as emitted candidate trades."
    )
    parser.add_argument("--separability-artifact", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/phantom-selectivity-candidate-replay.json"),
    )
    parser.add_argument("--replay-tier", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-selection-rows", type=int, default=100)
    parser.add_argument("--min-selection-dates", type=int, default=20)
    args = parser.parse_args()

    report = run_candidate_replay(
        separability_artifact_path=args.separability_artifact,
        artifact_path=args.artifact,
        tiers={str(item).strip() for item in args.replay_tier if str(item).strip()} or {"tier_a"},
        limit=args.limit,
        min_selection_rows=args.min_selection_rows,
        min_selection_dates=args.min_selection_dates,
    )
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "verdict": report["verdict"],
                "promotion_candidate_ready": report["promotion_candidate_ready"],
                "candidate_group_count": report["candidate_group_count"],
                "combined_union": report["combined_union"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

