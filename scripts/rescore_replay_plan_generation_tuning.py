#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.models import PlanGenerationTuningRun
from trade_proposer_app.persistence.models import RecommendationPlanRecord, ReplayEligibilityRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.services.outcome_population import summarize_outcome_population
from trade_proposer_app.services.plan_generation_tuning import (
    EligibleTuningRecord,
    PlanGenerationTuningService,
    TuningOutcomeSnapshot,
    TuningPlanSnapshot,
)
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    PARAMETER_BY_KEY,
    normalize_plan_generation_tuning_config,
)
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService
from trade_proposer_app.utils.json_payloads import loads_json_object


def _float_or_none(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _load_records(session, service: PlanGenerationTuningService, *, batch_id: int, tiers: set[str]) -> list[EligibleTuningRecord]:
    rows = session.execute(
        select(ReplayEligibilityRecord, RecommendationPlanRecord, ReplayPlanOutcomeRecord)
        .join(RecommendationPlanRecord, RecommendationPlanRecord.id == ReplayEligibilityRecord.recommendation_plan_id)
        .join(ReplayPlanOutcomeRecord, ReplayPlanOutcomeRecord.id == ReplayEligibilityRecord.replay_plan_outcome_id)
        .where(ReplayEligibilityRecord.replay_batch_id == batch_id)
        .where(ReplayEligibilityRecord.eligible_for_tuning.is_(True))
        .where(ReplayEligibilityRecord.tier.in_(sorted(tiers)))
        .where(ReplayEligibilityRecord.outcome.in_(["win", "loss", "phantom_win", "phantom_loss"]))
        .order_by(RecommendationPlanRecord.computed_at.asc(), ReplayEligibilityRecord.id.asc())
    ).all()
    records: list[EligibleTuningRecord] = []
    for eligibility, plan, outcome in rows:
        signal_breakdown = loads_json_object(plan.signal_breakdown_json)
        outcome_payload = loads_json_object(outcome.outcome_json)
        setup = service._setup_family_from_payloads(signal_breakdown, outcome_payload)  # noqa: SLF001
        records.append(
            EligibleTuningRecord(
                plan=TuningPlanSnapshot(
                    id=int(plan.id or 0),
                    computed_at=service._normalize_datetime(plan.computed_at),  # noqa: SLF001
                    action=plan.action,
                    confidence_percent=float(plan.confidence_percent),
                    entry_price_low=plan.entry_price_low,
                    entry_price_high=plan.entry_price_high,
                    stop_loss=plan.stop_loss,
                    take_profit=plan.take_profit,
                    signal_breakdown={key: signal_breakdown[key] for key in ("intended_action", "cheap_scan_volatility_score") if key in signal_breakdown},
                    ticker=plan.ticker,
                ),
                outcome=TuningOutcomeSnapshot(
                    max_favorable_excursion=_float_or_none(outcome_payload.get("max_favorable_excursion")),
                    max_adverse_excursion=_float_or_none(outcome_payload.get("max_adverse_excursion")),
                    horizon_return_5d=_float_or_none(outcome_payload.get("horizon_return_5d")),
                ),
                sample=None,
                setup_family=setup,
                context_bias=service._context_bias(signal_breakdown),  # noqa: SLF001
            )
        )
    return records


def _candidate_configs(service: PlanGenerationTuningService, active_config: dict[str, object], *, fixed_floor: float, candidate_count: int) -> list[dict[str, object]]:
    active = normalize_plan_generation_tuning_config(active_config)
    active["global.actionable_confidence_floor_percent"] = fixed_floor
    configs = [dict(active)]
    seen = {tuple(sorted(active.items()))}
    keys = [
        "global.entry_band_risk_fraction",
        "setup_family.entry_band_multiplier",
        "global.headwind_stop_multiplier",
        "global.volatility_stop_multiplier",
        "setup_family.breakout.stop_distance_multiplier",
        "setup_family.mean_reversion.stop_distance_multiplier",
        "setup_family.breakout.take_profit_distance_multiplier",
        "setup_family.mean_reversion.take_profit_distance_multiplier",
        "setup_family.catalyst_follow_through.take_profit_distance_multiplier",
        "setup_family.macro_beneficiary_loser.take_profit_distance_multiplier",
    ]
    for key in keys:
        definition = PARAMETER_BY_KEY[key]
        base = float(active.get(key, definition.default))
        for step in (-2, -1, 1, 2):
            candidate = dict(active)
            candidate[key] = service._campaign_bounded_value(definition, base + definition.step * step, explore_mode=True)  # noqa: SLF001
            candidate["global.actionable_confidence_floor_percent"] = fixed_floor
            normalized = normalize_plan_generation_tuning_config(candidate)
            fingerprint = tuple(sorted(normalized.items()))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            configs.append(normalized)
            if len(configs) >= candidate_count:
                return configs
    return configs


def main() -> None:
    parser = argparse.ArgumentParser(description="Rescore plan-generation tuning candidates from repaired replay eligibility rows.")
    parser.add_argument("--batch-id", type=int, required=True)
    parser.add_argument("--fixed-floor", type=float, default=48.0)
    parser.add_argument("--candidate-count", type=int, default=20)
    parser.add_argument("--tiers", default="tier_a,tier_b", help="Comma-separated replay eligibility tiers to include.")
    parser.add_argument("--artifact-dir", default="artifacts")
    args = parser.parse_args()
    tiers = {item.strip() for item in args.tiers.split(",") if item.strip()}
    session = SessionLocal()
    try:
        service = PlanGenerationTuningService(session)
        active = service._resolve_active_config_version()  # noqa: SLF001
        active_config = normalize_plan_generation_tuning_config(active.config)
        active_config["global.actionable_confidence_floor_percent"] = float(args.fixed_floor)
        records = _load_records(session, service, batch_id=args.batch_id, tiers=tiers)
        if not records:
            raise SystemExit("no eligible replay tuning records found")
        search_records, validation_records = service._split_records(records, min_validation=8)  # noqa: SLF001
        candidates = _candidate_configs(service, active_config, fixed_floor=float(args.fixed_floor), candidate_count=int(args.candidate_count))
        service._candidate_configs = MethodType(lambda self, active_config_arg, *, mode: candidates, service)  # noqa: SLF001
        seed = service._exploration_seed(active_config=active_config, records=records, mode="point_in_time_replay")  # noqa: SLF001
        evaluations, baseline, refinements, _, batch_count = service._evaluate_candidate_search(  # noqa: SLF001
            active_config=active_config,
            records=records,
            search_records=search_records,
            validation_records=validation_records,
            walk_forward_service=PlanGenerationWalkForwardService(service),
            mode="point_in_time_replay",
            explore_mode=True,
            batch_size=10,
            max_candidates=int(args.candidate_count),
            min_validation_resolved=8,
            exploration_seed=seed,
        )
        population = summarize_outcome_population(
            session.scalars(
                select(ReplayEligibilityRecord)
                .where(ReplayEligibilityRecord.replay_batch_id == args.batch_id)
                .where(ReplayEligibilityRecord.eligible_for_tuning.is_(True))
                .where(ReplayEligibilityRecord.tier.in_(sorted(tiers)))
            ).all(),
            population="replay_tier_a_b" if tiers == {"tier_a", "tier_b"} else "replay_tier_a_only" if tiers == {"tier_a"} else "custom_replay_tiers",
            outcome_attr="outcome",
            tier_attr="tier",
        )
        summary = {
            "winner": service._candidate_payload(evaluations[0]),  # noqa: SLF001
            "baseline": service._candidate_payload(baseline),  # noqa: SLF001
            "promotion_requested": False,
            "tuning_source_mode": "repaired_replay_eligibility_rescore",
            "replay_batch_id": int(args.batch_id),
            "fixed_actionability_floor_percent": float(args.fixed_floor),
            "requested_candidate_count": int(args.candidate_count),
            "search_record_count": len(search_records),
            "validation_record_count": len(validation_records),
            "refinement_candidate_count": len(refinements),
            "evaluation_batch_count": batch_count,
            "outcome_population": population,
        }
        run = service.repository.create_run(
            PlanGenerationTuningRun(
                status="completed",
                mode="fixed_floor_replay_rescore",
                objective_name=service.OBJECTIVE_NAME,
                promotion_mode="dry_run",
                baseline_config_version_id=active.id,
                eligible_record_count=len(records),
                eligible_tier_a_count=int(population.get("tier_counts", {}).get("tier_a", 0)),
                validation_record_count=len(validation_records),
                candidate_count=len(evaluations),
                summary=summary,
                filters={"replay_batch_id": int(args.batch_id), "fixed_floor": float(args.fixed_floor), "tiers": sorted(tiers)},
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        stored = service._store_candidate_evaluations(run_id=run.id or 0, evaluations=evaluations, baseline_eval=baseline, min_validation_resolved=8)  # noqa: SLF001
        run.winning_candidate_id = stored[0].id if stored else None
        run.candidates = stored
        run.summary["winning_candidate_id"] = run.winning_candidate_id
        service.repository.update_run(run.id or 0, run)
        artifact = {
            "run_id": run.id,
            "replay_batch_id": int(args.batch_id),
            "outcome_population": population,
            "top_candidates": [service._candidate_payload(item) for item in evaluations[:10]],  # noqa: SLF001
        }
        artifact_dir = Path(args.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / f"replay-plan-generation-rescore-batch-{args.batch_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
        path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str))
        session.commit()
        print(json.dumps({"status": "completed", "run_id": run.id, "artifact_path": str(path), "winner_candidate_id": run.winning_candidate_id, "outcome_population": population}, indent=2, sort_keys=True))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
