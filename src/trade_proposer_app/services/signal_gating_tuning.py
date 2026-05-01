from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import product

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationDecisionSample, RecommendationPlanOutcome, RecommendationSignalGatingTuningRun
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.signal_gating_tuning_runs import RecommendationSignalGatingTuningRunRepository


class RecommendationSignalGatingTuningError(Exception):
    pass


@dataclass(slots=True)
class SignalGatingOutcome:
    outcome: str
    source: str
    benchmark_direction: str | None = None
    benchmark_target_1d_hit: bool | None = None
    benchmark_target_5d_hit: bool | None = None
    benchmark_max_favorable_pct: float | None = None


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
    benchmark_selected_count: int
    benchmark_hit_count: int
    benchmark_miss_count: int
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
                "benchmark_selected_count": self.benchmark_selected_count,
                "benchmark_hit_count": self.benchmark_hit_count,
                "benchmark_miss_count": self.benchmark_miss_count,
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
        self.context_snapshots = ContextSnapshotRepository(session)
        self.market_data = HistoricalMarketDataRepository(session)
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
        limit: int | None = None,
        apply: bool = False,
    ) -> RecommendationSignalGatingTuningRun:
        started_at = datetime.now(timezone.utc)
        threshold_before = self.settings.get_confidence_threshold()
        active_tuning = self.settings.get_signal_gating_tuning_config()
        effective_created_after, sample_window_mode, latest_applied_run = self._effective_created_after(
            created_after=created_after,
            run_id=run_id,
        )
        samples = self.samples.list_samples(
            ticker=ticker,
            run_id=run_id,
            decision_type=decision_type,
            review_priority=review_priority,
            shortlisted=shortlisted,
            setup_family=setup_family,
            transmission_bias=transmission_bias,
            context_regime=context_regime,
            created_after=effective_created_after,
            created_before=created_before,
            limit=limit,
        )
        samples = self._filter_samples(
            samples,
            setup_family=setup_family,
            transmission_bias=transmission_bias,
            context_regime=context_regime,
            created_after=effective_created_after,
            created_before=created_before,
        )
        if not samples:
            raise RecommendationSignalGatingTuningError("no decision samples available for signal gating tuning")

        outcomes = self.outcomes.get_simulated_outcomes_by_plan_ids([sample.recommendation_plan_id for sample in samples if sample.recommendation_plan_id is not None])
        plan_scored_samples = self._plan_scored_samples(samples, outcomes)
        benchmark_scored_samples, benchmark_summary = self._benchmark_scored_samples(samples, plan_scored_samples)
        scored_samples = [*plan_scored_samples, *benchmark_scored_samples]
        if not scored_samples:
            if sample_window_mode == "since_latest_applied" and latest_applied_run is not None:
                boundary = latest_applied_run.completed_at or latest_applied_run.created_at
                boundary_label = boundary.isoformat() if boundary is not None else "the latest applied tuning run"
                raise RecommendationSignalGatingTuningError(
                    f"no scoreable win/loss outcomes or benchmark follow-through found for signal gating tuning since {boundary_label}; try widening the date window or setting a larger manual limit"
                )
            raise RecommendationSignalGatingTuningError(
                "no scoreable win/loss outcomes or benchmark follow-through found for the selected signal gating tuning sample window"
            )

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
                created_after=effective_created_after,
                created_before=created_before,
                limit=limit,
                apply=apply,
                sample_window_mode=sample_window_mode,
                latest_applied_run_completed_at=latest_applied_run.completed_at if latest_applied_run is not None else None,
            ),
            "sample_count": len(samples),
            "resolved_sample_count": len(plan_scored_samples),
            "benchmark_sample_count": benchmark_summary["benchmark_sample_count"],
            "scoreable_sample_count": len(scored_samples),
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
            "benchmark_hit_count": benchmark_summary["benchmark_hit_count"],
            "benchmark_miss_count": benchmark_summary["benchmark_miss_count"],
            "benchmark_target_1d_hit_count": benchmark_summary["benchmark_target_1d_hit_count"],
            "benchmark_target_5d_hit_count": benchmark_summary["benchmark_target_5d_hit_count"],
            "missed_opportunity_count": benchmark_summary["missed_opportunity_count"],
            "good_reject_count": benchmark_summary["good_reject_count"],
            "selection_rate_percent": winner_dict["selection_rate_percent"],
            "best_config": winner.config.to_dict(),
        }
        artifact = {
            "objective_name": self.OBJECTIVE_NAME,
            "candidates": [candidate.to_dict() for candidate in evaluated_candidates],
            "sample_plan_ids": [sample.recommendation_plan_id for sample, _ in plan_scored_samples if sample.recommendation_plan_id is not None],
            "benchmark_sample_ids": [sample.id for sample, _ in benchmark_scored_samples if sample.id is not None],
            "threshold_before": round(threshold_before, 2),
            "threshold_after": applied_threshold,
            "active_tuning": active_tuning,
            "benchmark_summary": benchmark_summary,
        }
        run = RecommendationSignalGatingTuningRun(
            objective_name=self.OBJECTIVE_NAME,
            status="completed",
            applied=apply,
            filters=summary["filters"],
            sample_count=len(samples),
            resolved_sample_count=len(plan_scored_samples),
            benchmark_sample_count=benchmark_summary["benchmark_sample_count"],
            scoreable_sample_count=len(scored_samples),
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

    def _effective_created_after(
        self,
        *,
        created_after: datetime | None,
        run_id: int | None,
    ) -> tuple[datetime | None, str, RecommendationSignalGatingTuningRun | None]:
        if created_after is not None:
            return created_after, "explicit", None
        if run_id is not None:
            return None, "run_id", None
        latest_applied_run = self.runs.get_latest_applied_run()
        if latest_applied_run is None:
            return None, "all_history", None
        return latest_applied_run.completed_at or latest_applied_run.created_at, "since_latest_applied", latest_applied_run

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
    def _plan_scored_samples(
        samples: list[RecommendationDecisionSample],
        outcomes: dict[int, RecommendationPlanOutcome],
    ) -> list[tuple[RecommendationDecisionSample, SignalGatingOutcome]]:
        scored: list[tuple[RecommendationDecisionSample, SignalGatingOutcome]] = []
        for sample in samples:
            if sample.recommendation_plan_id is None:
                continue
            outcome = outcomes.get(sample.recommendation_plan_id)
            if outcome is None:
                continue
            normalized_outcome = outcome.outcome
            if normalized_outcome in {"win", "phantom_win"}:
                scored.append((sample, SignalGatingOutcome(outcome="win", source="plan")))
            elif normalized_outcome in {"loss", "phantom_loss"}:
                scored.append((sample, SignalGatingOutcome(outcome="loss", source="plan")))
        return scored

    def _benchmark_scored_samples(
        self,
        samples: list[RecommendationDecisionSample],
        plan_scored_samples: list[tuple[RecommendationDecisionSample, SignalGatingOutcome]],
    ) -> tuple[list[tuple[RecommendationDecisionSample, SignalGatingOutcome]], dict[str, int]]:
        plan_scoreable_ids = {sample.recommendation_plan_id for sample, _ in plan_scored_samples if sample.recommendation_plan_id is not None}
        benchmarked: list[tuple[RecommendationDecisionSample, SignalGatingOutcome]] = []
        summary = {"benchmark_sample_count": 0, "benchmark_hit_count": 0, "benchmark_miss_count": 0, "benchmark_target_1d_hit_count": 0, "benchmark_target_5d_hit_count": 0, "missed_opportunity_count": 0, "good_reject_count": 0}
        for sample in samples:
            if sample.recommendation_plan_id is not None and sample.recommendation_plan_id in plan_scoreable_ids:
                continue
            benchmark = self._evaluate_benchmark(sample)
            if benchmark is None:
                continue
            summary["benchmark_sample_count"] += 1
            if benchmark.benchmark_target_1d_hit:
                summary["benchmark_target_1d_hit_count"] += 1
            if benchmark.benchmark_target_5d_hit:
                summary["benchmark_target_5d_hit_count"] += 1
            if benchmark.outcome == "win":
                summary["benchmark_hit_count"] += 1
                summary["missed_opportunity_count"] += 1
            else:
                summary["benchmark_miss_count"] += 1
                summary["good_reject_count"] += 1
            benchmarked.append((sample, benchmark))
            if (sample.recommendation_plan_id is not None or sample.ticker_signal_snapshot_id is not None) and (sample.benchmark_status != "evaluated" or sample.benchmark_direction != benchmark.benchmark_direction or sample.benchmark_target_1d_hit != benchmark.benchmark_target_1d_hit or sample.benchmark_target_5d_hit != benchmark.benchmark_target_5d_hit or sample.benchmark_max_favorable_pct != benchmark.benchmark_max_favorable_pct):
                self.samples.upsert_sample(
                    RecommendationDecisionSample(
                        id=sample.id,
                        recommendation_plan_id=sample.recommendation_plan_id,
                        ticker=sample.ticker,
                        horizon=sample.horizon,
                        action=sample.action,
                        decision_type=sample.decision_type,
                        decision_reason=sample.decision_reason,
                        shortlisted=sample.shortlisted,
                        shortlist_rank=sample.shortlist_rank,
                        shortlist_decision=sample.shortlist_decision,
                        confidence_percent=sample.confidence_percent,
                        calibrated_confidence_percent=sample.calibrated_confidence_percent,
                        effective_threshold_percent=sample.effective_threshold_percent,
                        confidence_gap_percent=sample.confidence_gap_percent,
                        setup_family=sample.setup_family,
                        transmission_bias=sample.transmission_bias,
                        context_regime=sample.context_regime,
                        review_priority=sample.review_priority,
                        review_label=sample.review_label,
                        review_notes=sample.review_notes,
                        reviewed_at=sample.reviewed_at,
                        decision_context=sample.decision_context,
                        signal_breakdown=sample.signal_breakdown,
                        evidence_summary=sample.evidence_summary,
                        benchmark_direction=benchmark.benchmark_direction,
                        benchmark_status="evaluated",
                        benchmark_target_1d_hit=benchmark.benchmark_target_1d_hit,
                        benchmark_target_5d_hit=benchmark.benchmark_target_5d_hit,
                        benchmark_max_favorable_pct=benchmark.benchmark_max_favorable_pct,
                        benchmark_evaluated_at=datetime.now(timezone.utc),
                        run_id=sample.run_id,
                        job_id=sample.job_id,
                        watchlist_id=sample.watchlist_id,
                        ticker_signal_snapshot_id=sample.ticker_signal_snapshot_id,
                    )
                )
        return benchmarked, summary

    def _evaluate_benchmark(self, sample: RecommendationDecisionSample) -> SignalGatingOutcome | None:
        direction = self._benchmark_direction(sample)
        if direction is None:
            return None
        signal_time = self._benchmark_signal_time(sample)
        if signal_time is None:
            return None
        bars = self._benchmark_bars(sample.ticker, signal_time)
        benchmark = self._benchmark_from_bars(direction, signal_time, bars)
        if benchmark is None:
            return None
        return benchmark

    def _benchmark_direction(self, sample: RecommendationDecisionSample) -> str | None:
        action = str(sample.action or "").strip().lower()
        if action in {"long", "short"}:
            return action
        snapshot = self._latest_ticker_signal_snapshot(sample)
        if snapshot is not None:
            direction = str(snapshot.direction or "").strip().lower()
            if direction in {"long", "short"}:
                return direction
        if sample.benchmark_direction in {"long", "short"}:
            return sample.benchmark_direction
        fallback_direction = self._extract_direction_from_payload(sample.signal_breakdown) or self._extract_direction_from_payload(sample.decision_context)
        return fallback_direction

    def _benchmark_signal_time(self, sample: RecommendationDecisionSample) -> datetime | None:
        snapshot = self._latest_ticker_signal_snapshot(sample)
        if snapshot is not None and snapshot.computed_at is not None:
            return snapshot.computed_at
        if sample.reviewed_at is not None:
            return sample.reviewed_at
        return sample.created_at

    def _latest_ticker_signal_snapshot(self, sample: RecommendationDecisionSample):
        if sample.ticker_signal_snapshot_id is None:
            return None
        snapshots = self.context_snapshots.list_ticker_signal_snapshots(snapshot_id=sample.ticker_signal_snapshot_id, limit=1)
        return snapshots[0] if snapshots else None

    @staticmethod
    def _extract_direction_from_payload(payload: dict[str, object]) -> str | None:
        for key in ("benchmark_direction", "direction", "signal_direction", "bias"):
            value = payload.get(key)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"long", "short"}:
                    return normalized
        return None

    def _benchmark_bars(self, ticker: str, signal_time: datetime):
        timeframes = ("1m", "1d")
        window_start = signal_time - timedelta(days=7)
        window_end = signal_time + timedelta(days=5)
        for timeframe in timeframes:
            bars = self.market_data.list_bars(ticker=ticker, timeframe=timeframe, start_at=window_start, end_at=window_end, limit=5000)
            if bars:
                return bars
        return []

    @staticmethod
    def _benchmark_from_bars(direction: str, signal_time: datetime, bars: list) -> SignalGatingOutcome | None:
        baseline = None
        future_bars = []
        for bar in bars:
            bar_time = bar.bar_time
            if bar_time is None:
                continue
            if bar_time <= signal_time:
                baseline = bar
                continue
            future_bars.append(bar)
        if baseline is None or not future_bars:
            return None
        base_price = baseline.close_price
        if base_price <= 0:
            return None
        one_day_end = signal_time + timedelta(days=1)
        five_day_end = signal_time + timedelta(days=5)
        one_day_hit = False
        five_day_hit = False
        max_favorable = 0.0
        for bar in future_bars:
            bar_time = bar.bar_time
            if bar_time is None:
                continue
            if direction == "long":
                favorable_pct = ((bar.high_price - base_price) / base_price) * 100.0
            else:
                favorable_pct = ((base_price - bar.low_price) / base_price) * 100.0
            if favorable_pct > max_favorable:
                max_favorable = favorable_pct
            if bar_time <= one_day_end and favorable_pct >= 2.0:
                one_day_hit = True
            if bar_time <= five_day_end and favorable_pct >= 5.0:
                five_day_hit = True
        return SignalGatingOutcome(
            outcome="win" if (one_day_hit or five_day_hit) else "loss",
            source="benchmark",
            benchmark_direction=direction,
            benchmark_target_1d_hit=one_day_hit,
            benchmark_target_5d_hit=five_day_hit,
            benchmark_max_favorable_pct=round(max_favorable, 4),
        )

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
        samples: list[tuple[RecommendationDecisionSample, SignalGatingOutcome]],
        config: SignalGatingTuningConfig,
        base_threshold: float,
    ) -> EvaluatedCandidate:
        selected_count = 0
        resolved_selected_count = 0
        benchmark_selected_count = 0
        benchmark_hit_count = 0
        benchmark_miss_count = 0
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
            is_win = outcome.outcome == "win"
            is_loss = outcome.outcome == "loss"
            if outcome.source == "benchmark" and selected:
                benchmark_selected_count += 1
                if is_win:
                    benchmark_hit_count += 1
                elif is_loss:
                    benchmark_miss_count += 1
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
            benchmark_selected_count=benchmark_selected_count,
            benchmark_hit_count=benchmark_hit_count,
            benchmark_miss_count=benchmark_miss_count,
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
        limit: int | None,
        apply: bool,
        sample_window_mode: str,
        latest_applied_run_completed_at: datetime | None,
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
            "sample_window_mode": sample_window_mode,
            "latest_applied_run_completed_at": latest_applied_run_completed_at.isoformat() if latest_applied_run_completed_at else None,
        }
