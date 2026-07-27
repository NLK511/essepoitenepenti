from __future__ import annotations

import math
from typing import Any


def finite_float(value: Any) -> float | None:
    """Return a finite float, or None for missing/non-finite values."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def finite_or_default(value: Any, default: float = 0.0) -> float:
    numeric = finite_float(value)
    return default if numeric is None else numeric


def finite_ohlc(open_price: Any, high_price: Any, low_price: Any, close_price: Any) -> tuple[float, float, float, float] | None:
    values = (
        finite_float(open_price),
        finite_float(high_price),
        finite_float(low_price),
        finite_float(close_price),
    )
    if any(value is None for value in values):
        return None
    open_value, high_value, low_value, close_value = values
    assert open_value is not None
    assert high_value is not None
    assert low_value is not None
    assert close_value is not None
    return open_value, high_value, low_value, close_value
