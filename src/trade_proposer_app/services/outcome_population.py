from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


EXECUTION_OUTCOMES = {"win", "loss", "no_entry", "open", "pending"}
PHANTOM_OUTCOMES = {"phantom_win", "phantom_loss", "phantom_no_entry", "phantom_pending"}
RESOLVED_WIN_LOSS_OUTCOMES = {"win", "loss", "phantom_win", "phantom_loss"}


@dataclass(frozen=True)
class OutcomePopulationSummary:
    population: str
    row_count: int
    outcome_counts: dict[str, int]
    resolved_win_loss_count: int
    execution_count: int
    phantom_count: int
    tier_counts: dict[str, int]
    included_tiers: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "population": self.population,
            "row_count": self.row_count,
            "outcome_counts": self.outcome_counts,
            "resolved_win_loss_count": self.resolved_win_loss_count,
            "execution_count": self.execution_count,
            "phantom_count": self.phantom_count,
            "tier_counts": self.tier_counts,
            "included_tiers": self.included_tiers,
        }


def summarize_outcome_population(
    rows: Iterable[object],
    *,
    population: str,
    outcome_attr: str = "outcome",
    tier_attr: str | None = None,
) -> dict[str, object]:
    outcomes: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    row_count = 0
    execution_count = 0
    phantom_count = 0
    resolved = 0
    for row in rows:
        row_count += 1
        outcome = _get(row, outcome_attr)
        outcome_key = str(outcome or "unknown")
        outcomes[outcome_key] += 1
        if outcome_key in PHANTOM_OUTCOMES or outcome_key.startswith("phantom_"):
            phantom_count += 1
        else:
            execution_count += 1
        if outcome_key in RESOLVED_WIN_LOSS_OUTCOMES:
            resolved += 1
        if tier_attr is not None:
            tier = str(_get(row, tier_attr) or "unknown")
            tiers[tier] += 1
    return OutcomePopulationSummary(
        population=population,
        row_count=row_count,
        outcome_counts=dict(outcomes),
        resolved_win_loss_count=resolved,
        execution_count=execution_count,
        phantom_count=phantom_count,
        tier_counts=dict(tiers),
        included_tiers=sorted(tiers) if tiers else [],
    ).to_dict()


def _get(row: object, key: str) -> object:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)
