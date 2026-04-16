from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from sqlalchemy.orm import Session

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
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import PARAMETER_BY_KEY, normalize_plan_generation_tuning_config, parameter_definitions
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService


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
        self.outcomes = RecommendationOutcomeRepository(session)
        self.samples = RecommendationDecisionSampleRepository(session)

    def describe(self) -> dict[str, object]:
        baseline = self.ensure_baseline_config_version()
        active_version_id = self.settings.get_plan_generation_active_config_version_id() or baseline.id
        active_version = self.repository.get_config_version(active_version_id) if active_version_id is not None else baseline
        latest_run = self.repository.get_latest_run()
        state = PlanGenerationTuningState(
            objective_name=self.OBJECTIVE_NAME,
            active_config_version_id=active_version.id,
            active_config=normalize_plan_generation_tuning_config(active_version.config),
            auto_enabled=bool(self.settings.get_plan_generation_tuning_settings()["auto_enabled"]),
            auto_promote_enabled=bool(self.settings.get_plan_generation_tuning_settings()["auto_promote_enabled"]),
            latest_run=latest_run,
        )
        return {
            "objective_name": self.OBJECTIVE_NAME,
            "parameter_schema_version": self.SCHEMA_VERSION,
            "parameters": parameter_definitions(),
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
        self.settings.set_plan_generation_active_config_version_id(version.id)
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
        limit: int = 500,
    ) -> PlanGenerationTuningRun:
        started_at = datetime.now(timezone.utc)
        baseline_version = self._resolve_active_config_version()
        active_config = normalize_plan_generation_tuning_config(baseline_version.config)
        records = self._eligible_records(ticker=ticker, setup_family=setup_family, limit=limit)
        settings_payload = self.settings.get_plan_generation_tuning_settings()
        min_actionable_resolved = int(settings_payload["min_actionable_resolved"])
        min_validation_resolved = int(settings_payload["min_validation_resolved"])
        if len(records) < min_actionable_resolved:
            raise PlanGenerationTuningError(
                f"insufficient eligible records for plan generation tuning: {len(records)} available, minimum is {min_actionable_resolved}"
            )
        search_records, validation_records = self._split_records(records, min_validation=min_validation_resolved)
        candidates = self._candidate_configs(active_config)
        evaluations = [self._evaluate_candidate(config, active_config, search_records, validation_records) for config in candidates]
        evaluations.sort(key=self._candidate_sort_key, reverse=True)
        winner = evaluations[0]
        baseline_eval = next(item for item in evaluations if item.changed_keys == [])
        walk_forward_validation = PlanGenerationWalkForwardService(self).summarize(
            candidate_config=winner.config,
            baseline_config=active_config,
            candidate_label=f"run-{mode}-winner" if mode else "candidate",
            baseline_label="active-baseline",
            ticker=ticker,
            setup_family=setup_family,
            limit=limit,
            lookback_days=365,
            validation_days=90,
            step_days=30,
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
                    "search_record_count": len(search_records),
                    "validation_record_count": len(validation_records),
                    "walk_forward_validation": walk_forward_validation.model_dump(mode="json"),
                },
                filters={
                    "ticker": ticker.upper() if ticker else None,
                    "setup_family": setup_family,
                    "limit": limit,
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
                    },
                    validation_summary={
                        "validation_win_rate_percent": round(evaluation.validation_win_rate * 100.0, 2),
                        "validation_actionable_count": evaluation.validation_actionable_count,
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
            self.settings.set_plan_generation_active_config_version_id(promoted.id)
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
        self.settings.set_plan_generation_active_config_version_id(version.id)
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
        active_id = self.settings.get_plan_generation_active_config_version_id()
        if active_id is None:
            return baseline
        try:
            return self.repository.get_config_version(active_id)
        except ValueError:
            self.settings.set_plan_generation_active_config_version_id(baseline.id)
            return baseline

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
            if (plan.action or "") not in {"long", "short", "no_action"} or plan.id is None:
                continue
            outcome = outcome_map.get(plan.id)
            if outcome is None or outcome.outcome not in {"win", "loss", "phantom_win", "phantom_loss"}:
                continue
            signal_breakdown = plan.signal_breakdown if isinstance(plan.signal_breakdown, dict) else {}
            transmission_summary = signal_breakdown.get("transmission_summary") if isinstance(signal_breakdown.get("transmission_summary"), dict) else {}
            plan_setup_family = str(signal_breakdown.get("setup_family") or outcome.setup_family or "").strip().lower()
            if normalized_setup_family and plan_setup_family != normalized_setup_family:
                continue
            entry = self._entry_reference(plan)
            if entry is None or entry <= 0 or plan.stop_loss is None or plan.take_profit is None:
                continue
            if outcome.max_favorable_excursion is None or outcome.max_adverse_excursion is None:
                continue
            stop_hit = bool(outcome.stop_loss_hit)
            take_hit = bool(outcome.take_profit_hit)
            if stop_hit == take_hit:
                continue
            risk_pct = abs((entry - float(plan.stop_loss)) / entry) * 100.0
            reward_pct = abs((float(plan.take_profit) - entry) / entry) * 100.0
            if risk_pct <= 0 or reward_pct <= 0:
                continue
            eligible.append(
                EligibleTuningRecord(
                    plan=plan,
                    outcome=outcome,
                    sample=sample_map.get(plan.id),
                    setup_family=plan_setup_family,
                    context_bias=str(transmission_summary.get("context_bias") or "").strip().lower() or None,
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

    def _candidate_configs(self, active_config: dict[str, float]) -> list[dict[str, float]]:
        configs = [dict(active_config)]
        for key, definition in PARAMETER_BY_KEY.items():
            base_value = active_config.get(key, definition.default)
            for direction in (-1, 1):
                mutated = dict(active_config)
                candidate = base_value + (definition.step * direction)
                candidate = max(definition.minimum, min(definition.maximum, candidate))
                mutated[key] = round(candidate, 4)
                configs.append(mutated)
        deduped: list[dict[str, float]] = []
        fingerprints: set[tuple[tuple[str, float], ...]] = set()
        for config in configs:
            normalized = normalize_plan_generation_tuning_config(config)
            fingerprint = tuple(sorted(normalized.items()))
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            deduped.append(normalized)
        return deduped[:50]

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
            if candidate_outcome == "win":
                win_count += 1
                expected_value += reward_pct
            else:
                expected_value -= risk_pct
        return actionable_count, win_count, round(expected_value, 4), ambiguous_count

    def _candidate_resolution(self, record: EligibleTuningRecord, config: dict[str, float]) -> tuple[str, float, float] | None:
        entry = self._entry_reference(record.plan)
        if entry is None or entry <= 0 or record.plan.stop_loss is None or record.plan.take_profit is None:
            return None
            
        intended_action = None
        if isinstance(record.plan.signal_breakdown, dict):
            intended_action = record.plan.signal_breakdown.get("intended_action")
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
    def _candidate_payload(item: CandidateEvaluation) -> dict[str, object]:
        return {
            "config": item.config,
            "changed_keys": item.changed_keys,
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
