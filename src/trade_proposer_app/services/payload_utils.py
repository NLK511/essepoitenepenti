from __future__ import annotations

import math
from typing import Any


DEFAULT_SUMMARY_METHOD = "price_only"
DEFAULT_SUMMARY_TEXT = "No usable news articles were returned for this run."


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
