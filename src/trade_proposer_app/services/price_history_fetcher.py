from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from trade_proposer_app.services.retry_utils import bounded_backoff_seconds


class PriceHistoryFetchError(Exception):
    pass


class PriceHistoryFetcher:
    def __init__(
        self,
        *,
        local_fetch: Callable[[str, datetime | None], pd.DataFrame],
        remote_fetch: Callable[[str, datetime | None], pd.DataFrame],
        persist: Callable[[str, pd.DataFrame], None],
        sleep: Callable[[float], None],
        live_attempts: int,
        live_backoff_seconds: tuple[float, ...],
        error_type: type[Exception] = PriceHistoryFetchError,
    ) -> None:
        self.local_fetch = local_fetch
        self.remote_fetch = remote_fetch
        self.persist = persist
        self.sleep = sleep
        self.live_attempts = live_attempts
        self.live_backoff_seconds = live_backoff_seconds
        self.error_type = error_type

    def fetch(self, ticker: str, *, as_of: datetime | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
        normalized_ticker = ticker.strip().upper()
        is_replay = as_of is not None
        local_history = self.local_fetch(normalized_ticker, as_of)
        local_bar_count = len(local_history)
        diagnostics: dict[str, object] = {
            "ticker": normalized_ticker,
            "mode": "replay" if is_replay else "live",
            "source": "unavailable",
            "fallback_used": False,
            "remote_attempt_count": 0,
            "remote_attempted": False,
            "remote_errors": [],
            "local_bar_count": local_bar_count,
            "selected_bar_count": 0,
            "latest_bar_time": latest_bar_time_iso(local_history),
        }
        if is_replay and not local_history.empty:
            diagnostics.update({"source": "local_replay", "selected_bar_count": local_bar_count, "fallback_used": False})
            return local_history, diagnostics

        remote_error: Exception | None = None
        remote_attempts = 1 if is_replay else self.live_attempts
        for attempt in range(remote_attempts):
            backoff = bounded_backoff_seconds(self.live_backoff_seconds, attempt, enabled=not is_replay)
            if backoff > 0:
                self.sleep(backoff)
            diagnostics["remote_attempted"] = True
            diagnostics["remote_attempt_count"] = attempt + 1
            try:
                remote_history = self.remote_fetch(normalized_ticker, as_of)
            except Exception as exc:
                remote_error = exc
                diagnostics.setdefault("remote_errors", []).append(str(exc))
                continue
            if not remote_history.empty:
                diagnostics.update({"source": "remote", "fallback_used": False, "selected_bar_count": len(remote_history), "latest_bar_time": latest_bar_time_iso(remote_history)})
                self.persist(normalized_ticker, remote_history)
                return remote_history, diagnostics
            remote_error = self.error_type(f"could not retrieve historical data for '{normalized_ticker}'")
            diagnostics.setdefault("remote_errors", []).append(str(remote_error))

        if not local_history.empty:
            diagnostics.update({"source": "local_fallback", "fallback_used": True, "selected_bar_count": local_bar_count, "latest_bar_time": latest_bar_time_iso(local_history)})
            return local_history, diagnostics
        if remote_error is not None:
            raise remote_error
        raise self.error_type(f"could not retrieve historical data for '{normalized_ticker}'")


def latest_bar_time_iso(history: pd.DataFrame) -> str | None:
    if history.empty:
        return None
    latest = history.index[-1]
    if not isinstance(latest, datetime):
        latest = pd.to_datetime(latest).to_pydatetime()
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    else:
        latest = latest.astimezone(timezone.utc)
    return latest.isoformat()
