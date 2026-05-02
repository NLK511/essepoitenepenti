from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import random

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
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_reliability_features import PlanReliabilityFeatureBuilder
from trade_proposer_app.services.plan_generation_tuning_parameters import PARAMETER_BY_KEY, exploration_campaigns, normalize_plan_generation_tuning_config, parameter_definitions
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.settings_mutations import SettingsMutationService


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
                return version
        version = self.repository.create_config_version(
            PlanGenerationTuningConfigVersion(
                version_label="baseline-v1",
                status="active",
                source="seed",
                config=normalize_plan_generation_tuning_config(None),
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
        limit: int | None = 500,
    ) -> PlanGenerationTuningRun:
        started_at = datetime.now(timezone.utc)
        baseline_version = self._resolve_active_config_version()
        active_config = normalize_plan_generation_tuning_config(baseline_version.config)
        explore_mode = mode.strip().lower() in {"explore", "exploration", "research"}
        effective_limit = None if explore_mode else limit
        records = self._eligible_records(ticker=ticker, setup_family=setup_family, limit=effective_limit)
        settings_payload = self.settings_domains.strategy_settings().plan_generation_tuning
        min_actionable_resolved = int(settings_payload["min_actionable_resolved"])
        min_validation_resolved = int(settings_payload["min_validation_resolved"])
        if len(records) < min_actionable_resolved:
            raise PlanGenerationTuningError(
                f"insufficient eligible records for plan generation tuning: {len(records)} available, minimum is {min_actionable_resolved}"
            )
        search_records, validation_records = self._split_records(records, min_validation=min_validation_resolved)
        exploration_seed = self._exploration_seed(active_config=active_config, records=records, mode=mode)
        candidates = self._candidate_configs(active_config, mode=mode, seed=exploration_seed)
        walk_forward_service = PlanGenerationWalkForwardService(self)
        if explore_mode:
            evaluations = [
                self._evaluate_candidate_walk_forward(
                    config,
                    active_config,
                    search_records,
                    records,
                    walk_forward_service,
                    min_validation_resolved=min_validation_resolved,
                )
                for config in candidates
            ]
        else:
            evaluations = [self._evaluate_candidate(config, active_config, search_records, validation_records) for config in candidates]
        evaluations.sort(key=self._candidate_sort_key, reverse=True)
        winner = evaluations[0]
        baseline_eval = next(item for item in evaluations if item.changed_keys == [])
        history_span_days = self._history_span_days(records)
        walk_forward_validation = (
            walk_forward_service.summarize_records(
                records=records,
                candidate_config=winner.config,
                baseline_config=active_config,
                candidate_label=f"run-{mode}-winner" if mode else "candidate",
                baseline_label="active-baseline",
                lookback_days=history_span_days,
                validation_days=90,
                step_days=30,
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
                limit=None if explore_mode else (effective_limit if effective_limit is not None else len(records) or 1),
                lookback_days=history_span_days,
                validation_days=90,
                step_days=30,
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
                    "exploration_seed": exploration_seed,
                    "exploration_campaign_plan": exploration_campaigns(),
                    "search_record_count": len(search_records),
                    "validation_record_count": len(validation_records),
                    "validation_mode": "rolling_walk_forward" if explore_mode else "single_holdout",
                    "validation_slice_count": walk_forward_validation.total_slices if explore_mode else len(validation_records),
                    "history_span_days": history_span_days,
                    "walk_forward_validation": walk_forward_validation.model_dump(mode="json"),
                },
                filters={
                    "ticker": ticker.upper() if ticker else None,
                    "setup_family": setup_family,
                    "limit": limit,
                    "mode": mode,
                    "explore_mode": explore_mode,
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
        if apply:
            if not winner_candidate.promotion_eligible:
                raise PlanGenerationTuningError("winning candidate is not promotion eligible under current guardrails")
            if walk_forward_validation.qualified_slices >= 3 and not walk_forward_validation.promotion_recommended:
                raise PlanGenerationTuningError(f"winning candidate failed walk-forward validation: {walk_forward_validation.promotion_rationale}")
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
            self.repository.create_event(
                PlanGenerationTuningEvent(
                    event_type="config_promoted",
                    run_id=run.id,
                    config_version_id=promoted.id,
                    candidate_id=winner_candidate.id,
                    payload={"version_label": promoted.version_label},
                )
            )

        updated_run = self.repository.get_run(run.id or 0)
        updated_run.winning_candidate_id = winner_candidate.id
        updated_run.promoted_config_version_id = promoted_config_version_id
        updated_run.summary["winner_candidate_id"] = winner_candidate.id
        updated_run.summary["promoted_config_version_id"] = promoted_config_version_id
        updated_run.summary["baseline_config_version_id"] = baseline_version.id
        return self.repository.update_run(run.id or 0, updated_run)

    def promote_config_version(self, config_version_id: int) -> PlanGenerationTuningConfigVersion:
        version = self.repository.get_config_version(config_version_id)
        self.settings_mutations.set_plan_generation_active_config_version_id(version.id)
        self.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="config_promoted_manual",
                config_version_id=version.id,
                payload={"version_label": version.version_label},
            )
        )
        return version

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

    def _eligible_records(self, *, ticker: str | None, setup_family: str | None, limit: int) -> list[EligibleTuningRecord]:
        plans = self.plans.list_plans(ticker=ticker, action=None, limit=limit, offset=0)
        outcome_map = self.outcomes.get_outcomes_by_plan_ids([plan.id for plan in plans if plan.id is not None])
        sample_map = {
            sample.recommendation_plan_id: sample
            for sample in self.samples.list_samples(ticker=ticker, limit=limit)
            if sample.recommendation_plan_id is not None
        }
        eligible: list[EligibleTuningRecord] = []
        normalized_setup_family = str(setup_family or "").strip().lower() or None
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

    def _candidate_configs(self, active_config: dict[str, float], *, mode: str, seed: int) -> list[dict[str, float]]:
        explore_mode = mode.strip().lower() in {"explore", "exploration", "research"}
        configs: list[dict[str, float]] = [dict(active_config)]
        parameter_keys = list(PARAMETER_BY_KEY.keys())
        for key, definition in PARAMETER_BY_KEY.items():
            base_value = active_config.get(key, definition.default)
            step_counts = (-4, -3, -2, -1, 1, 2, 3, 4) if explore_mode else (-2, -1, 1, 2)
            for step_count in step_counts:
                mutated = dict(active_config)
                candidate = base_value + (definition.step * step_count)
                mutated[key] = self._campaign_bounded_value(definition, candidate, explore_mode=explore_mode)
                configs.append(mutated)
        for index, key_a in enumerate(parameter_keys):
            definition_a = PARAMETER_BY_KEY[key_a]
            base_a = active_config.get(key_a, definition_a.default)
            for key_b in parameter_keys[index + 1 :]:
                definition_b = PARAMETER_BY_KEY[key_b]
                base_b = active_config.get(key_b, definition_b.default)
                pair_steps = (-2, -1, 1, 2) if explore_mode else (-1, 1)
                for step_a in pair_steps:
                    for step_b in pair_steps:
                        mutated = dict(active_config)
                        candidate_a = base_a + (definition_a.step * step_a)
                        candidate_b = base_b + (definition_b.step * step_b)
                        mutated[key_a] = self._campaign_bounded_value(definition_a, candidate_a, explore_mode=explore_mode)
                        mutated[key_b] = self._campaign_bounded_value(definition_b, candidate_b, explore_mode=explore_mode)
                        configs.append(mutated)
        for version in self.repository.list_config_versions(limit=100):
            if not version.config:
                continue
            normalized = normalize_plan_generation_tuning_config(version.config)
            if explore_mode:
                normalized = {
                    key: self._campaign_bounded_value(PARAMETER_BY_KEY[key], value, explore_mode=True)
                    for key, value in normalized.items()
                }
            configs.append(normalized)
        if explore_mode:
            rng = random.Random(seed)
            max_random_candidates = 36
            max_random_changes = 4
            for _ in range(max_random_candidates):
                mutated = dict(active_config)
                change_count = rng.randint(1, max_random_changes)
                for key in rng.sample(parameter_keys, change_count):
                    definition = PARAMETER_BY_KEY[key]
                    base_value = mutated.get(key, definition.default)
                    step_count = rng.choice([-4, -3, -2, -1, 1, 2, 3, 4])
                    candidate = base_value + (definition.step * step_count)
                    mutated[key] = self._campaign_bounded_value(definition, candidate, explore_mode=True)
                configs.append(mutated)
        deduped: list[dict[str, float]] = []
        fingerprints: set[tuple[tuple[str, float], ...]] = set()
        max_candidates = 200 if explore_mode else 50
        for config in configs:
            normalized = normalize_plan_generation_tuning_config(config)
            if explore_mode:
                normalized = {
                    key: self._campaign_bounded_value(PARAMETER_BY_KEY[key], value, explore_mode=True)
                    for key, value in normalized.items()
                }
            fingerprint = tuple(sorted(normalized.items()))
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            deduped.append(normalized)
            if len(deduped) >= max_candidates:
                break
        return deduped

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
            
        entry_low, entry_high, stop_loss, take_profit = family_adjusted_trade_levels(
            entry_price=entry,
            stop_loss=float(record.plan.stop_loss),
            take_profit=float(record.plan.take_profit),
            setup_family=record.setup_family,
            action=effective_action,
            transmission_context_bias=record.context_bias,
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
        if changed.issubset({"global.entry_band_risk_fraction"}):
            return "entry_calibration"
        if changed.issubset({"global.headwind_stop_multiplier", "setup_family.breakout.stop_distance_multiplier", "setup_family.mean_reversion.stop_distance_multiplier"}):
            return "risk_protection"
        if changed.issubset({"setup_family.breakout.take_profit_distance_multiplier", "setup_family.mean_reversion.take_profit_distance_multiplier", "setup_family.catalyst_follow_through.take_profit_distance_multiplier", "setup_family.macro_beneficiary_loser.take_profit_distance_multiplier"}):
            return "reward_expansion"
        return "historical_reuse_or_random_mutation"

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

    @staticmethod
    def _promotion_eligible(candidate: CandidateEvaluation, baseline: CandidateEvaluation, *, min_validation_resolved: int) -> bool:
        if candidate.validation_actionable_count < min_validation_resolved:
            return False
        if candidate.validation_win_rate < baseline.validation_win_rate:
            return False
        if candidate.validation_win_rate == baseline.validation_win_rate and candidate.validation_win_count < baseline.validation_win_count:
            return False
        if candidate.validation_win_rate == baseline.validation_win_rate and candidate.validation_win_count == baseline.validation_win_count and candidate.validation_expected_value < baseline.validation_expected_value:
            return False
        return True

    @staticmethod
    def _rejection_reasons(candidate: CandidateEvaluation, baseline: CandidateEvaluation, *, min_validation_resolved: int) -> list[str]:
        reasons: list[str] = []
        if candidate.validation_actionable_count < min_validation_resolved:
            reasons.append("insufficient_validation_actionable_records")
        if candidate.validation_win_rate < baseline.validation_win_rate:
            reasons.append("validation_win_rate_below_baseline")
        if candidate.validation_win_rate == baseline.validation_win_rate and candidate.validation_win_count < baseline.validation_win_count:
            reasons.append("validation_win_count_below_baseline")
        if candidate.validation_win_rate == baseline.validation_win_rate and candidate.validation_win_count == baseline.validation_win_count and candidate.validation_expected_value < baseline.validation_expected_value:
            reasons.append("validation_expected_value_below_baseline")
        return reasons
