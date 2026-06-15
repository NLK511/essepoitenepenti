from __future__ import annotations

import gc
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from trade_proposer_app.domain.models import (
    PlanGenerationWalkForwardSlice,
    PlanGenerationWalkForwardSummary,
)


@dataclass(slots=True)
class _SliceEvaluation:
    actionable_count: int
    win_count: int
    expected_value: float
    ambiguous_count: int

    @property
    def win_rate_percent(self) -> float | None:
        if self.actionable_count <= 0:
            return None
        return round((self.win_count / self.actionable_count) * 100.0, 2)


@dataclass(slots=True)
class _WalkForwardStats:
    slices: list[PlanGenerationWalkForwardSlice]
    qualified_slices: int
    candidate_wins: int
    baseline_wins: int
    ties: int
    win_rate_deltas: list[float]
    expected_value_deltas: list[float]


class _RecordWindow(Sequence):
    def __init__(self, records: Sequence, start_index: int, end_index: int) -> None:
        self.records = records
        self.start_index = max(0, start_index)
        self.end_index = max(self.start_index, end_index)

    def __len__(self) -> int:
        return self.end_index - self.start_index

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self.records[self.start_index + offset] for offset in range(start, stop, step)]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return self.records[self.start_index + index]

    def __iter__(self) -> Iterator:
        for index in range(self.start_index, self.end_index):
            yield self.records[index]


class PlanGenerationWalkForwardService:
    def __init__(self, tuning_service: object) -> None:
        self.tuning_service = tuning_service

    def summarize(
        self,
        *,
        candidate_config: dict[str, float],
        baseline_config: dict[str, float],
        candidate_label: str = "candidate",
        baseline_label: str = "baseline",
        ticker: str | None = None,
        setup_family: str | None = None,
        limit: int | None = 500,
        lookback_days: int = 365,
        validation_days: int = 90,
        step_days: int = 30,
        min_validation_resolved: int = 8,
    ) -> PlanGenerationWalkForwardSummary:
        records = self._eligible_records(ticker=ticker, setup_family=setup_family, limit=limit)
        return self.summarize_records(
            records=records,
            candidate_config=candidate_config,
            baseline_config=baseline_config,
            candidate_label=candidate_label,
            baseline_label=baseline_label,
            lookback_days=lookback_days,
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_validation_resolved,
        )

    def summarize_records(
        self,
        *,
        records: list,
        candidate_config: dict[str, float],
        baseline_config: dict[str, float],
        candidate_label: str = "candidate",
        baseline_label: str = "baseline",
        lookback_days: int = 365,
        validation_days: int = 90,
        step_days: int = 30,
        min_validation_resolved: int = 8,
    ) -> PlanGenerationWalkForwardSummary:
        if not records:
            raise ValueError(
                "no eligible records available for plan-generation walk-forward validation"
            )

        lookback_days, validation_days, step_days, min_validation_resolved = (
            self._normalized_window_inputs(
                lookback_days=lookback_days,
                validation_days=validation_days,
                step_days=step_days,
                min_validation_resolved=min_validation_resolved,
            )
        )
        records, start_time, end_time, validation_days, step_days = (
            self._prepare_walk_forward_window(
                records,
                lookback_days=lookback_days,
                validation_days=validation_days,
                step_days=step_days,
            )
        )
        stats = self._build_walk_forward_slices(
            records,
            candidate_config=candidate_config,
            baseline_config=baseline_config,
            start_time=start_time,
            end_time=end_time,
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_validation_resolved,
        )
        average_win_rate_delta = self._average_delta(stats.win_rate_deltas, precision=2)
        average_expected_value_delta = self._average_delta(stats.expected_value_deltas, precision=4)
        promotion_recommended = self._promotion_recommended(
            qualified_slices=stats.qualified_slices,
            candidate_wins=stats.candidate_wins,
            baseline_wins=stats.baseline_wins,
            ties=stats.ties,
            average_win_rate_delta=average_win_rate_delta,
            average_expected_value_delta=average_expected_value_delta,
            slices=stats.slices,
        )
        rationale = self._rationale(
            qualified_slices=stats.qualified_slices,
            candidate_wins=stats.candidate_wins,
            baseline_wins=stats.baseline_wins,
            ties=stats.ties,
            average_win_rate_delta=average_win_rate_delta,
            average_expected_value_delta=average_expected_value_delta,
            promotion_recommended=promotion_recommended,
        )
        return PlanGenerationWalkForwardSummary(
            total_slices=len(stats.slices),
            lookback_days=lookback_days,
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_validation_resolved,
            candidate_label=candidate_label,
            baseline_label=baseline_label,
            qualified_slices=stats.qualified_slices,
            candidate_wins=stats.candidate_wins,
            baseline_wins=stats.baseline_wins,
            ties=stats.ties,
            average_win_rate_delta=average_win_rate_delta,
            average_expected_value_delta=average_expected_value_delta,
            promotion_recommended=promotion_recommended,
            promotion_rationale=rationale,
            slices=stats.slices,
        )

    @staticmethod
    def _normalized_window_inputs(
        *,
        lookback_days: int,
        validation_days: int,
        step_days: int,
        min_validation_resolved: int,
    ) -> tuple[int, int, int, int]:
        return (
            max(30, int(lookback_days)),
            max(7, int(validation_days)),
            max(1, int(step_days)),
            max(1, int(min_validation_resolved)),
        )

    def _prepare_walk_forward_window(
        self,
        records: list,
        *,
        lookback_days: int,
        validation_days: int,
        step_days: int,
    ) -> tuple[list, datetime, datetime, int, int]:
        sorted_records = records if isinstance(records, list) else list(records)
        sorted_records.sort(key=lambda item: item.plan.computed_at)
        end_time = self._normalize_datetime(sorted_records[-1].plan.computed_at) or datetime.now(
            timezone.utc
        )
        start_time = max(
            self._normalize_datetime(sorted_records[0].plan.computed_at) or end_time,
            end_time - timedelta(days=lookback_days),
        )
        validation_days, step_days = self._adapt_window_sizes(
            start_time=start_time,
            end_time=end_time,
            validation_days=validation_days,
            step_days=step_days,
        )
        return sorted_records, start_time, end_time, validation_days, step_days

    def _build_walk_forward_slices(
        self,
        records: list,
        *,
        candidate_config: dict[str, float],
        baseline_config: dict[str, float],
        start_time: datetime,
        end_time: datetime,
        validation_days: int,
        step_days: int,
        min_validation_resolved: int,
    ) -> _WalkForwardStats:
        stats = _WalkForwardStats([], 0, 0, 0, 0, [], [])
        current = start_time
        index = 0
        window_start_index = 0
        window_end_index = 0
        record_count = len(records)
        while current + timedelta(days=validation_days) <= end_time:
            index += 1
            window_end = current + timedelta(days=validation_days)
            while window_start_index < record_count:
                record_time = self._normalize_datetime(
                    records[window_start_index].plan.computed_at
                ) or current
                if record_time >= current:
                    break
                window_start_index += 1
            if window_end_index < window_start_index:
                window_end_index = window_start_index
            while window_end_index < record_count:
                record_time = self._normalize_datetime(
                    records[window_end_index].plan.computed_at
                ) or window_end
                if record_time >= window_end:
                    break
                window_end_index += 1
            slice_records = _RecordWindow(records, window_start_index, window_end_index)
            baseline_eval = self._score_slice(slice_records, baseline_config)
            candidate_eval = self._score_slice(slice_records, candidate_config)
            delta_win, delta_ev, is_qualified = self._record_slice_comparison(
                stats,
                baseline_eval=baseline_eval,
                candidate_eval=candidate_eval,
                min_validation_resolved=min_validation_resolved,
            )
            stats.slices.append(
                PlanGenerationWalkForwardSlice(
                    slice_index=index,
                    window_label=f"{current.date().isoformat()} → {window_end.date().isoformat()}",
                    computed_after=current,
                    computed_before=window_end,
                    evaluated_after=current,
                    evaluated_before=window_end,
                    total_records=len(slice_records),
                    resolved_records=candidate_eval.actionable_count,
                    baseline_actionable_count=baseline_eval.actionable_count,
                    candidate_actionable_count=candidate_eval.actionable_count,
                    baseline_win_rate_percent=baseline_eval.win_rate_percent,
                    candidate_win_rate_percent=candidate_eval.win_rate_percent,
                    baseline_expected_value=round(baseline_eval.expected_value, 4),
                    candidate_expected_value=round(candidate_eval.expected_value, 4),
                    win_rate_delta=delta_win,
                    expected_value_delta=delta_ev,
                    ambiguous_count=candidate_eval.ambiguous_count + baseline_eval.ambiguous_count,
                    sample_status="qualified" if is_qualified else "thin",
                )
            )
            current += timedelta(days=step_days)
            del slice_records
            gc.collect()
        return stats

    def _record_slice_comparison(
        self,
        stats: _WalkForwardStats,
        *,
        baseline_eval: _SliceEvaluation,
        candidate_eval: _SliceEvaluation,
        min_validation_resolved: int,
    ) -> tuple[float | None, float | None, bool]:
        is_qualified = (
            candidate_eval.actionable_count >= min_validation_resolved
            and baseline_eval.actionable_count >= min_validation_resolved
        )
        if not is_qualified:
            return None, None, False
        stats.qualified_slices += 1
        delta_win = self._slice_win_rate_delta(candidate_eval, baseline_eval)
        if delta_win is not None:
            stats.win_rate_deltas.append(delta_win)
            if delta_win > 0:
                stats.candidate_wins += 1
            elif delta_win < 0:
                stats.baseline_wins += 1
            else:
                stats.ties += 1
        delta_ev = round(candidate_eval.expected_value - baseline_eval.expected_value, 4)
        stats.expected_value_deltas.append(delta_ev)
        return delta_win, delta_ev, True

    @staticmethod
    def _slice_win_rate_delta(
        candidate_eval: _SliceEvaluation, baseline_eval: _SliceEvaluation
    ) -> float | None:
        if candidate_eval.win_rate_percent is None or baseline_eval.win_rate_percent is None:
            return None
        return round(candidate_eval.win_rate_percent - baseline_eval.win_rate_percent, 2)

    @staticmethod
    def _average_delta(values: list[float], *, precision: int) -> float | None:
        return round(sum(values) / len(values), precision) if values else None

    def _eligible_records(self, *, ticker: str | None, setup_family: str | None, limit: int | None):
        return self.tuning_service._eligible_records(
            ticker=ticker, setup_family=setup_family, limit=limit
        )

    @staticmethod
    def _adapt_window_sizes(
        *, start_time: datetime, end_time: datetime, validation_days: int, step_days: int
    ) -> tuple[int, int]:
        available_days = max(1, int((end_time - start_time).total_seconds() // 86400))
        effective_validation_days = max(1, min(int(validation_days), max(1, available_days // 3)))
        effective_step_days = max(1, min(int(step_days), max(1, effective_validation_days // 3)))
        return effective_validation_days, effective_step_days

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _score_slice(self, records, config: dict[str, float]) -> _SliceEvaluation:
        actionable_count, win_count, expected_value, ambiguous_count = (
            self.tuning_service._score_records(records, config)
        )
        return _SliceEvaluation(
            actionable_count=actionable_count,
            win_count=win_count,
            expected_value=expected_value,
            ambiguous_count=ambiguous_count,
        )

    @staticmethod
    def _promotion_recommended(
        *,
        qualified_slices: int,
        candidate_wins: int,
        baseline_wins: int,
        ties: int,
        average_win_rate_delta: float | None,
        average_expected_value_delta: float | None,
        slices: list[PlanGenerationWalkForwardSlice],
    ) -> bool:
        if qualified_slices < 3:
            return False
        if average_win_rate_delta is None or average_expected_value_delta is None:
            return False
        if candidate_wins < baseline_wins:
            return False
        if candidate_wins + ties < baseline_wins:
            return False
        if average_win_rate_delta <= 0.0:
            return False
        if average_expected_value_delta <= 0.0:
            return False
        severe_regressions = [
            slice_row
            for slice_row in slices
            if slice_row.sample_status == "qualified"
            and (
                (slice_row.win_rate_delta or 0.0) < -5.0
                or (slice_row.expected_value_delta or 0.0) < -0.05
            )
        ]
        return len(severe_regressions) <= 1

    @staticmethod
    def _rationale(
        *,
        qualified_slices: int,
        candidate_wins: int,
        baseline_wins: int,
        ties: int,
        average_win_rate_delta: float | None,
        average_expected_value_delta: float | None,
        promotion_recommended: bool,
    ) -> str:
        if qualified_slices < 3:
            return "Not enough qualified slices to make a stable promotion call."
        if promotion_recommended:
            return (
                f"Candidate is ahead on {candidate_wins} of {qualified_slices} qualified slices with {ties} ties; "
                f"average win-rate delta is {average_win_rate_delta:.2f} points and average EV delta is {average_expected_value_delta:.4f}."
            )
        return (
            f"Candidate is not stable enough for promotion: {candidate_wins} wins vs {baseline_wins} baseline wins, "
            f"{ties} ties, average win-rate delta {average_win_rate_delta if average_win_rate_delta is not None else 'n/a'}, "
            f"average EV delta {average_expected_value_delta if average_expected_value_delta is not None else 'n/a'}."
        )
