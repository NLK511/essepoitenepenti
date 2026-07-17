from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median

from trade_proposer_app.services.tuning_evidence_partitions import evidence_date


@dataclass(frozen=True, slots=True)
class ScoreAggregate:
    record_count: int
    actionable_count: int
    win_count: int
    expected_value_total: float
    ambiguous_count: int

    @property
    def win_rate_percent(self) -> float | None:
        if self.actionable_count <= 0:
            return None
        return round(self.win_count / self.actionable_count * 100.0, 4)

    @property
    def expected_value_per_actionable(self) -> float | None:
        if self.actionable_count <= 0:
            return None
        return round(self.expected_value_total / self.actionable_count, 6)

    def payload(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "actionable_count": self.actionable_count,
            "win_count": self.win_count,
            "loss_count": max(0, self.actionable_count - self.win_count),
            "win_rate_percent": self.win_rate_percent,
            "expected_value_total": round(self.expected_value_total, 4),
            "expected_value_per_actionable": self.expected_value_per_actionable,
            "ambiguous_count": self.ambiguous_count,
        }


@dataclass(frozen=True, slots=True)
class DateComparison:
    evidence_date: date
    candidate: ScoreAggregate
    baseline: ScoreAggregate

    @property
    def expected_value_delta(self) -> float:
        return round(self.candidate.expected_value_total - self.baseline.expected_value_total, 4)

    @property
    def win_rate_delta(self) -> float | None:
        if self.candidate.win_rate_percent is None or self.baseline.win_rate_percent is None:
            return None
        return round(self.candidate.win_rate_percent - self.baseline.win_rate_percent, 4)

    def payload(self) -> dict[str, object]:
        return {
            "date": self.evidence_date.isoformat(),
            "candidate": self.candidate.payload(),
            "baseline": self.baseline.payload(),
            "expected_value_delta": self.expected_value_delta,
            "win_rate_delta": self.win_rate_delta,
        }


@dataclass(frozen=True, slots=True)
class FoldComparison:
    index: int
    start_date: date
    end_date: date
    candidate: ScoreAggregate
    baseline: ScoreAggregate
    qualified: bool
    thin_reason: str | None

    @property
    def expected_value_delta(self) -> float:
        return round(self.candidate.expected_value_total - self.baseline.expected_value_total, 4)

    @property
    def win_rate_delta(self) -> float | None:
        if self.candidate.win_rate_percent is None or self.baseline.win_rate_percent is None:
            return None
        return round(self.candidate.win_rate_percent - self.baseline.win_rate_percent, 4)

    def payload(self) -> dict[str, object]:
        return {
            "fold_index": self.index,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "candidate": self.candidate.payload(),
            "baseline": self.baseline.payload(),
            "win_rate_delta": self.win_rate_delta,
            "expected_value_delta": self.expected_value_delta,
            "qualified": self.qualified,
            "thin_reason": self.thin_reason,
        }


@dataclass(frozen=True, slots=True)
class StabilitySummary:
    candidate: ScoreAggregate
    baseline: ScoreAggregate
    dates: tuple[DateComparison, ...]
    folds: tuple[FoldComparison, ...]
    qualified_fold_count: int
    positive_fold_count: int
    non_worse_fold_count: int
    negative_fold_count: int
    median_win_rate_delta: float | None
    worst_win_rate_delta: float | None
    median_expected_value_delta: float | None
    worst_expected_value_delta: float | None
    best_date: date | None
    best_date_positive_share_percent: float | None
    top_three_positive_share_percent: float | None
    win_rate_delta_without_best_date: float | None
    expected_value_delta_without_best_date: float | None
    leave_one_date_out_worst_expected_value_delta: float | None
    stable: bool
    reasons: tuple[str, ...]

    def payload(
        self, *, include_dates: bool = False, include_folds: bool = True
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate": self.candidate.payload(),
            "baseline": self.baseline.payload(),
            "distinct_date_count": len(self.dates),
            "qualified_fold_count": self.qualified_fold_count,
            "positive_fold_count": self.positive_fold_count,
            "non_worse_fold_count": self.non_worse_fold_count,
            "negative_fold_count": self.negative_fold_count,
            "median_win_rate_delta": self.median_win_rate_delta,
            "worst_win_rate_delta": self.worst_win_rate_delta,
            "median_expected_value_delta": self.median_expected_value_delta,
            "worst_expected_value_delta": self.worst_expected_value_delta,
            "best_date": self.best_date.isoformat() if self.best_date else None,
            "best_date_positive_share_percent": self.best_date_positive_share_percent,
            "top_three_positive_share_percent": self.top_three_positive_share_percent,
            "win_rate_delta_without_best_date": self.win_rate_delta_without_best_date,
            "expected_value_delta_without_best_date": self.expected_value_delta_without_best_date,
            "leave_one_date_out_worst_expected_value_delta": (
                self.leave_one_date_out_worst_expected_value_delta
            ),
            "stable": self.stable,
            "reasons": list(self.reasons),
        }
        if include_folds:
            payload["folds"] = [item.payload() for item in self.folds]
        if include_dates:
            payload["dates"] = [item.payload() for item in self.dates]
        return payload


class TuningStabilityEvaluator:
    """Paired candidate/baseline stability calculations grouped by market date."""

    def __init__(self, tuning_service: object) -> None:
        self.tuning_service = tuning_service
        self._baseline_cache: dict[tuple[object, ...], ScoreAggregate] = {}
        self.evidence_profile: str | None = None

    def evaluate(
        self,
        records: Sequence[object],
        *,
        candidate_config: dict[str, float],
        baseline_config: dict[str, float],
        fold_count: int = 6,
        min_fold_actionable: int = 1,
        min_qualified_folds: int = 4,
        win_rate_tolerance_pp: float = 0.25,
        best_date_share_limit_percent: float = 35.0,
        top_three_share_limit_percent: float = 65.0,
    ) -> StabilitySummary:
        grouped = _group_by_date(records)

        def candidate_score(rows: Sequence[object]) -> ScoreAggregate:
            if candidate_config == baseline_config:
                return self._score_baseline(rows, baseline_config)
            return self._score(rows, candidate_config)

        date_rows = tuple(
            DateComparison(
                evidence_date=day,
                candidate=candidate_score(day_records),
                baseline=self._score_baseline(day_records, baseline_config),
            )
            for day, day_records in grouped
        )
        candidate = candidate_score(records)
        baseline = self._score_baseline(records, baseline_config)
        folds = self._folds(
            grouped,
            candidate_config=candidate_config,
            baseline_config=baseline_config,
            fold_count=fold_count,
            min_fold_actionable=min_fold_actionable,
        )
        qualified = tuple(item for item in folds if item.qualified)
        win_deltas = [item.win_rate_delta for item in qualified if item.win_rate_delta is not None]
        ev_deltas = [item.expected_value_delta for item in qualified]
        positive = sum(1 for item in qualified if _primary_delta(item) > win_rate_tolerance_pp)
        non_worse = sum(1 for item in qualified if _primary_delta(item) >= -win_rate_tolerance_pp)
        negative = len(qualified) - non_worse

        best_row = max(
            date_rows, key=lambda item: item.candidate.expected_value_total, default=None
        )
        positive_contributions = sorted(
            (
                item.candidate.expected_value_total
                for item in date_rows
                if item.candidate.expected_value_total > 0
            ),
            reverse=True,
        )
        positive_total = sum(positive_contributions)
        best_share = (
            round(positive_contributions[0] / positive_total * 100.0, 2)
            if positive_contributions and positive_total > 0
            else None
        )
        top_three_share = (
            round(sum(positive_contributions[:3]) / positive_total * 100.0, 2)
            if positive_contributions and positive_total > 0
            else None
        )
        without_best_candidate, without_best_baseline = _without_date(date_rows, best_row)
        win_without = _win_rate_delta(without_best_candidate, without_best_baseline)
        ev_without = round(
            without_best_candidate.expected_value_total
            - without_best_baseline.expected_value_total,
            4,
        )
        loo_ev = [
            round(
                candidate.expected_value_total
                - row.candidate.expected_value_total
                - (baseline.expected_value_total - row.baseline.expected_value_total),
                4,
            )
            for row in date_rows
        ]

        reasons: list[str] = []
        required_qualified = min(max(1, min_qualified_folds), max(1, len(folds)))
        if len(qualified) < required_qualified:
            reasons.append("insufficient_qualified_folds")
        if qualified and non_worse * 2 < len(qualified):
            reasons.append("majority_of_folds_worse_than_baseline")
        if win_without is None or win_without < -win_rate_tolerance_pp:
            reasons.append("advantage_disappears_without_best_date")
        if len(positive_contributions) >= 20:
            if best_share is not None and best_share > best_date_share_limit_percent:
                reasons.append("best_date_concentration")
            if top_three_share is not None and top_three_share > top_three_share_limit_percent:
                reasons.append("top_three_date_concentration")
        elif positive_contributions:
            reasons.append("thin_positive_date_sample")
        else:
            reasons.append("no_positive_dates")

        blocking = {
            "insufficient_qualified_folds",
            "majority_of_folds_worse_than_baseline",
            "advantage_disappears_without_best_date",
            "best_date_concentration",
            "top_three_date_concentration",
            "no_positive_dates",
        }
        return StabilitySummary(
            candidate=candidate,
            baseline=baseline,
            dates=date_rows,
            folds=folds,
            qualified_fold_count=len(qualified),
            positive_fold_count=positive,
            non_worse_fold_count=non_worse,
            negative_fold_count=negative,
            median_win_rate_delta=_rounded_median(win_deltas),
            worst_win_rate_delta=round(min(win_deltas), 4) if win_deltas else None,
            median_expected_value_delta=_rounded_median(ev_deltas),
            worst_expected_value_delta=round(min(ev_deltas), 4) if ev_deltas else None,
            best_date=best_row.evidence_date if best_row else None,
            best_date_positive_share_percent=best_share,
            top_three_positive_share_percent=top_three_share,
            win_rate_delta_without_best_date=win_without,
            expected_value_delta_without_best_date=ev_without,
            leave_one_date_out_worst_expected_value_delta=round(min(loo_ev), 4) if loo_ev else None,
            stable=not any(reason in blocking for reason in reasons),
            reasons=tuple(reasons),
        )

    def _score(self, records: Sequence[object], config: dict[str, float]) -> ScoreAggregate:
        actionable, wins, expected_value, ambiguous = self.tuning_service._score_records(  # noqa: SLF001
            records, config, evidence_profile=self.evidence_profile
        )
        return ScoreAggregate(
            record_count=len(records),
            actionable_count=int(actionable),
            win_count=int(wins),
            expected_value_total=float(expected_value),
            ambiguous_count=int(ambiguous),
        )

    def _score_baseline(
        self, records: Sequence[object], config: dict[str, float]
    ) -> ScoreAggregate:
        config_key = tuple(sorted((key, str(value)) for key, value in config.items()))
        record_key = tuple(
            int(getattr(getattr(record, "plan", None), "id", 0) or id(record)) for record in records
        )
        key: tuple[object, ...] = (config_key, record_key, self.evidence_profile)
        cached = self._baseline_cache.get(key)
        if cached is None:
            cached = self._score(records, config)
            self._baseline_cache[key] = cached
        return cached

    def _folds(
        self,
        grouped: list[tuple[date, tuple[object, ...]]],
        *,
        candidate_config: dict[str, float],
        baseline_config: dict[str, float],
        fold_count: int,
        min_fold_actionable: int,
    ) -> tuple[FoldComparison, ...]:
        if not grouped:
            return ()
        count = min(max(1, fold_count), len(grouped))
        folds: list[FoldComparison] = []
        for index in range(count):
            start = (index * len(grouped)) // count
            end = ((index + 1) * len(grouped)) // count
            rows = grouped[start : max(start + 1, end)]
            records = tuple(record for _, day_records in rows for record in day_records)
            candidate = (
                self._score_baseline(records, baseline_config)
                if candidate_config == baseline_config
                else self._score(records, candidate_config)
            )
            baseline = self._score_baseline(records, baseline_config)
            qualified = (
                candidate.actionable_count >= min_fold_actionable
                and baseline.actionable_count >= min_fold_actionable
            )
            folds.append(
                FoldComparison(
                    index=index + 1,
                    start_date=rows[0][0],
                    end_date=rows[-1][0],
                    candidate=candidate,
                    baseline=baseline,
                    qualified=qualified,
                    thin_reason=None if qualified else "insufficient_actionable_records",
                )
            )
        return tuple(folds)


def _group_by_date(records: Sequence[object]) -> list[tuple[date, tuple[object, ...]]]:
    grouped: dict[date, list[object]] = {}
    for record in records:
        grouped.setdefault(evidence_date(record), []).append(record)
    return [(day, tuple(grouped[day])) for day in sorted(grouped)]


def _sum_aggregates(rows: Sequence[ScoreAggregate]) -> ScoreAggregate:
    return ScoreAggregate(
        record_count=sum(item.record_count for item in rows),
        actionable_count=sum(item.actionable_count for item in rows),
        win_count=sum(item.win_count for item in rows),
        expected_value_total=round(sum(item.expected_value_total for item in rows), 4),
        ambiguous_count=sum(item.ambiguous_count for item in rows),
    )


def _without_date(
    rows: Sequence[DateComparison], best: DateComparison | None
) -> tuple[ScoreAggregate, ScoreAggregate]:
    retained = [item for item in rows if best is None or item.evidence_date != best.evidence_date]
    return (
        _sum_aggregates([item.candidate for item in retained]),
        _sum_aggregates([item.baseline for item in retained]),
    )


def _win_rate_delta(candidate: ScoreAggregate, baseline: ScoreAggregate) -> float | None:
    if candidate.win_rate_percent is None or baseline.win_rate_percent is None:
        return None
    return round(candidate.win_rate_percent - baseline.win_rate_percent, 4)


def _primary_delta(fold: FoldComparison) -> float:
    return float(fold.win_rate_delta if fold.win_rate_delta is not None else -math.inf)


def _rounded_median(values: Sequence[float]) -> float | None:
    return round(float(median(values)), 4) if values else None
