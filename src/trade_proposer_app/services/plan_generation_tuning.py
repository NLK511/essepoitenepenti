from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cmp_to_key
from itertools import islice
import gc
import json
import hashlib
import logging
import math
import os
import resource
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.statuses import TradeOutcome
from trade_proposer_app.domain.models import (
    PlanGenerationTuningCandidate,
    PlanGenerationTuningConfigVersion,
    PlanGenerationTuningEvent,
    PlanGenerationTuningRun,
    PlanGenerationTuningState,
    RecommendationDecisionSample,
    RecommendationPlan,
    RecommendationPlanOutcome,
)
from trade_proposer_app.persistence.models import (
    BrokerPositionRecord,
    HistoricalReplayBatchRecord,
    HistoricalReplaySliceRecord,
    PlanGenerationTuningEligibleRecordRecord,
    RecommendationDecisionSampleRecord,
    RecommendationOutcomeRecord,
    RecommendationPlanRecord,
    ReplayEligibilityRecord,
    ReplayPlanOutcomeRecord,
)
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.recommendation_decision_samples import (
    RecommendationDecisionSampleRepository,
)
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.policy_trust_report import PolicyTrustReportService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_reliability_features import PlanReliabilityFeatureBuilder
from trade_proposer_app.services.input_access import stable_hash
from trade_proposer_app.services.outcome_population import summarize_outcome_population
from trade_proposer_app.services.replay_evidence_quality import replay_outcome_population_rejection_reasons
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    PARAMETER_BY_KEY,
    candidate_validation_depth,
    exploration_campaigns,
    normalize_plan_generation_tuning_config,
    parameter_definitions,
)
from trade_proposer_app.services.plan_generation_walk_forward import (
    PlanGenerationWalkForwardService,
)
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.settings_mutations import SettingsMutationService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
from trade_proposer_app.utils.json_payloads import loads_json_object


logger = logging.getLogger(__name__)


class PlanGenerationTuningError(Exception):
    pass


@dataclass(slots=True)
class TuningPlanSnapshot:
    id: int
    computed_at: datetime | None
    action: str
    confidence_percent: float
    entry_price_low: float | None
    entry_price_high: float | None
    stop_loss: float | None
    take_profit: float | None
    signal_breakdown: dict[str, object]
    ticker: str = ""


@dataclass(slots=True)
class TuningOutcomeSnapshot:
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    horizon_return_5d: float | None


@dataclass(slots=True)
class EligibleTuningRecord:
    plan: RecommendationPlan | TuningPlanSnapshot
    outcome: RecommendationPlanOutcome | TuningOutcomeSnapshot
    sample: RecommendationDecisionSample | None
    setup_family: str
    context_bias: str | None


@dataclass(slots=True)
class CandidateEvaluation:
    config: dict[str, float]
    changed_keys: list[str]
    search_actionable_count: int
    search_win_count: int
    search_expected_value: float
    search_ambiguous_count: int
    validation_actionable_count: int
    validation_win_count: int
    validation_expected_value: float
    validation_ambiguous_count: int
    validation_slice_count: int = 0
    validation_baseline_win_count: int = 0
    validation_ties: int = 0
    validation_average_win_rate_delta: float | None = None
    validation_average_expected_value_delta: float | None = None

    @property
    def search_win_rate(self) -> float:
        if self.search_actionable_count <= 0:
            return 0.0
        return self.search_win_count / self.search_actionable_count

    @property
    def validation_win_rate(self) -> float:
        if self.validation_actionable_count <= 0:
            return 0.0
        return self.validation_win_count / self.validation_actionable_count


class PlanGenerationTuningService:
    OBJECTIVE_NAME = "plan_generation_precision_tuning_v1"
    ELIGIBLE_RECORD_CACHE_VERSION = "eligible_records_v2"
    SCHEMA_VERSION = "v1"
    WIN_RATE_TIE_TOLERANCE = 0.0025
    WIN_COUNT_TIE_TOLERANCE = 1
    EXPECTED_VALUE_TIE_TOLERANCE = 0.02
    MEMORY_GUARD_FRACTION = 0.8
    MEMORY_GUARD_FALLBACK_BYTES = 1_500_000_000
    ELIGIBLE_RECORD_BATCH_SIZE = 250

    def __init__(
        self,
        session: Session,
        historical_replay_service: object | None = None,
        job_execution_service: object | None = None,
    ) -> None:
        self.session = session
        self.settings = SettingsRepository(session)
        self.repository = PlanGenerationTuningRepository(session)
        self.plans = RecommendationPlanRepository(session)
        self.outcomes = EffectivePlanOutcomeRepository(session)
        self.samples = RecommendationDecisionSampleRepository(session)
        self.reliability_features = PlanReliabilityFeatureBuilder()
        self.settings_domains = SettingsDomainService(repository=self.settings)
        self.settings_mutations = SettingsMutationService(repository=self.settings)
        self.historical_replay_service = historical_replay_service
        self.job_execution_service = job_execution_service

    def describe(self) -> dict[str, object]:
        baseline = self.ensure_baseline_config_version()
        active_version_id = self._active_config_version_id() or baseline.id
        active_version = (
            self.repository.get_config_version(active_version_id)
            if active_version_id is not None
            else baseline
        )
        latest_run = self.repository.get_latest_run()
        state = PlanGenerationTuningState(
            objective_name=self.OBJECTIVE_NAME,
            active_config_version_id=active_version.id,
            active_config=normalize_plan_generation_tuning_config(active_version.config),
            auto_enabled=bool(
                self.settings_domains.strategy_settings().plan_generation_tuning["auto_enabled"]
            ),
            auto_promote_enabled=bool(
                self.settings_domains.strategy_settings().plan_generation_tuning[
                    "auto_promote_enabled"
                ]
            ),
            latest_run=latest_run,
        )
        return {
            "objective_name": self.OBJECTIVE_NAME,
            "parameter_schema_version": self.SCHEMA_VERSION,
            "parameters": parameter_definitions(),
            "exploration_campaigns": exploration_campaigns(),
            "state": state,
        }

    def ensure_baseline_config_version(self) -> PlanGenerationTuningConfigVersion:
        versions = self.repository.list_config_versions(limit=200)
        for version in versions:
            if version.source == "seed" and version.version_label == "baseline-v1":
                normalized = normalize_plan_generation_tuning_config(version.config)
                if (
                    float(normalized.get("global.actionable_confidence_floor_percent", 0.0) or 0.0)
                    >= 60.0
                ):
                    return version
                active_id = self._active_config_version_id()
                if active_id is not None and active_id != version.id:
                    return version
                upgraded = self.repository.create_config_version(
                    PlanGenerationTuningConfigVersion(
                        version_label="baseline-v1-actionability-on",
                        status="active",
                        source="seed",
                        parent_config_version_id=version.id,
                        config={**normalized, "global.actionable_confidence_floor_percent": 60.0},
                        parameter_schema_version=self.SCHEMA_VERSION,
                    )
                )
                self.settings_mutations.set_plan_generation_active_config_version_id(upgraded.id)
                self.repository.create_event(
                    PlanGenerationTuningEvent(
                        event_type="baseline_reseeded",
                        config_version_id=upgraded.id,
                        payload={
                            "version_label": upgraded.version_label,
                            "parent_version_id": version.id,
                        },
                    )
                )
                return upgraded
        version = self.repository.create_config_version(
            PlanGenerationTuningConfigVersion(
                version_label="baseline-v1",
                status="active",
                source="seed",
                config={
                    **normalize_plan_generation_tuning_config(None),
                    "global.actionable_confidence_floor_percent": 60.0,
                },
                parameter_schema_version=self.SCHEMA_VERSION,
            )
        )
        self.settings_mutations.set_plan_generation_active_config_version_id(version.id)
        self.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="baseline_seeded",
                config_version_id=version.id,
                payload={"version_label": version.version_label},
            )
        )
        return version

    def run(
        self,
        *,
        mode: str = "manual",
        apply: bool = False,
        auto: bool | None = None,
        ticker: str | None = None,
        setup_family: str | None = None,
        limit: int | None = None,
        execute_replay_candidates: bool = False,
        replay_candidate_limit: int = 3,
    ) -> PlanGenerationTuningRun:
        started_at = datetime.now(timezone.utc)
        logger.info(
            "plan generation tuning started: mode=%s apply=%s ticker=%s setup_family=%s limit=%s",
            mode,
            apply,
            ticker,
            setup_family,
            limit,
        )
        baseline_version = self._resolve_active_config_version()
        active_config = normalize_plan_generation_tuning_config(baseline_version.config)
        mode_profile = self._mode_profile(mode)
        explore_mode = bool(mode_profile["explore_like"])
        wide_mode = mode_profile["name"] in {"wide", "wide_point_in_time_replay"}
        replay_mode = bool(mode_profile.get("replay_like"))
        effective_limit = None if limit is None else max(1, int(limit))
        records = (
            self._replay_eligible_records(ticker=ticker, setup_family=setup_family, limit=effective_limit)
            if replay_mode
            else self._eligible_records(ticker=ticker, setup_family=setup_family, limit=effective_limit)
        )
        logger.info(
            "plan generation tuning eligibility: mode=%s explore=%s wide=%s eligible_records=%s effective_limit=%s",
            mode,
            explore_mode,
            wide_mode,
            len(records),
            effective_limit,
        )
        settings_payload = self.settings_domains.strategy_settings().plan_generation_tuning
        min_actionable_resolved = int(settings_payload["min_actionable_resolved"])
        min_validation_resolved = int(settings_payload["min_validation_resolved"])
        if len(records) < min_actionable_resolved:
            raise PlanGenerationTuningError(
                f"insufficient eligible records for plan generation tuning: {len(records)} available, minimum is {min_actionable_resolved}"
            )
        search_records, validation_records = self._split_records(
            records, min_validation=min_validation_resolved
        )
        exploration_seed = self._exploration_seed(
            active_config=active_config, records=records, mode=mode
        )
        walk_forward_service = PlanGenerationWalkForwardService(self)
        batch_size = int(mode_profile["batch_size"])
        (
            evaluations,
            baseline_eval,
            refinement_candidates,
            refinement_seed_count,
            evaluation_batch_count,
        ) = self._evaluate_candidate_search(
            active_config=active_config,
            records=records,
            search_records=search_records,
            validation_records=validation_records,
            walk_forward_service=walk_forward_service,
            mode=mode,
            explore_mode=explore_mode,
            batch_size=batch_size,
            max_candidates=int(mode_profile["max_candidates"]),
            min_validation_resolved=min_validation_resolved,
            exploration_seed=exploration_seed,
        )
        winner = evaluations[0]
        logger.info(
            "plan generation tuning ranked candidates: mode=%s winner_rank=%s winner_validation_win_rate=%.2f winner_validation_win_count=%s winner_validation_expected_value=%.4f",
            mode,
            1,
            round(winner.validation_win_rate * 100.0, 2),
            winner.validation_win_count,
            winner.validation_expected_value,
        )
        history_span_days = self._history_span_days(records)
        validation_days = 120 if wide_mode else 90
        step_days = 14 if wide_mode else 30
        walk_forward_validation = walk_forward_service.summarize_records(
            records=records,
            candidate_config=winner.config,
            baseline_config=active_config,
            candidate_label=f"run-{mode}-winner" if mode else "candidate",
            baseline_label="active-baseline",
            lookback_days=history_span_days,
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_validation_resolved,
        )

        run = self.repository.create_run(
            PlanGenerationTuningRun(
                status="completed",
                mode=mode,
                objective_name=self.OBJECTIVE_NAME,
                promotion_mode="apply" if apply else "dry_run",
                baseline_config_version_id=baseline_version.id,
                eligible_record_count=len(records),
                eligible_tier_a_count=len(records),
                validation_record_count=len(validation_records),
                candidate_count=len(evaluations),
                summary={
                    "winner": self._candidate_payload(winner),
                    "baseline": self._candidate_payload(baseline_eval),
                    "promotion_requested": apply,
                    "exploration_mode": explore_mode,
                    "wide_research_mode": wide_mode,
                    "tuning_source_mode": "point_in_time_replay" if replay_mode else "stored_plan_rescore",
                    "exploration_seed": exploration_seed,
                    "exploration_campaign_plan": exploration_campaigns(),
                    "search_record_count": len(search_records),
                    "validation_record_count": len(validation_records),
                    "validation_mode": "rolling_walk_forward" if explore_mode else "single_holdout",
                    "validation_slice_count": walk_forward_validation.total_slices
                    if explore_mode
                    else len(validation_records),
                    "history_span_days": history_span_days,
                    "requested_limit": limit,
                    "effective_limit": effective_limit,
                    "record_batch_size": self.ELIGIBLE_RECORD_BATCH_SIZE,
                    "candidate_batch_size": batch_size,
                    "evaluation_batch_count": evaluation_batch_count,
                    "refinement_candidate_count": len(refinement_candidates),
                    "refinement_seed_count": refinement_seed_count,
                    "walk_forward_validation": walk_forward_validation.model_dump(mode="json"),
                },
                filters={
                    "ticker": ticker.upper() if ticker else None,
                    "setup_family": setup_family,
                    "limit": limit,
                    "mode": mode,
                    "explore_mode": explore_mode,
                    "wide_mode": wide_mode,
                    "replay_mode": replay_mode,
                },
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
        )

        stored_candidates = self._store_candidate_evaluations(
            run_id=run.id or 0,
            evaluations=evaluations,
            baseline_eval=baseline_eval,
            min_validation_resolved=min_validation_resolved,
        )
        winner_candidate = stored_candidates[0]
        defer_replay_promotion = bool(replay_mode and execute_replay_candidates)
        if replay_mode and apply and not execute_replay_candidates:
            promoted_config_version_id = None
            promotion_applied = False
            promotion_rejection_reasons = ["replay_candidate_execution_required_for_promotion"]
            edge_gate_report = None
        else:
            (
                promoted_config_version_id,
                promotion_applied,
                promotion_rejection_reasons,
                edge_gate_report,
            ) = self._apply_winner_promotion(
                apply=apply and not defer_replay_promotion,
                run=run,
                winner_candidate=winner_candidate,
                baseline_version=baseline_version,
                walk_forward_validation=walk_forward_validation,
            )

        updated_run = self.repository.get_run(run.id or 0)
        updated_run.winning_candidate_id = winner_candidate.id
        updated_run.promoted_config_version_id = promoted_config_version_id
        updated_run.summary["winner_candidate_id"] = winner_candidate.id
        updated_run.summary["promoted_config_version_id"] = promoted_config_version_id
        updated_run.summary["promotion_requested"] = apply
        updated_run.summary["promotion_applied"] = promotion_applied
        updated_run.summary["promotion_rejection_reasons"] = promotion_rejection_reasons
        if apply:
            updated_run.summary["edge_validation_gate"] = edge_gate_report
        updated_run.summary["baseline_config_version_id"] = baseline_version.id
        finished_run = self.repository.update_run(run.id or 0, updated_run)
        if replay_mode and execute_replay_candidates:
            replay_execution = self.execute_replay_candidate_batches_from_run(
                finished_run.id or 0,
                candidate_limit=replay_candidate_limit,
            )
            refreshed_run = self.repository.get_run(finished_run.id or 0)
            refreshed_run.summary["candidate_replay_execution"] = replay_execution
            refreshed_run.summary["candidate_replay_execution_requested"] = True
            if apply:
                replay_promotion = self._apply_replay_reranked_promotion(
                    run=refreshed_run,
                    replay_execution=replay_execution,
                    baseline_version=baseline_version,
                    walk_forward_validation=walk_forward_validation,
                    min_validation_resolved=min_validation_resolved,
                )
                refreshed_run = self.repository.get_run(finished_run.id or 0)
                refreshed_run.winning_candidate_id = replay_promotion.get("replay_winner_candidate_id") or refreshed_run.winning_candidate_id
                refreshed_run.promoted_config_version_id = replay_promotion.get("promoted_config_version_id")
                refreshed_run.summary["replay_promotion"] = replay_promotion
                refreshed_run.summary["promotion_applied"] = bool(replay_promotion.get("promotion_applied"))
                refreshed_run.summary["promotion_rejection_reasons"] = replay_promotion.get("promotion_rejection_reasons", [])
                refreshed_run.summary["promoted_config_version_id"] = replay_promotion.get("promoted_config_version_id")
                if replay_promotion.get("edge_validation_gate") is not None:
                    refreshed_run.summary["edge_validation_gate"] = replay_promotion.get("edge_validation_gate")
            finished_run = self.repository.update_run(refreshed_run.id or 0, refreshed_run)
        logger.info(
            "plan generation tuning finished: run_id=%s status=%s candidate_count=%s promoted_config_version_id=%s duration_seconds=%.3f",
            finished_run.id,
            finished_run.status,
            finished_run.candidate_count,
            finished_run.promoted_config_version_id,
            (datetime.now(timezone.utc) - started_at).total_seconds(),
        )
        return finished_run

    def _apply_replay_reranked_promotion(
        self,
        *,
        run: PlanGenerationTuningRun,
        replay_execution: dict[str, object],
        baseline_version: PlanGenerationTuningConfigVersion,
        walk_forward_validation: object,
        min_validation_resolved: int,
    ) -> dict[str, object]:
        aggregate = replay_execution.get("aggregate") if isinstance(replay_execution, dict) else None
        if not isinstance(aggregate, dict):
            return {
                "promotion_applied": False,
                "promoted_config_version_id": None,
                "promotion_rejection_reasons": ["missing_replay_aggregate"],
                "replay_winner_candidate_id": None,
                "edge_validation_gate": None,
            }
        rerank = aggregate.get("rerank")
        if not isinstance(rerank, list) or not rerank:
            return {
                "promotion_applied": False,
                "promoted_config_version_id": None,
                "promotion_rejection_reasons": ["missing_replay_rerank"],
                "replay_winner_candidate_id": None,
                "edge_validation_gate": None,
            }
        top = rerank[0] if isinstance(rerank[0], dict) else {}
        replay_winner_candidate_id = int(top.get("candidate_id") or 0)
        rejection_reasons: list[str] = []
        if replay_winner_candidate_id <= 0:
            rejection_reasons.append("missing_replay_winner_candidate")
        if int(top.get("tier_a_count") or 0) <= 0:
            rejection_reasons.append("replay_winner_missing_tier_a_evidence")
        if int(top.get("eligible_record_count") or 0) < min_validation_resolved:
            rejection_reasons.append("replay_winner_insufficient_eligible_records")
        rejection_reasons.extend(self._replay_evidence_quality_rejection_reasons(top, min_validation_resolved=min_validation_resolved))
        replay_walk_forward_validation = aggregate.get("replay_walk_forward_validation") if isinstance(aggregate, dict) else None
        if not isinstance(replay_walk_forward_validation, dict) or not replay_walk_forward_validation.get("passed"):
            rejection_reasons.append("replay_winner_failed_rolling_baseline_comparison")
        if rejection_reasons:
            return {
                "promotion_applied": False,
                "promoted_config_version_id": None,
                "promotion_rejection_reasons": rejection_reasons,
                "replay_winner_candidate_id": replay_winner_candidate_id or None,
                "replay_rerank_top": top,
                "edge_validation_gate": None,
                "replay_walk_forward_validation": replay_walk_forward_validation,
            }
        replay_winner = self.repository.get_candidate(replay_winner_candidate_id)
        (
            promoted_config_version_id,
            promotion_applied,
            promotion_rejection_reasons,
            edge_gate_report,
        ) = self._apply_winner_promotion(
            apply=True,
            run=run,
            winner_candidate=replay_winner,
            baseline_version=baseline_version,
            walk_forward_validation=walk_forward_validation,
        )
        return {
            "promotion_applied": promotion_applied,
            "promoted_config_version_id": promoted_config_version_id,
            "promotion_rejection_reasons": promotion_rejection_reasons,
            "replay_winner_candidate_id": replay_winner_candidate_id,
            "replay_rerank_top": top,
            "edge_validation_gate": edge_gate_report,
            "replay_walk_forward_validation": replay_walk_forward_validation,
        }

    def enqueue_replay_candidate_batches_from_run(
        self,
        run_id: int,
        *,
        candidate_limit: int = 3,
        enqueue: bool = True,
    ) -> dict[str, object]:
        """Create deterministic historical replay batches for ranked candidate configs.

        This is the first execution bridge for replay tuning: an already-ranked replay tuning run can
        ask the replay service to regenerate slices for candidate configs instead of relying only on
        previously materialized replay eligibility artifacts.
        """
        if self.historical_replay_service is None:
            raise PlanGenerationTuningError("historical replay service is not configured")
        run = self.repository.get_run(run_id)
        candidates = self.repository.list_candidates_for_run(run_id)[: max(1, int(candidate_limit))]
        if not candidates:
            raise PlanGenerationTuningError(f"plan generation tuning run {run_id} has no candidates")
        slice_plan = self._replay_candidate_slice_plan()
        if not slice_plan["tickers"] or slice_plan["as_of_start"] is None or slice_plan["as_of_end"] is None:
            raise PlanGenerationTuningError("no current replay eligibility artifacts available for candidate replay execution")
        created_batches: list[dict[str, object]] = []
        for candidate in candidates:
            config_hash = stable_hash(candidate.config)
            depth_payload = candidate_validation_depth(candidate.changed_keys)
            existing = self._existing_replay_candidate_batch(run_id, candidate.id or 0, config_hash)
            if existing is not None:
                batch_id = existing.id
                queued_run_count = 0
                status = existing.status
            else:
                batch = self.historical_replay_service.create_batch(
                    name=f"tuning-run-{run_id}-candidate-{candidate.id}-{config_hash[:12]}",
                    mode="research",
                    tickers=list(slice_plan["tickers"]),
                    as_of_start=slice_plan["as_of_start"],
                    as_of_end=slice_plan["as_of_end"],
                    config={
                        "source": "plan_generation_tuning_candidate_replay",
                        "plan_generation_tuning_run_id": run_id,
                        "plan_generation_tuning_candidate_id": candidate.id,
                        "plan_generation_tuning_candidate_rank": candidate.rank,
                        "candidate_config_hash": config_hash,
                        "candidate_validation_depth": depth_payload["validation_depth"],
                        "candidate_validation_depth_reason": depth_payload["validation_depth_reason"],
                        "plan_generation_tuning_config_override": candidate.config,
                        "baseline_config_version_id": run.baseline_config_version_id,
                    },
                )
                queued_runs = self.historical_replay_service.enqueue_batch(batch.id or 0) if enqueue else []
                batch_id = batch.id
                queued_run_count = len(queued_runs)
                status = "queued" if enqueue else batch.status
            created_batches.append(
                {
                    "candidate_id": candidate.id,
                    "candidate_rank": candidate.rank,
                    "candidate_config_hash": config_hash,
                    "validation_depth": depth_payload["validation_depth"],
                    "validation_depth_reason": depth_payload["validation_depth_reason"],
                    "replay_batch_id": batch_id,
                    "status": status,
                    "queued_run_count": queued_run_count,
                }
            )
        return {
            "status": "created" if created_batches else "skipped",
            "run_id": run_id,
            "candidate_count": len(created_batches),
            "slice_count": slice_plan["slice_count"],
            "tickers": slice_plan["tickers"],
            "as_of_start": slice_plan["as_of_start"].isoformat(),
            "as_of_end": slice_plan["as_of_end"].isoformat(),
            "batches": created_batches,
        }

    def execute_replay_candidate_batches_from_run(
        self,
        run_id: int,
        *,
        candidate_limit: int = 3,
        worker_id: str = "plan-generation-replay-tuning",
    ) -> dict[str, object]:
        """Create/enqueue candidate replay batches, execute their queued slices, then aggregate.

        This is intentionally synchronous and bounded by candidate_limit. It is meant for research
        workflows/tests first; scheduled production use can keep using the async bridge.
        """
        if self.job_execution_service is None:
            raise PlanGenerationTuningError("job execution service is not configured")
        from trade_proposer_app.repositories.runs import RunRepository

        bridge = self.enqueue_replay_candidate_batches_from_run(
            run_id,
            candidate_limit=candidate_limit,
            enqueue=True,
        )
        batch_ids = [
            int(item["replay_batch_id"])
            for item in bridge.get("batches", [])
            if isinstance(item, dict) and item.get("replay_batch_id") is not None
        ]
        run_ids = [
            int(row.run_id)
            for row in self.session.scalars(
                select(HistoricalReplaySliceRecord).where(
                    HistoricalReplaySliceRecord.replay_batch_id.in_(batch_ids),
                    HistoricalReplaySliceRecord.run_id.is_not(None),
                )
            ).all()
            if row.run_id is not None
        ]
        runs = RunRepository(self.session)
        executed_run_ids: list[int] = []
        skipped_run_ids: list[int] = []
        for replay_run_id in sorted(set(run_ids)):
            claimed = runs.claim_queued_run(replay_run_id, worker_id=worker_id)
            if claimed is None:
                skipped_run_ids.append(replay_run_id)
                continue
            self.job_execution_service.execute_claimed_run(claimed, worker_id=worker_id)
            executed_run_ids.append(replay_run_id)
        aggregate = self.aggregate_replay_candidate_batch_results(run_id)
        return {
            "status": "completed",
            "run_id": run_id,
            "bridge": bridge,
            "executed_run_count": len(executed_run_ids),
            "executed_run_ids": executed_run_ids,
            "skipped_run_ids": skipped_run_ids,
            "aggregate": aggregate,
        }

    def aggregate_replay_candidate_batch_results(self, run_id: int) -> dict[str, object]:
        """Aggregate completed candidate replay artifacts back to the tuning candidate level."""
        candidates = {candidate.id: candidate for candidate in self.repository.list_candidates_for_run(run_id)}
        batches = self._candidate_replay_batches_for_run(run_id)
        summaries: list[dict[str, object]] = []
        for batch in batches:
            config = loads_json_object(batch.config_json)
            candidate_id = int(config.get("plan_generation_tuning_candidate_id") or 0)
            if candidate_id not in candidates:
                continue
            eligibility_rows = self.session.scalars(
                select(ReplayEligibilityRecord).where(ReplayEligibilityRecord.replay_batch_id == batch.id)
            ).all()
            window_summary = self._replay_candidate_window_summary(batch.id or 0)
            tier_counts: dict[str, int] = {}
            outcome_counts: dict[str, int] = {}
            resolution_source_counts: dict[str, int] = {}
            eligible_count = 0
            for row in eligibility_rows:
                tier_counts[row.tier] = tier_counts.get(row.tier, 0) + 1
                outcome_counts[row.outcome] = outcome_counts.get(row.outcome, 0) + 1
                resolution_source_counts[row.resolution_source] = resolution_source_counts.get(row.resolution_source, 0) + 1
                if row.eligible_for_tuning:
                    eligible_count += 1
            summaries.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_rank": candidates[candidate_id].rank,
                    "candidate_config_hash": config.get("candidate_config_hash"),
                    "replay_batch_id": batch.id,
                    "replay_batch_status": batch.status,
                    "eligible_record_count": eligible_count,
                    "total_record_count": len(eligibility_rows),
                    "outcome_population": summarize_outcome_population(
                        eligibility_rows,
                        population="replay_tier_a_b_eligible",
                        outcome_attr="outcome",
                        tier_attr="tier",
                    ),
                    "tier_counts": tier_counts,
                    "outcome_counts": outcome_counts,
                    "resolution_source_counts": resolution_source_counts,
                    "rolling_windows": window_summary["windows"],
                    "rolling_window_summary": window_summary["summary"],
                }
            )
        summaries.sort(key=lambda item: (int(item.get("candidate_rank") or 0), int(item.get("replay_batch_id") or 0)))
        rerank = self._rerank_replay_candidate_results(summaries)
        replay_walk_forward_validation = self._replay_candidate_vs_baseline_walk_forward(summaries, candidates)
        return {
            "status": "completed" if summaries else "empty",
            "run_id": run_id,
            "candidate_result_count": len(summaries),
            "results": summaries,
            "rerank": rerank,
            "replay_winner_candidate_id": rerank[0]["candidate_id"] if rerank else None,
            "replay_walk_forward_validation": replay_walk_forward_validation,
        }

    def _replay_candidate_window_summary(self, replay_batch_id: int) -> dict[str, object]:
        rows = self.session.execute(
            select(ReplayEligibilityRecord, HistoricalReplaySliceRecord)
            .join(
                HistoricalReplaySliceRecord,
                HistoricalReplaySliceRecord.id == ReplayEligibilityRecord.replay_slice_id,
            )
            .where(ReplayEligibilityRecord.replay_batch_id == replay_batch_id)
            .where(ReplayEligibilityRecord.eligible_for_tuning.is_(True))
            .order_by(HistoricalReplaySliceRecord.as_of.asc(), ReplayEligibilityRecord.id.asc())
        ).all()
        by_date: dict[str, dict[str, object]] = {}
        for eligibility, replay_slice in rows:
            key = replay_slice.as_of.date().isoformat()
            bucket = by_date.setdefault(
                key,
                {"as_of_date": key, "eligible_count": 0, "win_count": 0, "loss_count": 0, "tier_a_count": 0},
            )
            bucket["eligible_count"] = int(bucket["eligible_count"]) + 1
            if eligibility.tier == "tier_a":
                bucket["tier_a_count"] = int(bucket["tier_a_count"]) + 1
            if eligibility.outcome in {"win", "phantom_win"}:
                bucket["win_count"] = int(bucket["win_count"]) + 1
            elif eligibility.outcome in {"loss", "phantom_loss"}:
                bucket["loss_count"] = int(bucket["loss_count"]) + 1
        windows = list(by_date.values())
        for window in windows:
            resolved = int(window["win_count"]) + int(window["loss_count"])
            window["resolved_count"] = resolved
            window["win_rate_percent"] = round((int(window["win_count"]) / resolved) * 100.0, 2) if resolved else None
        qualified = [item for item in windows if int(item.get("resolved_count") or 0) > 0]
        positive = [item for item in qualified if float(item.get("win_rate_percent") or 0.0) >= 50.0]
        return {
            "windows": windows,
            "summary": {
                "window_count": len(windows),
                "qualified_windows": len(qualified),
                "positive_windows": len(positive),
                "promotion_recommended": bool(qualified and len(positive) >= max(1, len(qualified) // 2 + len(qualified) % 2)),
            },
        }

    @staticmethod
    def _replay_candidate_vs_baseline_walk_forward(
        summaries: list[dict[str, object]],
        candidates: dict[int | None, PlanGenerationTuningCandidate],
    ) -> dict[str, object]:
        baseline_ids = {candidate_id for candidate_id, candidate in candidates.items() if candidate.is_baseline or not candidate.changed_keys}
        baseline = next((item for item in summaries if item.get("candidate_id") in baseline_ids), None)
        winner = PlanGenerationTuningService._rerank_replay_candidate_results(summaries)[0] if summaries else None
        if baseline is None or winner is None:
            return {"passed": False, "promotion_recommended": False, "reason": "baseline_or_winner_missing"}
        winner_summary = next((item for item in summaries if item.get("candidate_id") == winner.get("candidate_id")), None)
        if winner_summary is None:
            return {"passed": False, "promotion_recommended": False, "reason": "winner_summary_missing"}

        def rate(item: dict[str, object]) -> float | None:
            outcome_counts = item.get("outcome_counts") if isinstance(item.get("outcome_counts"), dict) else {}
            wins = sum(int(outcome_counts.get(key, 0) or 0) for key in ("win", "phantom_win"))
            losses = sum(int(outcome_counts.get(key, 0) or 0) for key in ("loss", "phantom_loss"))
            return (wins / (wins + losses)) * 100.0 if wins + losses else None

        winner_rate = rate(winner_summary)
        baseline_rate = rate(baseline)
        window_pairs: list[dict[str, object]] = []
        baseline_windows = {
            str(item.get("as_of_date")): item
            for item in baseline.get("rolling_windows", [])
            if isinstance(item, dict)
        }
        for window in winner_summary.get("rolling_windows", []):
            if not isinstance(window, dict):
                continue
            base_window = baseline_windows.get(str(window.get("as_of_date")))
            if not isinstance(base_window, dict):
                continue
            candidate_rate = window.get("win_rate_percent")
            base_rate = base_window.get("win_rate_percent")
            passed = candidate_rate is not None and base_rate is not None and float(candidate_rate) >= float(base_rate)
            window_pairs.append(
                {
                    "as_of_date": window.get("as_of_date"),
                    "candidate_win_rate_percent": candidate_rate,
                    "baseline_win_rate_percent": base_rate,
                    "passed": passed,
                    "candidate_resolved_count": window.get("resolved_count"),
                    "baseline_resolved_count": base_window.get("resolved_count"),
                }
            )
        passed_windows = sum(1 for item in window_pairs if item["passed"])
        rate_delta = None if winner_rate is None or baseline_rate is None else round(winner_rate - baseline_rate, 2)
        passed = bool(window_pairs) and passed_windows >= max(1, len(window_pairs) // 2 + len(window_pairs) % 2) and rate_delta is not None and rate_delta >= 0.0
        return {
            "passed": passed,
            "promotion_recommended": passed,
            "reason": None if passed else "replay_candidate_failed_rolling_baseline_comparison",
            "candidate_id": winner.get("candidate_id"),
            "baseline_candidate_id": baseline.get("candidate_id"),
            "qualified_slices": len(window_pairs),
            "passed_slices": passed_windows,
            "candidate_win_rate_percent": round(winner_rate, 2) if winner_rate is not None else None,
            "baseline_win_rate_percent": round(baseline_rate, 2) if baseline_rate is not None else None,
            "win_rate_delta_percent": rate_delta,
            "windows": window_pairs,
        }

    @staticmethod
    def _rerank_replay_candidate_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
        ranked: list[dict[str, object]] = []
        for result in results:
            tier_counts = result.get("tier_counts") if isinstance(result.get("tier_counts"), dict) else {}
            outcome_counts = result.get("outcome_counts") if isinstance(result.get("outcome_counts"), dict) else {}
            eligible_count = int(result.get("eligible_record_count") or 0)
            tier_a_count = int(tier_counts.get("tier_a", 0) or 0)
            tier_b_count = int(tier_counts.get("tier_b", 0) or 0)
            win_count = sum(int(outcome_counts.get(key, 0) or 0) for key in ("win", "phantom_win"))
            loss_count = sum(int(outcome_counts.get(key, 0) or 0) for key in ("loss", "phantom_loss"))
            resolved_count = win_count + loss_count + int(outcome_counts.get("expired", 0) or 0)
            replay_score = round(
                (tier_a_count * 3.0)
                + (tier_b_count * 1.0)
                + (win_count * 2.0)
                - (loss_count * 2.0)
                + (eligible_count * 0.25),
                4,
            )
            ranked.append(
                {
                    "candidate_id": result.get("candidate_id"),
                    "candidate_rank": result.get("candidate_rank"),
                    "candidate_config_hash": result.get("candidate_config_hash"),
                    "replay_batch_id": result.get("replay_batch_id"),
                    "eligible_record_count": eligible_count,
                    "tier_a_count": tier_a_count,
                    "tier_b_count": tier_b_count,
                    "win_count": win_count,
                    "loss_count": loss_count,
                    "resolved_count": resolved_count,
                    "replay_score": replay_score,
                    "outcome_population": result.get("outcome_population") if isinstance(result.get("outcome_population"), dict) else None,
                }
            )
        ranked.sort(
            key=lambda item: (
                -float(item["replay_score"]),
                -int(item["tier_a_count"]),
                -int(item["eligible_record_count"]),
                int(item.get("candidate_rank") or 999999),
            )
        )
        return ranked

    def _candidate_replay_batches_for_run(self, run_id: int) -> list[HistoricalReplayBatchRecord]:
        rows = self.session.scalars(
            select(HistoricalReplayBatchRecord).where(
                HistoricalReplayBatchRecord.config_json.contains(
                    f'"plan_generation_tuning_run_id": {run_id}'
                )
            )
        ).all()
        return [
            row
            for row in rows
            if int(loads_json_object(row.config_json).get("plan_generation_tuning_run_id") or 0) == run_id
        ]

    def _replay_candidate_slice_plan(self) -> dict[str, object]:
        current_versions = self._current_replay_artifact_versions()
        query = (
            select(ReplayEligibilityRecord, RecommendationPlanRecord)
            .join(
                RecommendationPlanRecord,
                RecommendationPlanRecord.id == ReplayEligibilityRecord.recommendation_plan_id,
            )
            .where(ReplayEligibilityRecord.eligible_for_tuning.is_(True))
            .where(ReplayEligibilityRecord.tier.in_(["tier_a", "tier_b"]))
        )
        tickers: set[str] = set()
        as_of_values: list[datetime] = []
        for eligibility_row, plan_row in self.session.execute(query).all():
            diagnostics = loads_json_object(eligibility_row.diagnostics_json)
            if not self._replay_artifact_versions_current(diagnostics, current_versions):
                continue
            tickers.add(str(eligibility_row.ticker or plan_row.ticker or "").strip().upper())
            artifact_key = diagnostics.get("artifact_key")
            as_of = None
            if isinstance(artifact_key, dict):
                as_of = self._parse_datetime_value(artifact_key.get("as_of"))
            as_of_values.append(as_of or self._normalize_datetime(plan_row.computed_at) or datetime.now(timezone.utc))
        return {
            "tickers": sorted(item for item in tickers if item),
            "as_of_start": min(as_of_values) if as_of_values else None,
            "as_of_end": max(as_of_values) if as_of_values else None,
            "slice_count": len(set(value.date().isoformat() for value in as_of_values)),
        }

    def _existing_replay_candidate_batch(
        self, run_id: int, candidate_id: int, candidate_config_hash: str
    ) -> HistoricalReplayBatchRecord | None:
        rows = self.session.scalars(
            select(HistoricalReplayBatchRecord).where(
                HistoricalReplayBatchRecord.config_json.contains(
                    f'"plan_generation_tuning_run_id": {run_id}'
                )
            )
        ).all()
        for row in rows:
            config = loads_json_object(row.config_json)
            if (
                int(config.get("plan_generation_tuning_run_id") or 0) == run_id
                and int(config.get("plan_generation_tuning_candidate_id") or 0) == candidate_id
                and str(config.get("candidate_config_hash") or "") == candidate_config_hash
            ):
                return row
        return None

    @staticmethod
    def _parse_datetime_value(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return PlanGenerationTuningService._normalize_datetime(value)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return PlanGenerationTuningService._normalize_datetime(parsed)

    def _store_candidate_evaluations(
        self,
        *,
        run_id: int,
        evaluations: list[CandidateEvaluation],
        baseline_eval: CandidateEvaluation,
        min_validation_resolved: int,
    ) -> list[PlanGenerationTuningCandidate]:
        stored_candidates: list[PlanGenerationTuningCandidate] = []
        for rank, evaluation in enumerate(evaluations, start=1):
            promotion_eligible = self._promotion_eligible(
                evaluation, baseline_eval, min_validation_resolved=min_validation_resolved
            )
            candidate = self.repository.create_candidate(
                PlanGenerationTuningCandidate(
                    run_id=run_id,
                    rank=rank,
                    status="evaluated",
                    is_baseline=(evaluation.changed_keys == []),
                    promotion_eligible=promotion_eligible,
                    config=evaluation.config,
                    changed_keys=evaluation.changed_keys,
                    score_summary={
                        "search_win_rate": round(evaluation.search_win_rate * 100.0, 2),
                        "search_win_count": evaluation.search_win_count,
                        "search_expected_value": round(evaluation.search_expected_value, 4),
                        "validation_win_rate": round(evaluation.validation_win_rate * 100.0, 2),
                        "validation_win_count": evaluation.validation_win_count,
                        "validation_expected_value": round(evaluation.validation_expected_value, 4),
                    },
                    metric_breakdown=self._candidate_payload(evaluation),
                    sample_breakdown={
                        "search_actionable_count": evaluation.search_actionable_count,
                        "search_ambiguous_count": evaluation.search_ambiguous_count,
                        "validation_actionable_count": evaluation.validation_actionable_count,
                        "validation_ambiguous_count": evaluation.validation_ambiguous_count,
                        "validation_slice_count": evaluation.validation_slice_count,
                    },
                    validation_summary={
                        "validation_win_rate_percent": round(
                            evaluation.validation_win_rate * 100.0, 2
                        ),
                        "validation_actionable_count": evaluation.validation_actionable_count,
                        "validation_slice_count": evaluation.validation_slice_count,
                        "validation_baseline_win_count": evaluation.validation_baseline_win_count,
                        "validation_ties": evaluation.validation_ties,
                        "validation_average_win_rate_delta": evaluation.validation_average_win_rate_delta,
                        "validation_average_expected_value_delta": evaluation.validation_average_expected_value_delta,
                    },
                    rejection_reasons=[]
                    if promotion_eligible
                    else self._rejection_reasons(
                        evaluation, baseline_eval, min_validation_resolved=min_validation_resolved
                    ),
                )
            )
            stored_candidates.append(candidate)
        return stored_candidates

    def _apply_winner_promotion(
        self,
        *,
        apply: bool,
        run: PlanGenerationTuningRun,
        winner_candidate: PlanGenerationTuningCandidate,
        baseline_version: PlanGenerationTuningConfigVersion,
        walk_forward_validation: object,
    ) -> tuple[int | None, bool, list[str], dict[str, object] | None]:
        if not apply:
            return None, False, [], None
        logger.info(
            "plan generation tuning apply requested: run_id=%s winner_candidate_id=%s promotion_eligible=%s",
            run.id,
            winner_candidate.id,
            winner_candidate.promotion_eligible,
        )
        promotion_rejection_reasons: list[str] = []
        if not winner_candidate.promotion_eligible:
            promotion_rejection_reasons.extend(
                winner_candidate.rejection_reasons or ["winning_candidate_not_promotion_eligible"]
            )
        if getattr(walk_forward_validation, "qualified_slices", 0) >= 3 and not getattr(
            walk_forward_validation, "promotion_recommended", False
        ):
            rationale = (
                getattr(walk_forward_validation, "promotion_rationale", None)
                or "walk_forward_validation_rejected"
            ).strip()
            if rationale:
                promotion_rejection_reasons.append(rationale)
        edge_gate_report = self._edge_validation_gate_report(
            walk_forward_validation=walk_forward_validation
        )
        if edge_gate_report["label"] != "eligible_for_cautious_expansion":
            promotion_rejection_reasons.append(f"edge_validation_gate_{edge_gate_report['label']}")
        if promotion_rejection_reasons:
            self.repository.create_event(
                PlanGenerationTuningEvent(
                    event_type="config_promotion_skipped",
                    run_id=run.id,
                    candidate_id=winner_candidate.id,
                    payload={
                        "version_label": f"run-{run.id}-winner",
                        "rejection_reasons": promotion_rejection_reasons,
                        "edge_validation_gate": edge_gate_report,
                    },
                )
            )
            return None, False, promotion_rejection_reasons, edge_gate_report
        promoted = self.repository.create_config_version(
            PlanGenerationTuningConfigVersion(
                version_label=f"run-{run.id}-winner",
                status="active",
                source="tuning_run",
                parent_config_version_id=baseline_version.id,
                source_run_id=run.id,
                source_candidate_id=winner_candidate.id,
                config=winner_candidate.config,
                parameter_schema_version=self.SCHEMA_VERSION,
            )
        )
        self.settings_mutations.set_plan_generation_active_config_version_id(promoted.id)
        self.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="config_promoted",
                run_id=run.id,
                config_version_id=promoted.id,
                candidate_id=winner_candidate.id,
                payload={"version_label": promoted.version_label},
            )
        )
        return promoted.id, True, [], edge_gate_report

    def _evaluate_candidate_search(
        self,
        *,
        active_config: dict[str, float],
        records: list[EligibleTuningRecord],
        search_records: list[EligibleTuningRecord],
        validation_records: list[EligibleTuningRecord],
        walk_forward_service: PlanGenerationWalkForwardService,
        mode: str,
        explore_mode: bool,
        batch_size: int,
        max_candidates: int,
        min_validation_resolved: int,
        exploration_seed: int,
    ) -> tuple[list[CandidateEvaluation], CandidateEvaluation, list[dict[str, float]], int, int]:
        candidates = self._candidate_configs(active_config, mode=mode)
        evaluations: list[CandidateEvaluation] = []
        evaluation_batch_count = self._evaluate_candidate_batches(
            candidates,
            evaluations,
            active_config=active_config,
            search_records=search_records,
            validation_records=validation_records,
            walk_forward_records=records,
            walk_forward_service=walk_forward_service,
            mode=mode,
            explore_mode=explore_mode,
            batch_size=batch_size,
            min_validation_resolved=min_validation_resolved,
            exploration_seed=exploration_seed,
            phase="candidate",
            starting_batch_count=0,
        )
        evaluations.sort(key=cmp_to_key(self._candidate_compare))
        baseline_eval = next(item for item in evaluations if item.changed_keys == [])
        refinement_candidates = self._refinement_configs(
            evaluations,
            baseline_eval,
            active_config,
            mode=mode,
            max_candidates=max_candidates,
        )
        refinement_seed_count = 0
        if refinement_candidates:
            refinement_seed_count = min(2, len([item for item in evaluations if item.changed_keys]))
            evaluation_batch_count = self._evaluate_candidate_batches(
                refinement_candidates,
                evaluations,
                active_config=active_config,
                search_records=search_records,
                validation_records=validation_records,
                walk_forward_records=records,
                walk_forward_service=walk_forward_service,
                mode=mode,
                explore_mode=explore_mode,
                batch_size=batch_size,
                min_validation_resolved=min_validation_resolved,
                exploration_seed=exploration_seed,
                phase="refinement",
                starting_batch_count=evaluation_batch_count,
                seed_count=refinement_seed_count,
            )
        self._memory_guard(stage=f"{mode}-post-evaluation")
        evaluations.sort(key=cmp_to_key(self._candidate_compare))
        return (
            evaluations,
            baseline_eval,
            refinement_candidates,
            refinement_seed_count,
            evaluation_batch_count,
        )

    def _evaluate_candidate_batches(
        self,
        candidates: list[dict[str, float]],
        evaluations: list[CandidateEvaluation],
        *,
        active_config: dict[str, float],
        search_records: list[EligibleTuningRecord],
        validation_records: list[EligibleTuningRecord],
        walk_forward_records: list[EligibleTuningRecord],
        walk_forward_service: PlanGenerationWalkForwardService,
        mode: str,
        explore_mode: bool,
        batch_size: int,
        min_validation_resolved: int,
        exploration_seed: int,
        phase: str,
        starting_batch_count: int,
        seed_count: int = 0,
    ) -> int:
        batch_count = starting_batch_count
        phase_batches = max(1, math.ceil(len(candidates) / batch_size))
        if phase == "candidate":
            logger.info(
                "plan generation tuning candidate search prepared: mode=%s candidate_count=%s batch_size=%s total_batches=%s exploration_seed=%s",
                mode,
                len(candidates),
                batch_size,
                phase_batches,
                exploration_seed,
            )
        else:
            logger.info(
                "plan generation tuning refinement search prepared: mode=%s seed_count=%s candidate_count=%s batch_size=%s total_batches=%s exploration_seed=%s",
                mode,
                seed_count,
                len(candidates),
                batch_size,
                phase_batches,
                exploration_seed,
            )
        for batch_index, batch in enumerate(self._batched(candidates, batch_size), start=1):
            batch_count += 1
            if phase == "candidate":
                logger.info(
                    "plan generation tuning evaluating batch %s/%s: mode=%s batch_candidates=%s rss_mb=%s",
                    batch_index,
                    phase_batches,
                    mode,
                    len(batch),
                    round(self._current_rss_bytes() / 1024 / 1024, 1),
                )
            else:
                logger.info(
                    "plan generation tuning evaluating refinement batch %s/%s: mode=%s batch_candidates=%s rss_mb=%s",
                    batch_index,
                    phase_batches,
                    mode,
                    len(batch),
                    round(self._current_rss_bytes() / 1024 / 1024, 1),
                )
            self._memory_guard(stage=f"{mode}-{phase}-batch-{batch_count}-start")
            if explore_mode:
                batch_evaluations = [
                    self._evaluate_candidate_walk_forward(
                        config,
                        active_config,
                        search_records,
                        walk_forward_records,
                        walk_forward_service,
                        min_validation_resolved=min_validation_resolved,
                    )
                    for config in batch
                ]
            else:
                batch_evaluations = [
                    self._evaluate_candidate(
                        config, active_config, search_records, validation_records
                    )
                    for config in batch
                ]
            evaluations.extend(batch_evaluations)
            gc.collect()
            self._memory_guard(stage=f"{mode}-{phase}-batch-{batch_count}-end")
        return batch_count

    def promote_config_version(self, config_version_id: int) -> PlanGenerationTuningConfigVersion:
        gate_report = self._edge_validation_gate_report()
        version = self.repository.get_config_version(config_version_id)
        self.settings_mutations.set_plan_generation_active_config_version_id(version.id)
        self.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="config_promoted_manual",
                config_version_id=version.id,
                payload={
                    "version_label": version.version_label,
                    "edge_validation_gate": gate_report,
                },
            )
        )
        return version

    def promote_candidate(
        self, run_id: int, candidate_id: int
    ) -> PlanGenerationTuningConfigVersion:
        gate_report = self._edge_validation_gate_report()
        run = self.repository.get_run(run_id)
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.run_id != run.id:
            raise PlanGenerationTuningError(
                f"candidate {candidate_id} does not belong to run {run_id}"
            )
        manual_replay_check = self._manual_replay_candidate_promotion_check(run, candidate)
        if not candidate.promotion_eligible and not manual_replay_check.get("allowed"):
            raise PlanGenerationTuningError(f"candidate {candidate_id} is not promotion eligible: {manual_replay_check.get('reason') or 'candidate checks failed'}")
        version_label = f"run-{run.id}-candidate-{candidate.rank or candidate.id}"
        version = self.repository.create_config_version(
            PlanGenerationTuningConfigVersion(
                version_label=version_label,
                status="active",
                source="promoted_candidate",
                parent_config_version_id=run.baseline_config_version_id,
                source_run_id=run.id,
                source_candidate_id=candidate.id,
                config=candidate.config,
                parameter_schema_version=self.SCHEMA_VERSION,
            )
        )
        self.settings_mutations.set_plan_generation_active_config_version_id(version.id)
        self.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="config_promoted_manual_candidate",
                run_id=run.id,
                config_version_id=version.id,
                candidate_id=candidate.id,
                payload={
                    "version_label": version.version_label,
                    "candidate_rank": candidate.rank,
                    "run_id": run.id,
                    "edge_validation_gate": gate_report,
                    "manual_replay_promotion_check": manual_replay_check,
                },
            )
        )
        return version

    def _manual_replay_candidate_promotion_check(
        self, run: PlanGenerationTuningRun, candidate: PlanGenerationTuningCandidate
    ) -> dict[str, object]:
        if candidate.promotion_eligible:
            return {"allowed": True, "reason": "candidate_marked_promotion_eligible"}
        if run.summary.get("tuning_source_mode") != "point_in_time_replay":
            return {"allowed": False, "reason": "stored_plan_candidate_not_promotion_eligible"}
        aggregate = self.aggregate_replay_candidate_batch_results(run.id or 0)
        validation = aggregate.get("replay_walk_forward_validation") if isinstance(aggregate, dict) else None
        candidate_id = candidate.id or 0
        top_candidate_id = aggregate.get("replay_winner_candidate_id") if isinstance(aggregate, dict) else None
        result = next(
            (
                item
                for item in aggregate.get("results", [])
                if isinstance(item, dict) and int(item.get("candidate_id") or 0) == candidate_id
            ),
            None,
        ) if isinstance(aggregate, dict) else None
        tier_counts = result.get("tier_counts") if isinstance(result, dict) and isinstance(result.get("tier_counts"), dict) else {}
        if candidate_id != int(top_candidate_id or 0):
            return {"allowed": False, "reason": "candidate_is_not_replay_reranked_winner", "aggregate": aggregate}
        if int(tier_counts.get("tier_a", 0) or 0) <= 0:
            return {"allowed": False, "reason": "candidate_missing_tier_a_replay_evidence", "aggregate": aggregate}
        quality_reasons = self._replay_evidence_quality_rejection_reasons(result or {}, min_validation_resolved=1)
        if quality_reasons:
            return {"allowed": False, "reason": quality_reasons[0], "aggregate": aggregate}
        if not isinstance(validation, dict) or not validation.get("passed"):
            return {"allowed": False, "reason": "candidate_failed_replay_walk_forward_baseline_check", "aggregate": aggregate}
        return {"allowed": True, "reason": "replay_candidate_passed_manual_checks", "aggregate": aggregate}

    @staticmethod
    def _replay_evidence_quality_rejection_reasons(source: dict[str, object], *, min_validation_resolved: int) -> list[str]:
        population = source.get("outcome_population") if isinstance(source.get("outcome_population"), dict) else None
        return replay_outcome_population_rejection_reasons(
            population,
            min_execution_rows=min_validation_resolved,
            phantom_reason="replay_winner_phantom_dominated_without_execution_sample",
            empty_reason="replay_winner_empty_outcome_population",
        )

    def _edge_validation_gate_report(
        self, *, walk_forward_validation: object | None = None
    ) -> dict[str, object]:
        return (
            PolicyTrustReportService(
                self.outcomes,
                policy_service=TradeDecisionPolicyService(self.session),
            )
            .summarize_active_policy(
                walk_forward_validation=walk_forward_validation,
                degraded_input_summary=None,
                risk_state=None,
            )
            .edge_validation_gate.to_dict()
        )

    def _resolve_active_config_version(self) -> PlanGenerationTuningConfigVersion:
        baseline = self.ensure_baseline_config_version()
        active_id = self._active_config_version_id()
        if active_id is None:
            return baseline
        try:
            return self.repository.get_config_version(active_id)
        except ValueError:
            self.settings_mutations.set_plan_generation_active_config_version_id(baseline.id)
            return baseline

    def _active_config_version_id(self) -> int | None:
        value = self.settings_domains.strategy_settings().plan_generation_tuning.get(
            "active_config_version_id"
        )
        return value if isinstance(value, int) else None

    def _eligible_records(
        self, *, ticker: str | None, setup_family: str | None, limit: int | None
    ) -> list[EligibleTuningRecord]:
        self._refresh_eligible_record_cache_if_needed(ticker=ticker, limit=limit)
        return self._cached_eligible_records(ticker=ticker, setup_family=setup_family, limit=limit)

    def _refresh_eligible_record_cache_if_needed(
        self, *, ticker: str | None, limit: int | None
    ) -> None:
        cached_count = int(
            self.session.scalar(select(func.count()).select_from(PlanGenerationTuningEligibleRecordRecord))
            or 0
        )
        latest_source_update = self._latest_eligible_source_update()
        source_updated_at = self._normalize_datetime(latest_source_update)
        stale_version_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(PlanGenerationTuningEligibleRecordRecord)
                .where(
                    PlanGenerationTuningEligibleRecordRecord.cache_version
                    != self.ELIGIBLE_RECORD_CACHE_VERSION
                )
            )
            or 0
        )
        latest_cache_update = self.session.scalar(
            select(func.max(PlanGenerationTuningEligibleRecordRecord.source_updated_at))
            .where(
                PlanGenerationTuningEligibleRecordRecord.cache_version
                == self.ELIGIBLE_RECORD_CACHE_VERSION
            )
        )
        if cached_count > 0 and stale_version_count == 0 and latest_cache_update is not None:
            cache_updated_at = self._normalize_datetime(latest_cache_update)
            if source_updated_at is None or cache_updated_at >= source_updated_at:
                return
        logger.info("refreshing persisted plan-generation tuning eligible records")
        records = self._build_eligible_records_from_sources(ticker=None, limit=None)
        self.session.query(PlanGenerationTuningEligibleRecordRecord).delete(synchronize_session=False)
        cache_watermark = source_updated_at or datetime.now(timezone.utc)
        for record in records:
            self._upsert_cached_eligible_record(record, source_updated_at=cache_watermark)
        self.session.commit()

    def _latest_eligible_source_update(self) -> datetime | None:
        values = [
            self.session.scalar(select(func.max(RecommendationPlanRecord.updated_at))),
            self.session.scalar(select(func.max(RecommendationOutcomeRecord.updated_at))),
            self.session.scalar(select(func.max(BrokerPositionRecord.updated_at))),
            self.session.scalar(select(func.max(RecommendationDecisionSampleRecord.updated_at))),
        ]
        normalized = [self._normalize_datetime(value) for value in values if value is not None]
        return max(normalized) if normalized else None

    def _cached_eligible_records(
        self, *, ticker: str | None, setup_family: str | None, limit: int | None
    ) -> list[EligibleTuningRecord]:
        query = select(PlanGenerationTuningEligibleRecordRecord)
        if ticker:
            query = query.where(PlanGenerationTuningEligibleRecordRecord.ticker == ticker.upper())
        normalized_setup_family = str(setup_family or "").strip().lower() or None
        if normalized_setup_family:
            query = query.where(
                PlanGenerationTuningEligibleRecordRecord.setup_family == normalized_setup_family
            )
        query = query.order_by(PlanGenerationTuningEligibleRecordRecord.computed_at.desc())
        if limit is not None:
            query = query.limit(max(1, int(limit)))
        rows = list(self.session.scalars(query).all())
        rows.sort(key=lambda row: row.computed_at)
        return [self._cached_eligible_record_to_model(row) for row in rows]

    def _cached_eligible_record_to_model(
        self, row: PlanGenerationTuningEligibleRecordRecord
    ) -> EligibleTuningRecord:
        signal_breakdown = loads_json_object(row.signal_breakdown_json)
        return EligibleTuningRecord(
            plan=TuningPlanSnapshot(
                id=int(row.plan_id),
                computed_at=self._normalize_datetime(row.computed_at),
                action=row.action,
                confidence_percent=float(row.confidence_percent),
                entry_price_low=row.entry_price_low,
                entry_price_high=row.entry_price_high,
                stop_loss=row.stop_loss,
                take_profit=row.take_profit,
                signal_breakdown=signal_breakdown,
                ticker=row.ticker,
            ),
            outcome=TuningOutcomeSnapshot(
                max_favorable_excursion=row.max_favorable_excursion,
                max_adverse_excursion=row.max_adverse_excursion,
                horizon_return_5d=row.horizon_return_5d,
            ),
            sample=None,
            setup_family=row.setup_family,
            context_bias=row.context_bias,
        )

    def _upsert_cached_eligible_record(
        self, record: EligibleTuningRecord, *, source_updated_at: datetime
    ) -> None:
        plan = record.plan
        outcome = record.outcome
        plan_id = int(plan.id or 0)
        if plan_id <= 0:
            return
        row = self.session.scalar(
            select(PlanGenerationTuningEligibleRecordRecord).where(
                PlanGenerationTuningEligibleRecordRecord.plan_id == plan_id
            )
        )
        if row is None:
            row = PlanGenerationTuningEligibleRecordRecord(plan_id=plan_id)
            self.session.add(row)
        row.ticker = str(getattr(plan, "ticker", "") or "")
        row.action = str(plan.action or "")
        row.computed_at = self._normalize_datetime(plan.computed_at) or datetime.now(timezone.utc)
        row.setup_family = record.setup_family
        row.context_bias = record.context_bias
        row.confidence_percent = float(plan.confidence_percent)
        row.entry_price_low = plan.entry_price_low
        row.entry_price_high = plan.entry_price_high
        row.stop_loss = plan.stop_loss
        row.take_profit = plan.take_profit
        row.signal_breakdown_json = json.dumps(plan.signal_breakdown or {}, sort_keys=True)
        row.max_favorable_excursion = outcome.max_favorable_excursion
        row.max_adverse_excursion = outcome.max_adverse_excursion
        row.horizon_return_5d = outcome.horizon_return_5d
        row.cache_version = self.ELIGIBLE_RECORD_CACHE_VERSION
        row.source_updated_at = source_updated_at

    def _replay_eligible_records(
        self, *, ticker: str | None, setup_family: str | None, limit: int | None
    ) -> list[EligibleTuningRecord]:
        query = (
            select(ReplayEligibilityRecord, RecommendationPlanRecord, ReplayPlanOutcomeRecord)
            .join(
                RecommendationPlanRecord,
                RecommendationPlanRecord.id == ReplayEligibilityRecord.recommendation_plan_id,
            )
            .join(
                ReplayPlanOutcomeRecord,
                ReplayPlanOutcomeRecord.id == ReplayEligibilityRecord.replay_plan_outcome_id,
            )
            .where(ReplayEligibilityRecord.eligible_for_tuning.is_(True))
            .where(ReplayEligibilityRecord.tier.in_(["tier_a", "tier_b"]))
        )
        if ticker:
            query = query.where(ReplayEligibilityRecord.ticker == ticker.upper())
        query = query.order_by(RecommendationPlanRecord.computed_at.desc())
        if limit is not None:
            query = query.limit(max(1, int(limit)))
        rows = self.session.execute(query).all()
        records: list[EligibleTuningRecord] = []
        normalized_setup_family = setup_family.strip().lower() if setup_family else None
        current_versions = self._current_replay_artifact_versions()
        for eligibility_row, plan_row, outcome_row in rows:
            diagnostics = loads_json_object(eligibility_row.diagnostics_json)
            if not self._replay_artifact_versions_current(diagnostics, current_versions):
                continue
            signal_breakdown = loads_json_object(plan_row.signal_breakdown_json)
            outcome_payload = loads_json_object(outcome_row.outcome_json)
            row_setup_family = self._setup_family_from_payloads(signal_breakdown, outcome_payload)
            if normalized_setup_family and row_setup_family.lower() != normalized_setup_family:
                continue
            records.append(
                EligibleTuningRecord(
                    plan=TuningPlanSnapshot(
                        id=int(plan_row.id or 0),
                        computed_at=self._normalize_datetime(plan_row.computed_at),
                        action=plan_row.action,
                        confidence_percent=float(plan_row.confidence_percent),
                        entry_price_low=plan_row.entry_price_low,
                        entry_price_high=plan_row.entry_price_high,
                        stop_loss=plan_row.stop_loss,
                        take_profit=plan_row.take_profit,
                        signal_breakdown={
                            key: signal_breakdown[key]
                            for key in ("intended_action", "cheap_scan_volatility_score")
                            if key in signal_breakdown
                        },
                        ticker=plan_row.ticker,
                    ),
                    outcome=TuningOutcomeSnapshot(
                        max_favorable_excursion=self._float_or_none(
                            outcome_payload.get("max_favorable_excursion")
                        ),
                        max_adverse_excursion=self._float_or_none(
                            outcome_payload.get("max_adverse_excursion")
                        ),
                        horizon_return_5d=self._float_or_none(
                            outcome_payload.get("horizon_return_5d")
                        ),
                    ),
                    sample=None,
                    setup_family=row_setup_family,
                    context_bias=self._context_bias(signal_breakdown),
                )
            )
        records.sort(key=lambda item: item.plan.computed_at or datetime.min.replace(tzinfo=timezone.utc))
        return records

    @classmethod
    def _current_replay_artifact_versions(cls) -> dict[str, str]:
        return {
            "code_version": os.environ.get("GIT_COMMIT") or os.environ.get("SOURCE_VERSION") or "unknown",
            "settings_hash": stable_hash({"weights_file_path": settings.weights_file_path}),
        }

    @staticmethod
    def _replay_artifact_versions_current(
        diagnostics: dict[str, object], current_versions: dict[str, str]
    ) -> bool:
        versions = diagnostics.get("artifact_versions")
        if not isinstance(versions, dict):
            return False
        for key in ("code_version", "settings_hash"):
            value = versions.get(key)
            if value is None or str(value) != str(current_versions.get(key)):
                return False
        return True

    @staticmethod
    def _setup_family_from_payloads(
        signal_breakdown: dict[str, object], outcome_payload: dict[str, object]
    ) -> str:
        for source in (signal_breakdown, outcome_payload):
            value = source.get("setup_family")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "uncategorized"

    @staticmethod
    def _context_bias(signal_breakdown: dict[str, object]) -> str | None:
        transmission = signal_breakdown.get("transmission_summary")
        if isinstance(transmission, dict):
            value = transmission.get("context_bias")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_eligible_records_from_sources(
        self, *, ticker: str | None, limit: int | None
    ) -> list[EligibleTuningRecord]:
        normalized_limit = None if limit is None else max(1, int(limit))
        eligible: list[EligibleTuningRecord] = []
        offset = 0
        while True:
            batch_limit = self.ELIGIBLE_RECORD_BATCH_SIZE
            if normalized_limit is not None:
                remaining = normalized_limit - offset
                if remaining <= 0:
                    break
                batch_limit = min(batch_limit, remaining)
            plans = self.plans.list_plans(
                ticker=ticker, action=None, limit=batch_limit, offset=offset
            )
            if not plans:
                break
            plan_ids = [plan.id for plan in plans if plan.id is not None]
            outcome_map = self.outcomes.get_outcomes_by_plan_ids(plan_ids)
            sample_map = self.samples.get_samples_by_plan_ids(plan_ids)
            for plan in plans:
                if plan.id is None:
                    continue
                outcome = outcome_map.get(plan.id)
                if outcome is None:
                    continue
                sample = sample_map.get(plan.id)
                features = self.reliability_features.build(plan, outcome, sample)
                if features is None:
                    continue
                eligible.append(
                    self._compact_eligible_record(
                        plan=plan,
                        outcome=outcome,
                        sample=sample,
                        setup_family=features.setup_family,
                        context_bias=features.context_bias,
                    )
                )
            offset += len(plans)
            self.session.expunge_all()
            gc.collect()
            if len(plans) < batch_limit:
                break
        eligible.sort(key=lambda item: item.plan.computed_at)
        return eligible

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _compact_eligible_record(
        *,
        plan: RecommendationPlan,
        outcome: RecommendationPlanOutcome,
        sample: RecommendationDecisionSample | None,
        setup_family: str,
        context_bias: str | None,
    ) -> EligibleTuningRecord:
        signal_breakdown = PlanGenerationTuningService._plan_signal_breakdown(plan)
        compact_signal_breakdown = {
            key: signal_breakdown[key]
            for key in ("intended_action", "cheap_scan_volatility_score")
            if key in signal_breakdown
        }
        return EligibleTuningRecord(
            plan=TuningPlanSnapshot(
                id=int(plan.id or 0),
                computed_at=plan.computed_at,
                action=plan.action,
                confidence_percent=float(plan.confidence_percent),
                entry_price_low=float(plan.entry_price_low)
                if plan.entry_price_low is not None
                else None,
                entry_price_high=float(plan.entry_price_high)
                if plan.entry_price_high is not None
                else None,
                stop_loss=float(plan.stop_loss) if plan.stop_loss is not None else None,
                take_profit=float(plan.take_profit) if plan.take_profit is not None else None,
                signal_breakdown=compact_signal_breakdown,
                ticker=plan.ticker,
            ),
            outcome=TuningOutcomeSnapshot(
                max_favorable_excursion=float(outcome.max_favorable_excursion)
                if outcome.max_favorable_excursion is not None
                else None,
                max_adverse_excursion=float(outcome.max_adverse_excursion)
                if outcome.max_adverse_excursion is not None
                else None,
                horizon_return_5d=float(outcome.horizon_return_5d)
                if outcome.horizon_return_5d is not None
                else None,
            ),
            sample=None,
            setup_family=setup_family,
            context_bias=context_bias,
        )

    @staticmethod
    def _split_records(
        records: list[EligibleTuningRecord], *, min_validation: int
    ) -> tuple[list[EligibleTuningRecord], list[EligibleTuningRecord]]:
        if len(records) <= min_validation:
            return records, []
        validation_count = max(min_validation, int(math.ceil(len(records) * 0.2)))
        validation_count = min(validation_count, max(1, len(records) - 1))
        return records[:-validation_count], records[-validation_count:]

    def _evaluate_candidate_walk_forward(
        self,
        config: dict[str, float],
        baseline_config: dict[str, float],
        search_records: list[EligibleTuningRecord],
        records: list[EligibleTuningRecord],
        walk_forward_service: PlanGenerationWalkForwardService,
        *,
        min_validation_resolved: int,
    ) -> CandidateEvaluation:
        search_actionable_count, search_win_count, search_expected_value, search_ambiguous_count = (
            self._score_records(search_records, config)
        )
        history_span_days = self._history_span_days(records)
        summary = walk_forward_service.summarize_records(
            records=records,
            candidate_config=config,
            baseline_config=baseline_config,
            candidate_label="candidate",
            baseline_label="baseline",
            lookback_days=history_span_days,
            validation_days=90,
            step_days=30,
            min_validation_resolved=min_validation_resolved,
        )
        changed_keys = [
            key
            for key, value in config.items()
            if round(float(value), 4) != round(float(baseline_config.get(key, value)), 4)
        ]
        validation_actionable_count = int(summary.qualified_slices)
        validation_win_count = int(summary.candidate_wins)
        validation_expected_value = float(summary.average_expected_value_delta or 0.0)
        validation_ambiguous_count = max(0, int(summary.total_slices) - validation_actionable_count)
        return CandidateEvaluation(
            config=config,
            changed_keys=changed_keys,
            search_actionable_count=search_actionable_count,
            search_win_count=search_win_count,
            search_expected_value=search_expected_value,
            search_ambiguous_count=search_ambiguous_count,
            validation_actionable_count=validation_actionable_count,
            validation_win_count=validation_win_count,
            validation_expected_value=validation_expected_value,
            validation_ambiguous_count=validation_ambiguous_count,
            validation_slice_count=int(summary.total_slices),
            validation_baseline_win_count=int(summary.baseline_wins),
            validation_ties=int(summary.ties),
            validation_average_win_rate_delta=summary.average_win_rate_delta,
            validation_average_expected_value_delta=summary.average_expected_value_delta,
        )

    def _candidate_configs(
        self, active_config: dict[str, float], *, mode: str
    ) -> list[dict[str, float]]:
        mode_profile = self._mode_profile(mode)
        step_counts = mode_profile["step_counts"]
        explore_mode = bool(mode_profile["explore_like"])
        configs: list[dict[str, float]] = [dict(active_config)]
        campaign_keys = (
            (
                "entry_calibration",
                (
                    "global.entry_band_risk_fraction",
                    "setup_family.entry_band_multiplier",
                ),
            ),
            ("selectivity", ("global.actionable_confidence_floor_percent",)),
            (
                "risk_protection",
                (
                    "global.headwind_stop_multiplier",
                    "global.volatility_stop_multiplier",
                    "setup_family.breakout.stop_distance_multiplier",
                    "setup_family.mean_reversion.stop_distance_multiplier",
                ),
            ),
            (
                "reward_expansion",
                (
                    "setup_family.breakout.take_profit_distance_multiplier",
                    "setup_family.mean_reversion.take_profit_distance_multiplier",
                    "setup_family.catalyst_follow_through.take_profit_distance_multiplier",
                    "setup_family.macro_beneficiary_loser.take_profit_distance_multiplier",
                ),
            ),
        )
        for _, keys in campaign_keys:
            for key in keys:
                definition = PARAMETER_BY_KEY[key]
                base_value = active_config.get(key, definition.default)
                for step_count in step_counts:
                    mutated = dict(active_config)
                    candidate = base_value + (definition.step * step_count)
                    mutated[key] = self._campaign_bounded_value(
                        definition, candidate, explore_mode=explore_mode
                    )
                    configs.append(mutated)
        deduped: list[dict[str, float]] = []
        fingerprints: set[tuple[tuple[str, float], ...]] = set()
        max_candidates = mode_profile["max_candidates"]
        for config in configs:
            normalized = normalize_plan_generation_tuning_config(config)
            fingerprint = tuple(sorted(normalized.items()))
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            deduped.append(normalized)
            if len(deduped) >= max_candidates:
                break
        return deduped

    def _refinement_configs(
        self,
        initial_evaluations: list[CandidateEvaluation],
        baseline_eval: CandidateEvaluation,
        active_config: dict[str, float],
        *,
        mode: str,
        max_candidates: int,
    ) -> list[dict[str, float]]:
        remaining_budget = max(0, max_candidates - len(initial_evaluations))
        if remaining_budget <= 0:
            return []
        broad_budget = max(0, remaining_budget - 1)
        targeted_budget = remaining_budget - broad_budget
        mode_profile = self._mode_profile(mode)
        explore_mode = bool(mode_profile["explore_like"])
        seeds = [item for item in initial_evaluations if item.changed_keys][:2]
        seen = {
            tuple(sorted(normalize_plan_generation_tuning_config(item.config).items()))
            for item in initial_evaluations
        }
        refined: list[dict[str, float]] = []

        def add_refinement(
            source: CandidateEvaluation, key: str, *, step_scale: float, limit: int
        ) -> None:
            nonlocal refined
            if limit <= 0:
                return
            definition = PARAMETER_BY_KEY[key]
            seed_value = float(source.config[key])
            baseline_value = float(active_config.get(key, definition.default))
            direction = 1.0 if seed_value >= baseline_value else -1.0
            for candidate_value in (
                seed_value + (direction * definition.step * step_scale),
                seed_value - (direction * definition.step * step_scale),
            ):
                if len(refined) >= limit:
                    return
                mutated = dict(source.config)
                mutated[key] = self._campaign_bounded_value(
                    definition, candidate_value, explore_mode=explore_mode
                )
                normalized = normalize_plan_generation_tuning_config(mutated)
                fingerprint = tuple(sorted(normalized.items()))
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                refined.append(normalized)
                if len(refined) >= remaining_budget:
                    return

        for seed in seeds:
            for key in seed.changed_keys:
                add_refinement(seed, key, step_scale=0.5, limit=broad_budget)
                if len(refined) >= broad_budget:
                    break
            if len(refined) >= broad_budget:
                break

        if targeted_budget > 0 and seeds and self._candidate_compare(seeds[0], baseline_eval) < 0:
            top_seed = seeds[0]
            target_key = self._refinement_target_key(top_seed, active_config)
            if target_key is not None:
                add_refinement(top_seed, target_key, step_scale=0.25, limit=remaining_budget)
        return refined

    @staticmethod
    def _refinement_target_key(
        source: CandidateEvaluation, active_config: dict[str, float]
    ) -> str | None:
        if not source.changed_keys:
            return None
        return max(
            source.changed_keys,
            key=lambda key: abs(
                float(source.config[key]) - float(active_config.get(key, source.config[key]))
            ),
        )

    def _exploration_seed(
        self, *, active_config: dict[str, float], records: list[EligibleTuningRecord], mode: str
    ) -> int:
        fingerprint_source = {
            "mode": mode,
            "active_config": active_config,
            "eligible_count": len(records),
            "first_computed_at": records[0].plan.computed_at.isoformat()
            if records and records[0].plan.computed_at
            else None,
            "last_computed_at": records[-1].plan.computed_at.isoformat()
            if records and records[-1].plan.computed_at
            else None,
        }
        payload = repr(sorted(fingerprint_source.items())).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return int(digest[:16], 16)

    @staticmethod
    def _campaign_bounded_value(definition, value: float, *, explore_mode: bool) -> float:
        lower = definition.exploration_min if explore_mode else definition.minimum
        upper = definition.exploration_max if explore_mode else definition.maximum
        return round(max(lower, min(upper, value)), 4)

    @staticmethod
    def _mode_profile(mode: str) -> dict[str, object]:
        normalized = mode.strip().lower()
        if normalized in {"wide_point_in_time_replay", "wide_replay"}:
            return {
                "name": "wide_point_in_time_replay",
                "explore_like": True,
                "replay_like": True,
                "step_counts": (-3, -2, -1, 1, 2, 3),
                "max_candidates": 67,
                "batch_size": 16,
            }
        if normalized in {"point_in_time_replay", "replay", "scheduled", "auto"}:
            return {
                "name": "point_in_time_replay",
                "explore_like": True,
                "replay_like": True,
                "step_counts": (-2, -1, 1, 2),
                "max_candidates": 45,
                "batch_size": 12,
            }
        if normalized in {"wide", "expensive", "deep", "deep_research"}:
            return {
                "name": "wide",
                "explore_like": True,
                "replay_like": False,
                "step_counts": (-3, -2, -1, 1, 2, 3),
                "max_candidates": 67,
                "batch_size": 16,
            }
        if normalized in {"explore", "exploration", "research"}:
            return {
                "name": "explore",
                "explore_like": True,
                "replay_like": False,
                "step_counts": (-2, -1, 1, 2),
                "max_candidates": 45,
                "batch_size": 12,
            }
        return {
            "name": "stored_plan_rescore" if normalized == "stored_plan_rescore" else "manual",
            "explore_like": False,
            "replay_like": False,
            "step_counts": (-1, 1),
            "max_candidates": 25,
            "batch_size": 10,
        }

    @staticmethod
    def _history_span_days(records: list[EligibleTuningRecord]) -> int:
        if len(records) < 2:
            return 30
        start = records[0].plan.computed_at
        end = records[-1].plan.computed_at
        if start is None or end is None:
            return 365
        span = abs((end - start).days)
        return max(30, span or 30)

    def _evaluate_candidate(
        self,
        config: dict[str, float],
        baseline_config: dict[str, float],
        search_records: list[EligibleTuningRecord],
        validation_records: list[EligibleTuningRecord],
    ) -> CandidateEvaluation:
        changed_keys = [
            key
            for key, value in config.items()
            if round(float(value), 4) != round(float(baseline_config.get(key, value)), 4)
        ]
        search_actionable_count, search_win_count, search_expected_value, search_ambiguous_count = (
            self._score_records(search_records, config)
        )
        (
            validation_actionable_count,
            validation_win_count,
            validation_expected_value,
            validation_ambiguous_count,
        ) = self._score_records(validation_records, config)
        return CandidateEvaluation(
            config=config,
            changed_keys=changed_keys,
            search_actionable_count=search_actionable_count,
            search_win_count=search_win_count,
            search_expected_value=search_expected_value,
            search_ambiguous_count=search_ambiguous_count,
            validation_actionable_count=validation_actionable_count,
            validation_win_count=validation_win_count,
            validation_expected_value=validation_expected_value,
            validation_ambiguous_count=validation_ambiguous_count,
        )

    def _score_records(
        self, records: list[EligibleTuningRecord], config: dict[str, float]
    ) -> tuple[int, int, float, int]:
        actionable_count = 0
        win_count = 0
        expected_value = 0.0
        ambiguous_count = 0
        for record in records:
            candidate = self._candidate_resolution(record, config)
            if candidate is None:
                ambiguous_count += 1
                continue
            candidate_outcome, reward_pct, risk_pct = candidate
            actionable_count += 1
            if candidate_outcome == TradeOutcome.WIN.value:
                win_count += 1
                expected_value += reward_pct
            else:
                expected_value -= risk_pct
        return actionable_count, win_count, round(expected_value, 4), ambiguous_count

    def _candidate_resolution(
        self, record: EligibleTuningRecord, config: dict[str, float]
    ) -> tuple[str, float, float] | None:
        entry = self._entry_reference(record.plan)
        if (
            entry is None
            or entry <= 0
            or record.plan.stop_loss is None
            or record.plan.take_profit is None
        ):
            return None

        signal_breakdown = self._plan_signal_breakdown(record.plan)
        intended_action = str(signal_breakdown.get("intended_action") or "").strip().lower() or None
        effective_action = (
            intended_action
            if record.plan.action in {"no_action", "watchlist"}
            and intended_action in {"long", "short"}
            else record.plan.action
        )

        if effective_action not in {"long", "short"}:
            return None

        confidence_floor = float(
            config.get("global.actionable_confidence_floor_percent", 60.0) or 60.0
        )
        if float(record.plan.confidence_percent) < confidence_floor:
            return None

        volatility_score = signal_breakdown.get("cheap_scan_volatility_score")
        entry_low, entry_high, stop_loss, take_profit = family_adjusted_trade_levels(
            entry_price=entry,
            stop_loss=float(record.plan.stop_loss),
            take_profit=float(record.plan.take_profit),
            setup_family=record.setup_family,
            action=effective_action,
            transmission_context_bias=record.context_bias,
            volatility_score=float(volatility_score)
            if isinstance(volatility_score, (int, float))
            else None,
            tuning_config=config,
        )
        candidate_entry = (entry_low + entry_high) / 2.0
        if candidate_entry <= 0:
            return None
        risk_pct = abs((candidate_entry - stop_loss) / candidate_entry) * 100.0
        reward_pct = abs((take_profit - candidate_entry) / candidate_entry) * 100.0
        if risk_pct <= 0 or reward_pct <= 0:
            return None
        mfe = float(record.outcome.max_favorable_excursion or 0.0)
        mae = float(record.outcome.max_adverse_excursion or 0.0)
        stop_reached = mae >= risk_pct
        take_reached = mfe >= reward_pct
        if stop_reached and take_reached:
            return None
        if not stop_reached and not take_reached:
            # fall back to horizon return sign only when threshold evidence is absent
            horizon_return = record.outcome.horizon_return_5d
            if horizon_return is None:
                return None
            return ("win" if float(horizon_return) > 0 else "loss"), reward_pct, risk_pct
        return ("win" if take_reached else "loss"), reward_pct, risk_pct

    @staticmethod
    def _plan_signal_breakdown(plan: RecommendationPlan) -> dict[str, object]:
        signal_breakdown = plan.signal_breakdown
        if isinstance(signal_breakdown, dict):
            return signal_breakdown
        model_dump = getattr(signal_breakdown, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        if hasattr(signal_breakdown, "dict") and callable(getattr(signal_breakdown, "dict")):
            dumped = signal_breakdown.dict()  # type: ignore[call-arg]
            if isinstance(dumped, dict):
                return dumped
        return {}

    @staticmethod
    def _entry_reference(plan: RecommendationPlan) -> float | None:
        if plan.entry_price_low is not None and plan.entry_price_high is not None:
            return (float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0
        if plan.entry_price_low is not None:
            return float(plan.entry_price_low)
        if plan.entry_price_high is not None:
            return float(plan.entry_price_high)
        return None

    @staticmethod
    def _batched(items: list[dict[str, float]], batch_size: int):
        if batch_size <= 0:
            batch_size = 1
        iterator = iter(items)
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                return
            yield batch

    @classmethod
    def _current_rss_bytes(cls) -> int:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return int(rss)
        return int(rss) * 1024

    @classmethod
    def _memory_limit_bytes(cls) -> int:
        cgroup_paths = (
            "/sys/fs/cgroup/memory.max",
            "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        )
        for path in cgroup_paths:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    raw = handle.read().strip()
            except OSError:
                continue
            if not raw or raw == "max":
                continue
            try:
                limit = int(raw)
            except ValueError:
                continue
            if limit <= 0 or limit >= 1 << 60:
                continue
            return limit
        try:
            total = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
        except (AttributeError, ValueError, OSError):
            return cls.MEMORY_GUARD_FALLBACK_BYTES
        return max(cls.MEMORY_GUARD_FALLBACK_BYTES, int(total * cls.MEMORY_GUARD_FRACTION))

    @classmethod
    def _memory_guard(cls, *, stage: str) -> None:
        usage = cls._current_rss_bytes()
        limit = cls._memory_limit_bytes()
        threshold = int(limit * cls.MEMORY_GUARD_FRACTION)
        if usage >= threshold:
            logger.warning(
                "plan generation tuning memory guard tripped: stage=%s rss_mb=%s guard_mb=%s",
                stage,
                round(usage / 1024 / 1024, 1),
                round(threshold / 1024 / 1024, 1),
            )
            raise PlanGenerationTuningError(
                f"plan generation tuning aborted at {stage}: memory usage {usage // 1024 // 1024}MB exceeded guard {threshold // 1024 // 1024}MB"
            )

    @classmethod
    def _candidate_compare(cls, left: CandidateEvaluation, right: CandidateEvaluation) -> int:
        win_rate_delta = left.validation_win_rate - right.validation_win_rate
        if abs(win_rate_delta) > cls.WIN_RATE_TIE_TOLERANCE:
            return -1 if win_rate_delta > 0 else 1

        win_count_delta = left.validation_win_count - right.validation_win_count
        if abs(win_count_delta) > cls.WIN_COUNT_TIE_TOLERANCE:
            return -1 if win_count_delta > 0 else 1

        expected_value_delta = left.validation_expected_value - right.validation_expected_value
        if abs(expected_value_delta) > cls.EXPECTED_VALUE_TIE_TOLERANCE:
            return -1 if expected_value_delta > 0 else 1

        changed_key_delta = len(left.changed_keys) - len(right.changed_keys)
        if changed_key_delta != 0:
            return -1 if changed_key_delta < 0 else 1

        ambiguous_delta = left.validation_ambiguous_count - right.validation_ambiguous_count
        if ambiguous_delta != 0:
            return -1 if ambiguous_delta < 0 else 1
        return 0

    @staticmethod
    def _candidate_sort_key(item: CandidateEvaluation) -> tuple[float, int, float, float, int]:
        return (
            round(item.validation_win_rate, 8),
            item.validation_win_count,
            round(item.validation_expected_value, 8),
            -float(len(item.changed_keys)),
            -float(item.validation_ambiguous_count),
        )

    @staticmethod
    def _candidate_campaign_name(changed_keys: list[str]) -> str:
        changed = set(changed_keys)
        if not changed:
            return "baseline"
        if changed.issubset(
            {"global.entry_band_risk_fraction", "setup_family.entry_band_multiplier"}
        ):
            return "entry_calibration"
        if changed.issubset({"global.actionable_confidence_floor_percent"}):
            return "selectivity"
        if changed.issubset(
            {
                "global.headwind_stop_multiplier",
                "global.volatility_stop_multiplier",
                "setup_family.breakout.stop_distance_multiplier",
                "setup_family.mean_reversion.stop_distance_multiplier",
            }
        ):
            return "risk_protection"
        if changed.issubset(
            {
                "setup_family.breakout.take_profit_distance_multiplier",
                "setup_family.mean_reversion.take_profit_distance_multiplier",
                "setup_family.catalyst_follow_through.take_profit_distance_multiplier",
                "setup_family.macro_beneficiary_loser.take_profit_distance_multiplier",
            }
        ):
            return "reward_expansion"
        return "other"

    @staticmethod
    def _candidate_payload(item: CandidateEvaluation) -> dict[str, object]:
        return {
            "config": item.config,
            "changed_keys": item.changed_keys,
            "campaign": PlanGenerationTuningService._candidate_campaign_name(item.changed_keys),
            **candidate_validation_depth(item.changed_keys),
            "search_actionable_count": item.search_actionable_count,
            "search_win_count": item.search_win_count,
            "search_win_rate_percent": round(item.search_win_rate * 100.0, 2),
            "search_expected_value": round(item.search_expected_value, 4),
            "search_ambiguous_count": item.search_ambiguous_count,
            "validation_actionable_count": item.validation_actionable_count,
            "validation_win_count": item.validation_win_count,
            "validation_win_rate_percent": round(item.validation_win_rate * 100.0, 2),
            "validation_expected_value": round(item.validation_expected_value, 4),
            "validation_ambiguous_count": item.validation_ambiguous_count,
            "validation_slice_count": item.validation_slice_count,
            "validation_baseline_win_count": item.validation_baseline_win_count,
            "validation_ties": item.validation_ties,
            "validation_average_win_rate_delta": item.validation_average_win_rate_delta,
            "validation_average_expected_value_delta": item.validation_average_expected_value_delta,
        }

    @classmethod
    def _promotion_eligible(
        cls,
        candidate: CandidateEvaluation,
        baseline: CandidateEvaluation,
        *,
        min_validation_resolved: int,
    ) -> bool:
        if candidate.validation_actionable_count < min_validation_resolved:
            return False
        win_rate_delta = candidate.validation_win_rate - baseline.validation_win_rate
        if win_rate_delta < -cls.WIN_RATE_TIE_TOLERANCE:
            return False
        win_count_delta = candidate.validation_win_count - baseline.validation_win_count
        if (
            abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE
            and win_count_delta < -cls.WIN_COUNT_TIE_TOLERANCE
        ):
            return False
        expected_value_delta = (
            candidate.validation_expected_value - baseline.validation_expected_value
        )
        if (
            abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE
            and abs(win_count_delta) <= cls.WIN_COUNT_TIE_TOLERANCE
            and expected_value_delta < -cls.EXPECTED_VALUE_TIE_TOLERANCE
        ):
            return False
        return True

    @classmethod
    def _rejection_reasons(
        cls,
        candidate: CandidateEvaluation,
        baseline: CandidateEvaluation,
        *,
        min_validation_resolved: int,
    ) -> list[str]:
        reasons: list[str] = []
        if candidate.validation_actionable_count < min_validation_resolved:
            reasons.append("insufficient_validation_actionable_records")
        win_rate_delta = candidate.validation_win_rate - baseline.validation_win_rate
        if win_rate_delta < -cls.WIN_RATE_TIE_TOLERANCE:
            reasons.append("validation_win_rate_below_baseline")
        win_count_delta = candidate.validation_win_count - baseline.validation_win_count
        if (
            abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE
            and win_count_delta < -cls.WIN_COUNT_TIE_TOLERANCE
        ):
            reasons.append("validation_win_count_below_baseline")
        expected_value_delta = (
            candidate.validation_expected_value - baseline.validation_expected_value
        )
        if (
            abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE
            and abs(win_count_delta) <= cls.WIN_COUNT_TIE_TOLERANCE
            and expected_value_delta < -cls.EXPECTED_VALUE_TIE_TOLERANCE
        ):
            reasons.append("validation_expected_value_below_baseline")
        return reasons
