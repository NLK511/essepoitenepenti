from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationAutotuneRun, RecommendationDecisionSample, RecommendationPlanOutcome
from trade_proposer_app.repositories.recommendation_autotune_runs import RecommendationAutotuneRunRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.settings import SettingsRepository


class RecommendationAutotuneError(Exception):
    pass


@dataclass(slots=True)
class EvaluatedCandidate:
    threshold: float
    score: float
    selected_count: int
    resolved_selected_count: int
    win_count: int
    loss_count: int
    skipped_win_count: int
    skipped_loss_count: int
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
        return {
            "threshold": round(self.threshold, 2),
            "score": round(self.score, 3),
            "selected_count": self.selected_count,
            "resolved_selected_count": self.resolved_selected_count,
            "resolved_sample_count": resolved_total,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "skipped_win_count": self.skipped_win_count,
            "skipped_loss_count": self.skipped_loss_count,
            "true_positive_count": self.true_positive_count,
            "false_positive_count": self.false_positive_count,
            "false_negative_count": self.false_negative_count,
            "true_negative_count": self.true_negative_count,
            "selection_rate_percent": round(selection_rate, 1),
            "precision_percent": round(precision, 1) if precision is not None else None,
            "recall_percent": round(recall, 1) if recall is not None else None,
            "win_rate_percent": round(win_rate, 1) if win_rate is not None else None,
        }


class RecommendationAutotuneService:
    OBJECTIVE_NAME = "confidence_threshold_raw_grid"
    THRESHOLD_OFFSETS = (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0)
    MIN_THRESHOLD = 45.0
    MAX_THRESHOLD = 90.0

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = SettingsRepository(session)
        self.samples = RecommendationDecisionSampleRepository(session)
        self.outcomes = RecommendationOutcomeRepository(session)
        self.runs = RecommendationAutotuneRunRepository(session)

    def run(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        review_priority: str | None = None,
        decision_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 500,
        apply: bool = False,
    ) -> RecommendationAutotuneRun:
        started_at = datetime.now(timezone.utc)
        threshold_before = self.settings.get_confidence_threshold()
        samples = self.samples.list_samples(
            ticker=ticker,
            run_id=run_id,
            decision_type=decision_type,
            review_priority=review_priority,
            limit=limit,
        )
        samples = self._filter_samples(samples, setup_family=setup_family, created_after=created_after, created_before=created_before)
        if not samples:
            raise RecommendationAutotuneError("no decision samples available for autotuning")

        outcomes = self.outcomes.get_outcomes_by_plan_ids([sample.recommendation_plan_id for sample in samples])
        scored_samples = self._resolved_samples(samples, outcomes)
        if not scored_samples:
            raise RecommendationAutotuneError("no resolved recommendation-plan outcomes available for autotuning")

        candidate_thresholds = self._candidate_thresholds(threshold_before)
        evaluated_candidates = [self._evaluate_candidate(scored_samples, threshold) for threshold in candidate_thresholds]
        evaluated_candidates.sort(
            key=lambda item: (item.score, item.win_count, -item.false_positive_count, item.threshold),
            reverse=True,
        )
        winner = evaluated_candidates[0]
        baseline = self._evaluate_candidate(scored_samples, threshold_before)

        applied_threshold = None
        if apply:
            applied_threshold = round(winner.threshold, 2)
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
                review_priority=review_priority,
                decision_type=decision_type,
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
            "selected_resolved_count": winner.resolved_selected_count,
            "selected_win_count": winner.win_count,
            "selected_loss_count": winner.loss_count,
            "skipped_win_count": winner.skipped_win_count,
            "skipped_loss_count": winner.skipped_loss_count,
            "selection_rate_percent": winner_dict["selection_rate_percent"],
        }
        artifact = {
            "objective_name": self.OBJECTIVE_NAME,
            "candidates": [candidate.to_dict() for candidate in evaluated_candidates],
            "sample_plan_ids": [sample.recommendation_plan_id for sample, _ in scored_samples],
            "threshold_before": round(threshold_before, 2),
            "threshold_after": applied_threshold,
        }
        run = RecommendationAutotuneRun(
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
            winning_config={"confidence_threshold": round(winner.threshold, 2)},
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
            "latest_run": latest,
        }

    @classmethod
    def _candidate_thresholds(cls, baseline: float) -> list[float]:
        candidates = {
            round(max(cls.MIN_THRESHOLD, min(cls.MAX_THRESHOLD, baseline + offset)), 2)
            for offset in cls.THRESHOLD_OFFSETS
        }
        candidates.add(round(max(cls.MIN_THRESHOLD, min(cls.MAX_THRESHOLD, baseline)), 2))
        return sorted(candidates)

    @staticmethod
    def _filter_samples(
        samples: list[RecommendationDecisionSample],
        *,
        setup_family: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> list[RecommendationDecisionSample]:
        filtered: list[RecommendationDecisionSample] = []
        normalized_setup_family = str(setup_family or "").strip().lower() or None
        for sample in samples:
            sample_time = sample.reviewed_at or sample.created_at
            if normalized_setup_family and str(sample.setup_family or "").strip().lower() != normalized_setup_family:
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
            if outcome is None or outcome.outcome not in {"win", "loss"}:
                continue
            resolved.append((sample, outcome))
        return resolved

    @staticmethod
    def _decision_score(sample: RecommendationDecisionSample) -> float:
        return float(sample.calibrated_confidence_percent if sample.calibrated_confidence_percent is not None else sample.confidence_percent)

    def _evaluate_candidate(
        self,
        samples: list[tuple[RecommendationDecisionSample, RecommendationPlanOutcome]],
        threshold: float,
    ) -> EvaluatedCandidate:
        selected_count = 0
        resolved_selected_count = 0
        win_count = 0
        loss_count = 0
        skipped_win_count = 0
        skipped_loss_count = 0
        true_positive_count = 0
        false_positive_count = 0
        false_negative_count = 0
        true_negative_count = 0
        score = 0.0
        for sample, outcome in samples:
            selected = self._decision_score(sample) >= threshold
            is_win = outcome.outcome == "win"
            is_loss = outcome.outcome == "loss"
            if selected:
                selected_count += 1
                if is_win:
                    resolved_selected_count += 1
                    win_count += 1
                    true_positive_count += 1
                    score += 3.0
                elif is_loss:
                    resolved_selected_count += 1
                    loss_count += 1
                    false_positive_count += 1
                    score -= 3.0
            else:
                if is_win:
                    skipped_win_count += 1
                    false_negative_count += 1
                    score -= 1.5
                elif is_loss:
                    skipped_loss_count += 1
                    true_negative_count += 1
                    score += 0.75
        return EvaluatedCandidate(
            threshold=round(threshold, 2),
            score=round(score, 3),
            selected_count=selected_count,
            resolved_selected_count=resolved_selected_count,
            win_count=win_count,
            loss_count=loss_count,
            skipped_win_count=skipped_win_count,
            skipped_loss_count=skipped_loss_count,
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
        review_priority: str | None,
        decision_type: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        limit: int,
        apply: bool,
    ) -> dict[str, object]:
        return {
            "ticker": ticker.upper() if ticker else None,
            "run_id": run_id,
            "setup_family": setup_family,
            "review_priority": review_priority,
            "decision_type": decision_type,
            "created_after": created_after.isoformat() if created_after else None,
            "created_before": created_before.isoformat() if created_before else None,
            "limit": limit,
            "apply": apply,
        }
