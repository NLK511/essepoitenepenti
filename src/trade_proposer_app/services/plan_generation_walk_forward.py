from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from trade_proposer_app.domain.models import PlanGenerationWalkForwardSlice, PlanGenerationWalkForwardSummary
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config


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
        if not records:
            raise ValueError("no eligible records available for plan-generation walk-forward validation")

        lookback_days = max(30, int(lookback_days))
        validation_days = max(7, int(validation_days))
        step_days = max(1, int(step_days))
        min_validation_resolved = max(1, int(min_validation_resolved))

        records.sort(key=lambda item: item.plan.computed_at)
        end_time = self._normalize_datetime(records[-1].plan.computed_at) or datetime.now(timezone.utc)
        start_time = max(self._normalize_datetime(records[0].plan.computed_at) or end_time, end_time - timedelta(days=lookback_days))

        slices: list[PlanGenerationWalkForwardSlice] = []
        candidate_wins = 0
        baseline_wins = 0
        ties = 0
        candidate_win_rate_deltas: list[float] = []
        candidate_expected_value_deltas: list[float] = []
        qualified_slices = 0

        current = start_time
        index = 0
        while current + timedelta(days=validation_days) <= end_time:
            index += 1
            window_end = current + timedelta(days=validation_days)
            slice_records = [record for record in records if current <= self._normalize_datetime(record.plan.computed_at) < window_end]
            baseline_eval = self._score_slice(slice_records, baseline_config)
            candidate_eval = self._score_slice(slice_records, candidate_config)
            resolved_count = candidate_eval.actionable_count
            is_qualified = resolved_count >= min_validation_resolved and baseline_eval.actionable_count >= min_validation_resolved
            if is_qualified:
                qualified_slices += 1
                candidate_win_rate = candidate_eval.win_rate_percent
                baseline_win_rate = baseline_eval.win_rate_percent
                if candidate_win_rate is not None and baseline_win_rate is not None:
                    delta_win = round(candidate_win_rate - baseline_win_rate, 2)
                    candidate_win_rate_deltas.append(delta_win)
                    if delta_win > 0:
                        candidate_wins += 1
                    elif delta_win < 0:
                        baseline_wins += 1
                    else:
                        ties += 1
                else:
                    delta_win = None
                delta_ev = round(candidate_eval.expected_value - baseline_eval.expected_value, 4)
                candidate_expected_value_deltas.append(delta_ev)
            else:
                delta_win = None
                delta_ev = None

            slices.append(
                PlanGenerationWalkForwardSlice(
                    slice_index=index,
                    window_label=f"{current.date().isoformat()} → {window_end.date().isoformat()}",
                    computed_after=current,
                    computed_before=window_end,
                    evaluated_after=current,
                    evaluated_before=window_end,
                    total_records=len(slice_records),
                    resolved_records=resolved_count,
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

        average_win_rate_delta = round(sum(candidate_win_rate_deltas) / len(candidate_win_rate_deltas), 2) if candidate_win_rate_deltas else None
        average_expected_value_delta = round(sum(candidate_expected_value_deltas) / len(candidate_expected_value_deltas), 4) if candidate_expected_value_deltas else None
        promotion_recommended = self._promotion_recommended(
            qualified_slices=qualified_slices,
            candidate_wins=candidate_wins,
            baseline_wins=baseline_wins,
            ties=ties,
            average_win_rate_delta=average_win_rate_delta,
            average_expected_value_delta=average_expected_value_delta,
            slices=slices,
        )
        rationale = self._rationale(
            qualified_slices=qualified_slices,
            candidate_wins=candidate_wins,
            baseline_wins=baseline_wins,
            ties=ties,
            average_win_rate_delta=average_win_rate_delta,
            average_expected_value_delta=average_expected_value_delta,
            promotion_recommended=promotion_recommended,
        )
        return PlanGenerationWalkForwardSummary(
            total_slices=len(slices),
            lookback_days=lookback_days,
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_validation_resolved,
            candidate_label=candidate_label,
            baseline_label=baseline_label,
            qualified_slices=qualified_slices,
            candidate_wins=candidate_wins,
            baseline_wins=baseline_wins,
            ties=ties,
            average_win_rate_delta=average_win_rate_delta,
            average_expected_value_delta=average_expected_value_delta,
            promotion_recommended=promotion_recommended,
            promotion_rationale=rationale,
            slices=slices,
        )

    def _eligible_records(self, *, ticker: str | None, setup_family: str | None, limit: int | None):
        return self.tuning_service._eligible_records(ticker=ticker, setup_family=setup_family, limit=limit)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _score_slice(self, records, config: dict[str, float]) -> _SliceEvaluation:
        actionable_count, win_count, expected_value, ambiguous_count = self.tuning_service._score_records(records, config)
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
        severe_regressions = [slice_row for slice_row in slices if slice_row.sample_status == "qualified" and ((slice_row.win_rate_delta or 0.0) < -5.0 or (slice_row.expected_value_delta or 0.0) < -0.05)]
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
