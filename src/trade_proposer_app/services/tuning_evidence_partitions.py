from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

PartitionRole = Literal["discovery", "selection", "locked_holdout"]


class EvidencePartitionError(ValueError):
    """Raised when tuning evidence windows overlap or cannot be ordered safely."""


@dataclass(frozen=True, slots=True)
class EvidencePartition:
    role: PartitionRole
    records: tuple[object, ...]
    evidence_dates: tuple[date, ...]
    start_date: date | None
    end_date: date | None
    date_hash: str
    record_hash: str
    derived: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "evidence_dates": [item.isoformat() for item in self.evidence_dates],
            "distinct_date_count": len(self.evidence_dates),
            "record_count": len(self.records),
            "date_hash": self.date_hash,
            "record_hash": self.record_hash,
            "derived": self.derived,
        }


@dataclass(frozen=True, slots=True)
class EvidencePartitions:
    discovery: EvidencePartition
    selection: EvidencePartition
    locked_holdout: EvidencePartition
    holdout_status: str
    warnings: tuple[str, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "discovery": self.discovery.payload(),
            "selection": self.selection.payload(),
            "locked_holdout": self.locked_holdout.payload(),
            "holdout_status": self.holdout_status,
            "warnings": list(self.warnings),
        }


def evidence_date(record: object) -> date:
    """Return the stable grouping date for compact plan/replay evidence."""
    plan = getattr(record, "plan", None)
    value = getattr(plan, "computed_at", None)
    if not isinstance(value, datetime):
        raise EvidencePartitionError("eligible tuning record has no computed_at evidence date")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).date()


def build_evidence_partitions(
    records: Sequence[object],
    *,
    discovery_start: date | None = None,
    discovery_end: date | None = None,
    selection_start: date | None = None,
    selection_end: date | None = None,
    holdout_start: date | None = None,
    holdout_end: date | None = None,
    allow_derived: bool = True,
    min_total_dates_for_holdout: int = 60,
    min_selection_dates: int = 20,
    min_holdout_dates: int = 20,
) -> EvidencePartitions:
    if not records:
        empty = _partition("discovery", (), derived=True)
        return EvidencePartitions(
            discovery=empty,
            selection=_partition("selection", (), derived=True),
            locked_holdout=_partition("locked_holdout", (), derived=True),
            holdout_status="insufficient_dates_for_locked_holdout",
            warnings=("no_eligible_records",),
        )

    sorted_records = tuple(
        sorted(records, key=lambda item: (evidence_date(item), _record_id(item)))
    )
    explicit_values = (
        discovery_start,
        discovery_end,
        selection_start,
        selection_end,
        holdout_start,
        holdout_end,
    )
    if any(value is not None for value in explicit_values):
        if not all(value is not None for value in explicit_values):
            raise EvidencePartitionError(
                "all discovery, selection, and holdout boundaries are required"
            )
        assert discovery_start and discovery_end and selection_start and selection_end
        assert holdout_start and holdout_end
        if not (
            discovery_start
            <= discovery_end
            < selection_start
            <= selection_end
            < holdout_start
            <= holdout_end
        ):
            raise EvidencePartitionError(
                "evidence windows must be chronological, non-overlapping, and ordered "
                "discovery → selection → holdout"
            )
        discovery = _partition(
            "discovery",
            tuple(
                item
                for item in sorted_records
                if discovery_start <= evidence_date(item) <= discovery_end
            ),
        )
        selection = _partition(
            "selection",
            tuple(
                item
                for item in sorted_records
                if selection_start <= evidence_date(item) <= selection_end
            ),
        )
        holdout = _partition(
            "locked_holdout",
            tuple(
                item
                for item in sorted_records
                if holdout_start <= evidence_date(item) <= holdout_end
            ),
        )
        if not discovery.records or not selection.records or not holdout.records:
            raise EvidencePartitionError(
                "every explicit evidence window must contain eligible records"
            )
        status = (
            "locked"
            if len(selection.evidence_dates) >= min_selection_dates
            and len(holdout.evidence_dates) >= min_holdout_dates
            else "defer_thin_holdout"
        )
        warnings = () if status == "locked" else ("explicit_windows_are_thin",)
        return EvidencePartitions(discovery, selection, holdout, status, warnings)

    if not allow_derived:
        raise EvidencePartitionError(
            "explicit evidence windows are required when derived partitions are disabled"
        )

    dates = sorted({evidence_date(item) for item in sorted_records})
    if len(dates) >= min_total_dates_for_holdout:
        discovery_cut = max(1, int(len(dates) * 0.60))
        selection_cut = max(discovery_cut + 1, int(len(dates) * 0.80))
        discovery_dates = set(dates[:discovery_cut])
        selection_dates = set(dates[discovery_cut:selection_cut])
        holdout_dates = set(dates[selection_cut:])
        status = (
            "locked"
            if len(selection_dates) >= min_selection_dates
            and len(holdout_dates) >= min_holdout_dates
            else "defer_thin_holdout"
        )
        warnings = ("partitions_derived_from_evidence_dates",)
    else:
        # Preserve a useful research-only selection slice without pretending it is a holdout.
        cut = max(1, int(len(dates) * 0.80)) if len(dates) > 1 else len(dates)
        discovery_dates = set(dates[:cut])
        selection_dates = set(dates[cut:]) or set(dates[-1:])
        discovery_dates -= selection_dates
        if not discovery_dates:
            discovery_dates = set(dates)
            selection_dates = set()
        holdout_dates = set()
        status = "insufficient_dates_for_locked_holdout"
        warnings = ("insufficient_dates_for_locked_holdout",)

    return EvidencePartitions(
        _partition(
            "discovery",
            tuple(item for item in sorted_records if evidence_date(item) in discovery_dates),
            derived=True,
        ),
        _partition(
            "selection",
            tuple(item for item in sorted_records if evidence_date(item) in selection_dates),
            derived=True,
        ),
        _partition(
            "locked_holdout",
            tuple(item for item in sorted_records if evidence_date(item) in holdout_dates),
            derived=True,
        ),
        status,
        warnings,
    )


def select_stratified_dates(dates: Sequence[date], *, limit: int, seed: int) -> tuple[date, ...]:
    """Select dates spread across the full period with deterministic seeded tie breaking."""
    unique = sorted(set(dates))
    if limit <= 0 or len(unique) <= limit:
        return tuple(unique)
    rng = random.Random(seed)
    selected: list[date] = []
    for index in range(limit):
        start = (index * len(unique)) // limit
        end = ((index + 1) * len(unique)) // limit
        bucket = unique[start : max(start + 1, end)]
        selected.append(bucket[rng.randrange(len(bucket))])
    return tuple(sorted(set(selected)))


def records_for_dates(records: Sequence[object], dates: Sequence[date]) -> tuple[object, ...]:
    allowed = set(dates)
    return tuple(item for item in records if evidence_date(item) in allowed)


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _partition(
    role: PartitionRole, records: tuple[object, ...], *, derived: bool = False
) -> EvidencePartition:
    dates = tuple(sorted({evidence_date(item) for item in records}))
    record_keys = [_record_key(item) for item in records]
    return EvidencePartition(
        role=role,
        records=records,
        evidence_dates=dates,
        start_date=dates[0] if dates else None,
        end_date=dates[-1] if dates else None,
        date_hash=stable_hash([item.isoformat() for item in dates]),
        record_hash=stable_hash(record_keys),
        derived=derived,
    )


def _record_id(record: object) -> int:
    plan = getattr(record, "plan", None)
    value = getattr(plan, "id", 0)
    return int(value or 0)


def _record_key(record: object) -> dict[str, object]:
    plan = getattr(record, "plan", None)
    return {
        "id": _record_id(record),
        "ticker": str(getattr(plan, "ticker", "")),
        "computed_at": str(getattr(plan, "computed_at", "")),
    }
