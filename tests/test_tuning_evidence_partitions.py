from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from trade_proposer_app.services.tuning_evidence_partitions import (
    EvidencePartitionError,
    build_evidence_partitions,
    select_stratified_dates,
)


@dataclass
class _Plan:
    id: int
    computed_at: datetime
    ticker: str = "TEST"


@dataclass
class _Record:
    plan: _Plan


def _records(count: int) -> list[_Record]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [_Record(_Plan(index + 1, start + timedelta(days=index))) for index in range(count)]


def test_explicit_partitions_are_disjoint_and_hashed() -> None:
    partitions = build_evidence_partitions(
        _records(90),
        discovery_start=datetime(2026, 1, 1).date(),
        discovery_end=datetime(2026, 1, 30).date(),
        selection_start=datetime(2026, 1, 31).date(),
        selection_end=datetime(2026, 2, 28).date(),
        holdout_start=datetime(2026, 3, 1).date(),
        holdout_end=datetime(2026, 3, 31).date(),
    )

    ids = [
        {record.plan.id for record in partition.records}
        for partition in (
            partitions.discovery,
            partitions.selection,
            partitions.locked_holdout,
        )
    ]
    assert ids[0].isdisjoint(ids[1])
    assert ids[0].isdisjoint(ids[2])
    assert ids[1].isdisjoint(ids[2])
    assert (
        len(
            {
                partitions.discovery.record_hash,
                partitions.selection.record_hash,
                partitions.locked_holdout.record_hash,
            }
        )
        == 3
    )
    assert partitions.holdout_status == "locked"


def test_explicit_partitions_reject_overlap_and_partial_boundaries() -> None:
    with pytest.raises(EvidencePartitionError, match="all discovery"):
        build_evidence_partitions(_records(90), discovery_start=datetime(2026, 1, 1).date())

    with pytest.raises(EvidencePartitionError, match="chronological"):
        build_evidence_partitions(
            _records(90),
            discovery_start=datetime(2026, 1, 1).date(),
            discovery_end=datetime(2026, 2, 1).date(),
            selection_start=datetime(2026, 2, 1).date(),
            selection_end=datetime(2026, 2, 28).date(),
            holdout_start=datetime(2026, 3, 1).date(),
            holdout_end=datetime(2026, 3, 31).date(),
        )


def test_thin_derived_evidence_never_claims_locked_holdout() -> None:
    partitions = build_evidence_partitions(_records(30))

    assert partitions.holdout_status == "insufficient_dates_for_locked_holdout"
    assert not partitions.locked_holdout.records
    assert set(partitions.discovery.evidence_dates).isdisjoint(partitions.selection.evidence_dates)


def test_derived_partitions_and_panels_are_deterministic() -> None:
    first = build_evidence_partitions(_records(100))
    second = build_evidence_partitions(list(reversed(_records(100))))

    assert first.payload() == second.payload()
    panel_one = select_stratified_dates(first.discovery.evidence_dates, limit=12, seed=42)
    panel_two = select_stratified_dates(first.discovery.evidence_dates, limit=12, seed=42)
    assert panel_one == panel_two
    assert panel_one[0] < panel_one[-1]
