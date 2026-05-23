from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cmp_to_key
from itertools import islice
import gc
import hashlib
import logging
import math
import os
import resource
import sys

from sqlalchemy.orm import Session

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
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.edge_validation_gate import EdgeValidationGateService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_reliability_features import PlanReliabilityFeatureBuilder
from trade_proposer_app.services.plan_generation_tuning_parameters import PARAMETER_BY_KEY, exploration_campaigns, normalize_plan_generation_tuning_config, parameter_definitions
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.settings_mutations import SettingsMutationService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
from trade_proposer_app.services.trade_policy_evaluation import TradePolicyEvaluationService


logger = logging.getLogger(__name__)


class PlanGenerationTuningError(Exception):
    pass


@dataclass(slots=True)
class EligibleTuningRecord:
    plan: RecommendationPlan
    outcome: RecommendationPlanOutcome
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
    SCHEMA_VERSION = "v1"
    WIN_RATE_TIE_TOLERANCE = 0.0025
    WIN_COUNT_TIE_TOLERANCE = 1
    EXPECTED_VALUE_TIE_TOLERANCE = 0.02
    MEMORY_GUARD_FRACTION = 0.8
    MEMORY_GUARD_FALLBACK_BYTES = 1_500_000_000
    ELIGIBLE_RECORD_BATCH_SIZE = 250

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = SettingsRepository(session)
        self.repository = PlanGenerationTuningRepository(session)
        self.plans = RecommendationPlanRepository(session)
        self.outcomes = EffectivePlanOutcomeRepository(session)
        self.samples = RecommendationDecisionSampleRepository(session)
        self.reliability_features = PlanReliabilityFeatureBuilder()
        self.settings_domains = SettingsDomainService(repository=self.settings)
        self.settings_mutations = SettingsMutationService(repository=self.settings)

    def describe(self) -> dict[str, object]:
        baseline = self.ensure_baseline_config_version()
        active_version_id = self._active_config_version_id() or baseline.id
        active_version = self.repository.get_config_version(active_version_id) if active_version_id is not None else baseline
        latest_run = self.repository.get_latest_run()
        state = PlanGenerationTuningState(
            objective_name=self.OBJECTIVE_NAME,
            active_config_version_id=active_version.id,
            active_config=normalize_plan_generation_tuning_config(active_version.config),
            auto_enabled=bool(self.settings_domains.strategy_settings().plan_generation_tuning["auto_enabled"]),
            auto_promote_enabled=bool(self.settings_domains.strategy_settings().plan_generation_tuning["auto_promote_enabled"]),
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
                if float(normalized.get("global.actionable_confidence_floor_percent", 0.0) or 0.0) >= 60.0:
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
                        payload={"version_label": upgraded.version_label, "parent_version_id": version.id},
                    )
                )
                return upgraded
        version = self.repository.create_config_version(
            PlanGenerationTuningConfigVersion(
                version_label="baseline-v1",
                status="active",
                source="seed",
                config={**normalize_plan_generation_tuning_config(None), "global.actionable_confidence_floor_percent": 60.0},
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
        wide_mode = mode_profile["name"] == "wide"
        effective_limit = None if limit is None else max(1, int(limit))
        records = self._eligible_records(ticker=ticker, setup_family=setup_family, limit=effective_limit)
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
        search_records, validation_records = self._split_records(records, min_validation=min_validation_resolved)
        exploration_seed = self._exploration_seed(active_config=active_config, records=records, mode=mode)
        candidates = self._candidate_configs(active_config, mode=mode)
        walk_forward_service = PlanGenerationWalkForwardService(self)
        batch_size = int(mode_profile["batch_size"])
        evaluations: list[CandidateEvaluation] = []
        evaluation_batch_count = 0
        total_batches = max(1, math.ceil(len(candidates) / batch_size))
        logger.info(
            "plan generation tuning candidate search prepared: mode=%s candidate_count=%s batch_size=%s total_batches=%s exploration_seed=%s",
            mode,
            len(candidates),
            batch_size,
            total_batches,
            exploration_seed,
        )
        for batch in self._batched(candidates, batch_size):
            evaluation_batch_count += 1
            logger.info(
                "plan generation tuning evaluating batch %s/%s: mode=%s batch_candidates=%s rss_mb=%s",
                evaluation_batch_count,
                total_batches,
                mode,
                len(batch),
                round(self._current_rss_bytes() / 1024 / 1024, 1),
            )
            self._memory_guard(stage=f"{mode}-batch-{evaluation_batch_count}-start")
            if explore_mode:
                batch_evaluations = [
                    self._evaluate_candidate_walk_forward(
                        config,
                        active_config,
                        search_records,
                        records,
                        walk_forward_service,
                        min_validation_resolved=min_validation_resolved,
                    )
                    for config in batch
                ]
            else:
                batch_evaluations = [self._evaluate_candidate(config, active_config, search_records, validation_records) for config in batch]
            evaluations.extend(batch_evaluations)
            gc.collect()
            self._memory_guard(stage=f"{mode}-batch-{evaluation_batch_count}-end")
        evaluations.sort(key=cmp_to_key(self._candidate_compare))
        baseline_eval = next(item for item in evaluations if item.changed_keys == [])
        refinement_candidates = self._refinement_configs(
            evaluations,
            baseline_eval,
            active_config,
            mode=mode,
            max_candidates=int(mode_profile["max_candidates"]),
        )
        refinement_seed_count = 0
        if refinement_candidates:
            refinement_seed_count = min(2, len([item for item in evaluations if item.changed_keys]))
            refinement_total_batches = max(1, math.ceil(len(refinement_candidates) / batch_size))
            logger.info(
                "plan generation tuning refinement search prepared: mode=%s seed_count=%s candidate_count=%s batch_size=%s total_batches=%s exploration_seed=%s",
                mode,
                refinement_seed_count,
                len(refinement_candidates),
                batch_size,
                refinement_total_batches,
                exploration_seed,
            )
            for batch in self._batched(refinement_candidates, batch_size):
                evaluation_batch_count += 1
                logger.info(
                    "plan generation tuning evaluating refinement batch %s/%s: mode=%s batch_candidates=%s rss_mb=%s",
                    evaluation_batch_count,
                    total_batches + refinement_total_batches,
                    mode,
                    len(batch),
                    round(self._current_rss_bytes() / 1024 / 1024, 1),
                )
                self._memory_guard(stage=f"{mode}-refinement-batch-{evaluation_batch_count}-start")
                if explore_mode:
                    batch_evaluations = [
                        self._evaluate_candidate_walk_forward(
                            config,
                            active_config,
                            search_records,
                            records,
                            walk_forward_service,
                            min_validation_resolved=min_validation_resolved,
                        )
                        for config in batch
                    ]
                else:
                    batch_evaluations = [self._evaluate_candidate(config, active_config, search_records, validation_records) for config in batch]
                evaluations.extend(batch_evaluations)
                gc.collect()
                self._memory_guard(stage=f"{mode}-refinement-batch-{evaluation_batch_count}-end")
        self._memory_guard(stage=f"{mode}-post-evaluation")
        evaluations.sort(key=cmp_to_key(self._candidate_compare))
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
        walk_forward_validation = (
            walk_forward_service.summarize_records(
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
            if explore_mode
            else walk_forward_service.summarize(
                candidate_config=winner.config,
                baseline_config=active_config,
                candidate_label=f"run-{mode}-winner" if mode else "candidate",
                baseline_label="active-baseline",
                ticker=ticker,
                setup_family=setup_family,
                limit=effective_limit,
                lookback_days=history_span_days,
                validation_days=validation_days,
                step_days=step_days,
                min_validation_resolved=min_validation_resolved,
            )
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
                    "exploration_seed": exploration_seed,
                    "exploration_campaign_plan": exploration_campaigns(),
                    "search_record_count": len(search_records),
                    "validation_record_count": len(validation_records),
                    "validation_mode": "rolling_walk_forward" if explore_mode else "single_holdout",
                    "validation_slice_count": walk_forward_validation.total_slices if explore_mode else len(validation_records),
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
                },
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
        )

        stored_candidates: list[PlanGenerationTuningCandidate] = []
        for rank, evaluation in enumerate(evaluations, start=1):
            candidate = self.repository.create_candidate(
                PlanGenerationTuningCandidate(
                    run_id=run.id,
                    rank=rank,
                    status="evaluated",
                    is_baseline=(evaluation.changed_keys == []),
                    promotion_eligible=self._promotion_eligible(evaluation, baseline_eval, min_validation_resolved=min_validation_resolved),
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
                        "validation_win_rate_percent": round(evaluation.validation_win_rate * 100.0, 2),
                        "validation_actionable_count": evaluation.validation_actionable_count,
                        "validation_slice_count": evaluation.validation_slice_count,
                        "validation_baseline_win_count": evaluation.validation_baseline_win_count,
                        "validation_ties": evaluation.validation_ties,
                        "validation_average_win_rate_delta": evaluation.validation_average_win_rate_delta,
                        "validation_average_expected_value_delta": evaluation.validation_average_expected_value_delta,
                    },
                    rejection_reasons=[] if self._promotion_eligible(evaluation, baseline_eval, min_validation_resolved=min_validation_resolved) else self._rejection_reasons(evaluation, baseline_eval, min_validation_resolved=min_validation_resolved),
                )
            )
            stored_candidates.append(candidate)

        winner_candidate = stored_candidates[0]
        promoted_config_version_id = None
        promotion_applied = False
        promotion_rejection_reasons: list[str] = []
        if apply:
            logger.info(
                "plan generation tuning apply requested: run_id=%s winner_candidate_id=%s promotion_eligible=%s",
                run.id,
                winner_candidate.id,
                winner_candidate.promotion_eligible,
            )
            if not winner_candidate.promotion_eligible:
                promotion_rejection_reasons.extend(winner_candidate.rejection_reasons or ["winning_candidate_not_promotion_eligible"])
            if walk_forward_validation.qualified_slices >= 3 and not walk_forward_validation.promotion_recommended:
                rationale = (walk_forward_validation.promotion_rationale or "walk_forward_validation_rejected").strip()
                if rationale:
                    promotion_rejection_reasons.append(rationale)
            edge_gate_report = self._edge_validation_gate_report(walk_forward_validation=walk_forward_validation)
            if edge_gate_report["label"] != "eligible_for_cautious_expansion":
                promotion_rejection_reasons.append(f"edge_validation_gate_{edge_gate_report['label']}")
            if not promotion_rejection_reasons:
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
                promoted_config_version_id = promoted.id
                promotion_applied = True
                self.repository.create_event(
                    PlanGenerationTuningEvent(
                        event_type="config_promoted",
                        run_id=run.id,
                        config_version_id=promoted.id,
                        candidate_id=winner_candidate.id,
                        payload={"version_label": promoted.version_label},
                    )
                )
            else:
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
        logger.info(
            "plan generation tuning finished: run_id=%s status=%s candidate_count=%s promoted_config_version_id=%s duration_seconds=%.3f",
            finished_run.id,
            finished_run.status,
            finished_run.candidate_count,
            finished_run.promoted_config_version_id,
            (datetime.now(timezone.utc) - started_at).total_seconds(),
        )
        return finished_run

    def promote_config_version(self, config_version_id: int) -> PlanGenerationTuningConfigVersion:
        gate_report = self._edge_validation_gate_report()
        version = self.repository.get_config_version(config_version_id)
        self.settings_mutations.set_plan_generation_active_config_version_id(version.id)
        self.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="config_promoted_manual",
                config_version_id=version.id,
                payload={"version_label": version.version_label, "edge_validation_gate": gate_report},
            )
        )
        return version

    def promote_candidate(self, run_id: int, candidate_id: int) -> PlanGenerationTuningConfigVersion:
        gate_report = self._edge_validation_gate_report()
        run = self.repository.get_run(run_id)
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.run_id != run.id:
            raise PlanGenerationTuningError(f"candidate {candidate_id} does not belong to run {run_id}")
        if not candidate.promotion_eligible:
            raise PlanGenerationTuningError(f"candidate {candidate_id} is not promotion eligible")
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
                },
            )
        )
        return version

    def _edge_validation_gate_report(self, *, walk_forward_validation: object | None = None) -> dict[str, object]:
        policy_summary = TradePolicyEvaluationService(
            self.outcomes,
            policy_service=TradeDecisionPolicyService(self.session),
        ).summarize_active_policy()
        return EdgeValidationGateService().evaluate(
            policy_summary.policy_evaluation,
            walk_forward_validation=walk_forward_validation,
        ).to_dict()

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
        value = self.settings_domains.strategy_settings().plan_generation_tuning.get("active_config_version_id")
        return value if isinstance(value, int) else None

    def _eligible_records(self, *, ticker: str | None, setup_family: str | None, limit: int | None) -> list[EligibleTuningRecord]:
        normalized_limit = None if limit is None else max(1, int(limit))
        eligible: list[EligibleTuningRecord] = []
        normalized_setup_family = str(setup_family or "").strip().lower() or None
        offset = 0
        while True:
            batch_limit = self.ELIGIBLE_RECORD_BATCH_SIZE
            if normalized_limit is not None:
                remaining = normalized_limit - offset
                if remaining <= 0:
                    break
                batch_limit = min(batch_limit, remaining)
            plans = self.plans.list_plans(ticker=ticker, action=None, limit=batch_limit, offset=offset)
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
                if normalized_setup_family and features.setup_family != normalized_setup_family:
                    continue
                eligible.append(
                    EligibleTuningRecord(
                        plan=plan,
                        outcome=outcome,
                        sample=sample,
                        setup_family=features.setup_family,
                        context_bias=features.context_bias,
                    )
                )
            offset += len(plans)
            if len(plans) < batch_limit:
                break
        eligible.sort(key=lambda item: item.plan.computed_at)
        return eligible

    @staticmethod
    def _split_records(records: list[EligibleTuningRecord], *, min_validation: int) -> tuple[list[EligibleTuningRecord], list[EligibleTuningRecord]]:
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
        search_actionable_count, search_win_count, search_expected_value, search_ambiguous_count = self._score_records(search_records, config)
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
        changed_keys = [key for key, value in config.items() if round(float(value), 4) != round(float(baseline_config.get(key, value)), 4)]
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

    def _candidate_configs(self, active_config: dict[str, float], *, mode: str) -> list[dict[str, float]]:
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
                    mutated[key] = self._campaign_bounded_value(definition, candidate, explore_mode=explore_mode)
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
        seen = {tuple(sorted(normalize_plan_generation_tuning_config(item.config).items())) for item in initial_evaluations}
        refined: list[dict[str, float]] = []

        def add_refinement(source: CandidateEvaluation, key: str, *, step_scale: float, limit: int) -> None:
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
                mutated[key] = self._campaign_bounded_value(definition, candidate_value, explore_mode=explore_mode)
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
    def _refinement_target_key(source: CandidateEvaluation, active_config: dict[str, float]) -> str | None:
        if not source.changed_keys:
            return None
        return max(
            source.changed_keys,
            key=lambda key: abs(float(source.config[key]) - float(active_config.get(key, source.config[key]))),
        )

    def _exploration_seed(self, *, active_config: dict[str, float], records: list[EligibleTuningRecord], mode: str) -> int:
        fingerprint_source = {
            "mode": mode,
            "active_config": active_config,
            "eligible_count": len(records),
            "first_computed_at": records[0].plan.computed_at.isoformat() if records and records[0].plan.computed_at else None,
            "last_computed_at": records[-1].plan.computed_at.isoformat() if records and records[-1].plan.computed_at else None,
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
        if normalized in {"wide", "expensive", "deep", "deep_research"}:
            return {
                "name": "wide",
                "explore_like": True,
                "step_counts": (-3, -2, -1, 1, 2, 3),
                "max_candidates": 67,
                "batch_size": 16,
            }
        if normalized in {"explore", "exploration", "research"}:
            return {
                "name": "explore",
                "explore_like": True,
                "step_counts": (-2, -1, 1, 2),
                "max_candidates": 45,
                "batch_size": 12,
            }
        return {
            "name": "manual",
            "explore_like": False,
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
        changed_keys = [key for key, value in config.items() if round(float(value), 4) != round(float(baseline_config.get(key, value)), 4)]
        search_actionable_count, search_win_count, search_expected_value, search_ambiguous_count = self._score_records(search_records, config)
        validation_actionable_count, validation_win_count, validation_expected_value, validation_ambiguous_count = self._score_records(validation_records, config)
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

    def _score_records(self, records: list[EligibleTuningRecord], config: dict[str, float]) -> tuple[int, int, float, int]:
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

    def _candidate_resolution(self, record: EligibleTuningRecord, config: dict[str, float]) -> tuple[str, float, float] | None:
        entry = self._entry_reference(record.plan)
        if entry is None or entry <= 0 or record.plan.stop_loss is None or record.plan.take_profit is None:
            return None
            
        signal_breakdown = self._plan_signal_breakdown(record.plan)
        intended_action = str(signal_breakdown.get("intended_action") or "").strip().lower() or None
        effective_action = intended_action if record.plan.action in {"no_action", "watchlist"} and intended_action in {"long", "short"} else record.plan.action

        if effective_action not in {"long", "short"}:
            return None

        confidence_floor = float(config.get("global.actionable_confidence_floor_percent", 60.0) or 60.0)
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
            volatility_score=float(volatility_score) if isinstance(volatility_score, (int, float)) else None,
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
        if changed.issubset({"global.entry_band_risk_fraction", "setup_family.entry_band_multiplier"}):
            return "entry_calibration"
        if changed.issubset({"global.actionable_confidence_floor_percent"}):
            return "selectivity"
        if changed.issubset({"global.headwind_stop_multiplier", "global.volatility_stop_multiplier", "setup_family.breakout.stop_distance_multiplier", "setup_family.mean_reversion.stop_distance_multiplier"}):
            return "risk_protection"
        if changed.issubset({"setup_family.breakout.take_profit_distance_multiplier", "setup_family.mean_reversion.take_profit_distance_multiplier", "setup_family.catalyst_follow_through.take_profit_distance_multiplier", "setup_family.macro_beneficiary_loser.take_profit_distance_multiplier"}):
            return "reward_expansion"
        return "other"

    @staticmethod
    def _candidate_payload(item: CandidateEvaluation) -> dict[str, object]:
        return {
            "config": item.config,
            "changed_keys": item.changed_keys,
            "campaign": PlanGenerationTuningService._candidate_campaign_name(item.changed_keys),
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
    def _promotion_eligible(cls, candidate: CandidateEvaluation, baseline: CandidateEvaluation, *, min_validation_resolved: int) -> bool:
        if candidate.validation_actionable_count < min_validation_resolved:
            return False
        win_rate_delta = candidate.validation_win_rate - baseline.validation_win_rate
        if win_rate_delta < -cls.WIN_RATE_TIE_TOLERANCE:
            return False
        win_count_delta = candidate.validation_win_count - baseline.validation_win_count
        if abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE and win_count_delta < -cls.WIN_COUNT_TIE_TOLERANCE:
            return False
        expected_value_delta = candidate.validation_expected_value - baseline.validation_expected_value
        if abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE and abs(win_count_delta) <= cls.WIN_COUNT_TIE_TOLERANCE and expected_value_delta < -cls.EXPECTED_VALUE_TIE_TOLERANCE:
            return False
        return True

    @classmethod
    def _rejection_reasons(cls, candidate: CandidateEvaluation, baseline: CandidateEvaluation, *, min_validation_resolved: int) -> list[str]:
        reasons: list[str] = []
        if candidate.validation_actionable_count < min_validation_resolved:
            reasons.append("insufficient_validation_actionable_records")
        win_rate_delta = candidate.validation_win_rate - baseline.validation_win_rate
        if win_rate_delta < -cls.WIN_RATE_TIE_TOLERANCE:
            reasons.append("validation_win_rate_below_baseline")
        win_count_delta = candidate.validation_win_count - baseline.validation_win_count
        if abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE and win_count_delta < -cls.WIN_COUNT_TIE_TOLERANCE:
            reasons.append("validation_win_count_below_baseline")
        expected_value_delta = candidate.validation_expected_value - baseline.validation_expected_value
        if abs(win_rate_delta) <= cls.WIN_RATE_TIE_TOLERANCE and abs(win_count_delta) <= cls.WIN_COUNT_TIE_TOLERANCE and expected_value_delta < -cls.EXPECTED_VALUE_TIE_TOLERANCE:
            reasons.append("validation_expected_value_below_baseline")
        return reasons
