from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trade_proposer_app.services.tuning_stability import TuningStabilityEvaluator


@dataclass
class _Plan:
    id: int
    computed_at: datetime
    ticker: str = "TEST"


@dataclass
class _Record:
    plan: _Plan
    values: dict[str, float]


class _FakeTuningService:
    def _score_records(self, records, config):  # noqa: ANN001, ANN202
        name = str(config["name"])
        values = [record.values[name] for record in records]
        return len(values), sum(value > 0 for value in values), round(sum(values), 4), 0


def _records() -> list[_Record]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[_Record] = []
    for index in range(24):
        rows.append(
            _Record(
                _Plan(index + 1, start + timedelta(days=index)),
                {
                    "baseline": 0.2,
                    "lucky": 10.0 if index == 0 else -0.1,
                    "stable": 0.3,
                },
            )
        )
    return rows


def test_exceptional_date_dependency_is_rejected() -> None:
    summary = TuningStabilityEvaluator(_FakeTuningService()).evaluate(
        _records(),
        candidate_config={"name": "lucky"},
        baseline_config={"name": "baseline"},
        fold_count=6,
        min_fold_actionable=1,
    )

    assert not summary.stable
    assert summary.best_date is not None
    assert summary.best_date_positive_share_percent == 100.0
    assert "advantage_disappears_without_best_date" in summary.reasons
    assert summary.expected_value_delta_without_best_date < 0


def test_stable_candidate_survives_paired_date_and_fold_checks() -> None:
    summary = TuningStabilityEvaluator(_FakeTuningService()).evaluate(
        list(reversed(_records())),
        candidate_config={"name": "stable"},
        baseline_config={"name": "baseline"},
        fold_count=6,
        min_fold_actionable=1,
    )

    assert summary.stable
    assert summary.qualified_fold_count == 6
    assert summary.non_worse_fold_count == 6
    assert summary.expected_value_delta_without_best_date > 0
    assert summary.best_date_positive_share_percent < 35.0


def test_same_date_records_are_one_independent_observation() -> None:
    rows = _records()
    rows.append(
        _Record(
            _Plan(99, rows[0].plan.computed_at),
            {"baseline": 0.2, "lucky": 5.0, "stable": 0.3},
        )
    )
    summary = TuningStabilityEvaluator(_FakeTuningService()).evaluate(
        rows,
        candidate_config={"name": "stable"},
        baseline_config={"name": "baseline"},
        fold_count=6,
    )

    assert len(summary.dates) == 24
    assert summary.dates[0].candidate.record_count == 2
