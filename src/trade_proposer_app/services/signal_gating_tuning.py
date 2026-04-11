from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationSignalGatingTuningRun, RecommendationDecisionSample, RecommendationPlanOutcome
from trade_proposer_app.repositories.signal_gating_tuning_runs import RecommendationSignalGatingTuningRunRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.settings import SettingsRepository


class RecommendationSignalGatingTuningError(Exception):
    pass


@dataclass(slots=True)
class SignalGatingTuningConfig:
    threshold_offset: float
    confidence_adjustment: float
    near_miss_gap_cutoff: float
    shortlist_aggressiveness: float
    degraded_penalty: float

    @property
    def confidence_threshold_delta(self) -> float:
        return self.threshold_offset

    def to_dict(self) -> dict[str, float]:
        return {
            "threshold_offset": round(self.threshold_offset, 2),
            "confidence_adjustment": round(self.confidence_adjustment, 2),
            "near_miss_gap_cutoff": round(self.near_miss_gap_cutoff, 2),
            "shortlist_aggressiveness": round(self.shortlist_aggressiveness, 2),
            "degraded_penalty": round(self.degraded_penalty, 2),
        }


@dataclass(slots=True)
class EvaluatedCandidate:
    config: SignalGatingTuningConfig
    threshold: float
    score: float
    selected_count: int
    resolved_selected_count: int
    win_count: int
    loss_count: int
    skipped_win_count: int
    skipped_loss_count: int
    shortlisted_selected_count: int
    near_miss_selected_count: int
    degraded_selected_count: int
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int
    true_negative_count: int

    def to_dict(self) -> dict[str, object]:
        resolved_total = self.win_count + self.loss_count
        selection_rate = (self.selected_count / resolved_total * 100.0) if resolved_total else 0.0
        precision = (self.win_count / self.selected_count * 100.0) if self.selected_count else None
        recall = (self.win_count / resolved_total * 100.0) if resolved_total else None
        win_rate = (self.win_count / self.resolved_selected_count * 100.0) if self.resolved_selected_count else None
        payload = self.config.to_dict()
        payload.update(
            {
                "threshold": round(self.threshold, 2),
                "score": round(self.score, 3),
                "selected_count": self.selected_count,
                "resolved_selected_count": self.resolved_selected_count,
                "resolved_sample_count": resolved_total,
                "win_count": self.win_count,
                "loss_count": self.loss_count,
                "skipped_win_count": self.skipped_win_count,
                "skipped_loss_count": self.skipped_loss_count,
                "shortlisted_selected_count": self.shortlisted_selected_count,
                "near_miss_selected_count": self.near_miss_selected_count,
                "degraded_selected_count": self.degraded_selected_count,
                "true_positive_count": self.true_positive_count,
                "false_positive_count": self.false_positive_count,
                "false_negative_count": self.false_negative_count,
                "true_negative_count": self.true_negative_count,
                "selection_rate_percent": round(selection_rate, 1),
                "precision_percent": round(precision, 1) if precision is not None else None,
                "recall_percent": round(recall, 1) if recall is not None else None,
                "win_rate_percent": round(win_rate, 1) if win_rate is not None else None,
            }
        )
        return payload


class RecommendationSignalGatingTuningService:
    OBJECTIVE_NAME = "signal_gating_tuning_raw_grid"
    THRESHOLD_OFFSETS = (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0)
    CONFIDENCE_ADJUSTMENTS = (-4.0, -2.0, 0.0, 2.0)
    NEAR_MISS_GAP_CUTOFFS = (0.0, 1.5, 3.0)
    SHORTLIST_AGGRESSIVENESS = (0.0, 1.0, 2.0)
    DEGRADED_PENALTIES = (0.0, 1.5, 3.0)
    MIN_THRESHOLD = 45.0
    MAX_THRESHOLD = 90.0

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = SettingsRepository(session)
        self.samples = RecommendationDecisionSampleRepository(session)
        self.outcomes = RecommendationOutcomeRepository(session)
        self.runs = RecommendationSignalGatingTuningRunRepository(session)

    def run(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        transmission_bias: str | None = None,
        context_regime: str | None = None,
        review_priority: str | None = None,
        decision_type: str | None = None,
        shortlisted: bool | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 500,
        apply: bool = False,
    ) -> RecommendationSignalGatingTuningRun:
        started_at = datetime.now(timezone.utc)
        threshold_before = self.settings.get_confidence_threshold()
        active_tuning = self.settings.get_signal_gating_tuning_config()
        samples = self.samples.list_samples(
            ticker=ticker,
            run_id=run_id,
            decision_type=decision_type,
            review_priority=review_priority,
            shortlisted=shortlisted,
            setup_family=setup_family,
            transmission_bias=transmission_bias,
            context_regime=context_regime,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )
        samples = self._filter_samples(
            samples,
            setup_family=setup_family,
            transmission_bias=transmission_bias,
            context_regime=context_regime,
            created_after=created_after,
            created_before=created_before,
        )
        if not samples:
            raise RecommendationSignalGatingTuningError("no decision samples available for signal gating tuning")

        outcomes = self.outcomes.get_outcomes_by_plan_ids([sample.recommendation_plan_id for sample in samples])
        scored_samples = self._resolved_samples(samples, outcomes)
        if not scored_samples:
            raise RecommendationSignalGatingTuningError("no resolved recommendation-plan outcomes available for signal gating tuning")

        evaluated_candidates = [self._evaluate_candidate(scored_samples, config, threshold_before) for config in self._candidate_configs(active_tuning)]
        evaluated_candidates.sort(
            key=lambda item: (item.score, item.win_count, -item.false_positive_count, item.threshold),
            reverse=True,
        )
        winner = evaluated_candidates[0]
        baseline_config = SignalGatingTuningConfig(
            threshold_offset=0.0,
            confidence_adjustment=active_tuning["confidence_adjustment"],
            near_miss_gap_cutoff=active_tuning["near_miss_gap_cutoff"],
            shortlist_aggressiveness=active_tuning["shortlist_aggressiveness"],
            degraded_penalty=active_tuning["degraded_penalty"],
        )
        baseline = self._evaluate_candidate(scored_samples, baseline_config, threshold_before)

        applied_threshold = None
        applied_config = None
        if apply:
            applied_threshold = round(winner.threshold, 2)
            applied_config = self.settings.set_signal_gating_tuning_config(
                threshold_offset=winner.config.threshold_offset,
                confidence_adjustment=winner.config.confidence_adjustment,
                near_miss_gap_cutoff=winner.config.near_miss_gap_cutoff,
                shortlist_aggressiveness=winner.config.shortlist_aggressiveness,
                degraded_penalty=winner.config.degraded_penalty,
            )
            self.settings.set_confidence_threshold(applied_threshold)

        completed_at = datetime.now(timezone.utc)
        winner_dict = winner.to_dict()
        baseline_dict = baseline.to_dict()
        summary = {
            "status": "completed",
            "objective_name": self.OBJECTIVE_NAME,
            "filters": self._filters_payload(
                ticker=ticker,
                run_id=run_id,
                setup_family=setup_family,
                transmission_bias=transmission_bias,
                context_regime=context_regime,
                review_priority=review_priority,
                decision_type=decision_type,
                shortlisted=shortlisted,
                created_after=created_after,
                created_before=created_before,
                limit=limit,
                apply=apply,
            ),
            "sample_count": len(samples),
            "resolved_sample_count": len(scored_samples),
            "candidate_count": len(evaluated_candidates),
            "current_threshold": round(threshold_before, 2),
            "baseline_threshold": round(threshold_before, 2),
            "baseline_score": round(baseline.score, 3),
            "baseline_selection_rate_percent": baseline_dict["selection_rate_percent"],
            "best_threshold": round(winner.threshold, 2),
            "best_score": round(winner.score, 3),
            "best_delta": round(winner.score - baseline.score, 3),
            "applied": apply,
            "applied_threshold": applied_threshold,
            "applied_config": applied_config,
            "selected_resolved_count": winner.resolved_selected_count,
            "selected_win_count": winner.win_count,
            "selected_loss_count": winner.loss_count,
            "skipped_win_count": winner.skipped_win_count,
            "skipped_loss_count": winner.skipped_loss_count,
            "selection_rate_percent": winner_dict["selection_rate_percent"],
            "best_config": winner.config.to_dict(),
        }
        artifact = {
            "objective_name": self.OBJECTIVE_NAME,
            "candidates": [candidate.to_dict() for candidate in evaluated_candidates],
            "sample_plan_ids": [sample.recommendation_plan_id for sample, _ in scored_samples],
            "threshold_before": round(threshold_before, 2),
            "threshold_after": applied_threshold,
            "active_tuning": active_tuning,
        }
        run = RecommendationSignalGatingTuningRun(
            objective_name=self.OBJECTIVE_NAME,
            status="completed",
            applied=apply,
            filters=summary["filters"],
            sample_count=len(samples),
            resolved_sample_count=len(scored_samples),
            candidate_count=len(evaluated_candidates),
            baseline_threshold=round(threshold_before, 2),
            baseline_score=round(baseline.score, 3),
            best_threshold=round(winner.threshold, 2),
            best_score=round(winner.score, 3),
            winning_config={"confidence_threshold": round(winner.threshold, 2), **winner.config.to_dict()},
            candidate_results=[candidate.to_dict() for candidate in evaluated_candidates],
            summary=summary,
            artifact=artifact,
            started_at=started_at,
            completed_at=completed_at,
        )
        return self.runs.create_run(run)

    def describe(self) -> dict[str, object]:
        latest = self.runs.get_latest_run()
        return {
            "objective_name": self.OBJECTIVE_NAME,
            "current_confidence_threshold": self.settings.get_confidence_threshold(),
            "active_tuning": self.settings.get_signal_gating_tuning_config(),
            "latest_run": latest,
        }

    @classmethod
    def _candidate_configs(cls, active_tuning: dict[str, float]) -> list[SignalGatingTuningConfig]:
        configs: list[SignalGatingTuningConfig] = []
        for threshold_offset, confidence_adjustment, near_miss_gap_cutoff, shortlist_aggressiveness, degraded_penalty in product(
            cls.THRESHOLD_OFFSETS,
            cls.CONFIDENCE_ADJUSTMENTS,
            cls.NEAR_MISS_GAP_CUTOFFS,
            cls.SHORTLIST_AGGRESSIVENESS,
            cls.DEGRADED_PENALTIES,
        ):
            configs.append(
                SignalGatingTuningConfig(
                    threshold_offset=threshold_offset,
                    confidence_adjustment=confidence_adjustment,
                    near_miss_gap_cutoff=near_miss_gap_cutoff,
                    shortlist_aggressiveness=shortlist_aggressiveness,
                    degraded_penalty=degraded_penalty,
                )
            )
        baseline = SignalGatingTuningConfig(
            threshold_offset=0.0,
            confidence_adjustment=active_tuning["confidence_adjustment"],
            near_miss_gap_cutoff=active_tuning["near_miss_gap_cutoff"],
            shortlist_aggressiveness=active_tuning["shortlist_aggressiveness"],
            degraded_penalty=active_tuning["degraded_penalty"],
        )
        if baseline not in configs:
            configs.append(baseline)
        return configs

    @staticmethod
    def _filter_samples(
        samples: list[RecommendationDecisionSample],
        *,
        setup_family: str | None,
        transmission_bias: str | None,
        context_regime: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> list[RecommendationDecisionSample]:
        filtered: list[RecommendationDecisionSample] = []
        normalized_setup_family = str(setup_family or "").strip().lower() or None
        normalized_transmission_bias = str(transmission_bias or "").strip().lower() or None
        normalized_context_regime = str(context_regime or "").strip().lower() or None
        for sample in samples:
            sample_time = sample.reviewed_at or sample.created_at
            if normalized_setup_family and str(sample.setup_family or "").strip().lower() != normalized_setup_family:
                continue
            if normalized_transmission_bias and str(sample.transmission_bias or "").strip().lower() != normalized_transmission_bias:
                continue
            if normalized_context_regime and str(sample.context_regime or "").strip().lower() != normalized_context_regime:
                continue
            if created_after is not None and sample_time < created_after:
                continue
            if created_before is not None and sample_time > created_before:
                continue
            filtered.append(sample)
        return filtered

    @staticmethod
    def _resolved_samples(
        samples: list[RecommendationDecisionSample],
        outcomes: dict[int, RecommendationPlanOutcome],
    ) -> list[tuple[RecommendationDecisionSample, RecommendationPlanOutcome]]:
        resolved: list[tuple[RecommendationDecisionSample, RecommendationPlanOutcome]] = []
        for sample in samples:
            outcome = outcomes.get(sample.recommendation_plan_id)
            if outcome is None or outcome.outcome not in {"win", "loss", "phantom_win", "phantom_loss"}:
                continue
            resolved.append((sample, outcome))
        return resolved

    @staticmethod
    def _decision_score(sample: RecommendationDecisionSample, config: SignalGatingTuningConfig) -> float:
        raw_score = float(sample.calibrated_confidence_percent if sample.calibrated_confidence_percent is not None else sample.confidence_percent)
        raw_score += config.confidence_adjustment
        if str(sample.decision_type or "").strip().lower() == "degraded":
            raw_score -= config.degraded_penalty
        return raw_score

    def _effective_threshold(self, sample: RecommendationDecisionSample, base_threshold: float, config: SignalGatingTuningConfig) -> float:
        threshold = base_threshold + config.threshold_offset
        if sample.shortlisted:
            threshold -= config.shortlist_aggressiveness * 1.5
        if str(sample.decision_type or "").strip().lower() == "near_miss":
            threshold -= config.near_miss_gap_cutoff
        return max(self.MIN_THRESHOLD, min(self.MAX_THRESHOLD, threshold))

    def _evaluate_candidate(
        self,
        samples: list[tuple[RecommendationDecisionSample, RecommendationPlanOutcome]],
        config: SignalGatingTuningConfig,
        base_threshold: float,
    ) -> EvaluatedCandidate:
        selected_count = 0
        resolved_selected_count = 0
        win_count = 0
        loss_count = 0
        skipped_win_count = 0
        skipped_loss_count = 0
        shortlisted_selected_count = 0
        near_miss_selected_count = 0
        degraded_selected_count = 0
        true_positive_count = 0
        false_positive_count = 0
        false_negative_count = 0
        true_negative_count = 0
        score = 0.0
        for sample, outcome in samples:
            effective_score = self._decision_score(sample, config)
            threshold = self._effective_threshold(sample, base_threshold, config)
            selected = effective_score >= threshold
            is_win = outcome.outcome in {"win", "phantom_win"}
            is_loss = outcome.outcome in {"loss", "phantom_loss"}
            if sample.shortlisted and selected:
                shortlisted_selected_count += 1
            if str(sample.decision_type or "").strip().lower() == "near_miss" and selected:
                near_miss_selected_count += 1
            if str(sample.decision_type or "").strip().lower() == "degraded" and selected:
                degraded_selected_count += 1
            if selected:
                selected_count += 1
                if is_win:
                    resolved_selected_count += 1
                    win_count += 1
                    true_positive_count += 1
                    score += 4.0
                elif is_loss:
                    resolved_selected_count += 1
                    loss_count += 1
                    false_positive_count += 1
                    score -= 4.0
            else:
                if is_win:
                    skipped_win_count += 1
                    false_negative_count += 1
                    score -= 2.0
                elif is_loss:
                    skipped_loss_count += 1
                    true_negative_count += 1
                    score += 1.0
        score += shortlisted_selected_count * 0.2
        score += near_miss_selected_count * 0.1
        score -= degraded_selected_count * 0.1
        return EvaluatedCandidate(
            config=config,
            threshold=round(base_threshold + config.threshold_offset, 2),
            score=round(score, 3),
            selected_count=selected_count,
            resolved_selected_count=resolved_selected_count,
            win_count=win_count,
            loss_count=loss_count,
            skipped_win_count=skipped_win_count,
            skipped_loss_count=skipped_loss_count,
            shortlisted_selected_count=shortlisted_selected_count,
            near_miss_selected_count=near_miss_selected_count,
            degraded_selected_count=degraded_selected_count,
            true_positive_count=true_positive_count,
            false_positive_count=false_positive_count,
            false_negative_count=false_negative_count,
            true_negative_count=true_negative_count,
        )

    @staticmethod
    def _filters_payload(
        *,
        ticker: str | None,
        run_id: int | None,
        setup_family: str | None,
        transmission_bias: str | None,
        context_regime: str | None,
        review_priority: str | None,
        decision_type: str | None,
        shortlisted: bool | None,
        created_after: datetime | None,
        created_before: datetime | None,
        limit: int,
        apply: bool,
    ) -> dict[str, object]:
        return {
            "ticker": ticker.upper() if ticker else None,
            "run_id": run_id,
            "setup_family": setup_family,
            "transmission_bias": transmission_bias,
            "context_regime": context_regime,
            "review_priority": review_priority,
            "decision_type": decision_type,
            "shortlisted": shortlisted,
            "created_after": created_after.isoformat() if created_after else None,
            "created_before": created_before.isoformat() if created_before else None,
            "limit": limit,
            "apply": apply,
        }
