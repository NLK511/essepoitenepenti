from __future__ import annotations

from datetime import datetime, timedelta, timezone

REVIEW_WINDOW_ALIASES: dict[str, str] = {
    "30d": "1m",
    "90d": "3m",
    "180d": "6m",
    "365d": "1y",
}

REVIEW_WINDOW_ORDER: tuple[str, ...] = ("1d", "7d", "1m", "3m", "6m", "1y", "all")


def normalize_review_window(value: str | None, *, default: str = "1d") -> str:
    normalized = str(value or default).strip().lower()
    normalized = REVIEW_WINDOW_ALIASES.get(normalized, normalized)
    return normalized if normalized in REVIEW_WINDOW_ORDER else default


def review_window_label(window: str) -> str:
    normalized = normalize_review_window(window)
    if normalized == "all":
        return "ALL"
    return normalized.upper()


def review_window_start(window: str, now: datetime | None = None) -> datetime | None:
    normalized = normalize_review_window(window)
    if normalized == "all":
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone()
    if normalized == "1d":
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight.astimezone(timezone.utc)
    days = {
        "7d": 7,
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
    }[normalized]
    return (current - timedelta(days=days)).astimezone(timezone.utc)
