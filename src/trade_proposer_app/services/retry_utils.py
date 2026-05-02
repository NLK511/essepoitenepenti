from __future__ import annotations

from collections.abc import Sequence


def bounded_backoff_seconds(
    schedule: Sequence[float],
    attempt_index: int,
    *,
    enabled: bool = True,
) -> float:
    if not enabled or not schedule:
        return 0.0
    return schedule[min(attempt_index, len(schedule) - 1)]
