#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository


def _parse_timestamp(value: str) -> datetime:
    normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if normalized.tzinfo is None:
        return normalized.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc)


def _session_window(value: datetime) -> tuple[datetime, datetime]:
    date = value.date()
    return (
        datetime.combine(date, time(0, 0), tzinfo=timezone.utc),
        datetime.combine(date, time(23, 59, 59), tzinfo=timezone.utc),
    )


def _download_1m(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    return yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1m",
        progress=False,
        auto_adjust=False,
    )


def _normalize_frame(ticker: str, frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame
    if ticker in frame.columns.get_level_values(1):
        return frame.xs(ticker, axis=1, level=1)
    if ticker in frame.columns.get_level_values(0):
        return frame.xs(ticker, axis=1, level=0)
    standard_cols = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    for level in range(frame.columns.nlevels):
        if any(col in standard_cols for col in frame.columns.get_level_values(level)):
            normalized = frame.copy()
            normalized.columns = normalized.columns.get_level_values(level)
            return normalized
    return frame


def _bar_from_row(ticker: str, timestamp: datetime, row: pd.Series) -> HistoricalMarketBar | None:
    row_dict = {str(key).strip(): value for key, value in row.to_dict().items()}
    close_value = row_dict.get("Close") or row_dict.get("Adj Close")
    if close_value is None or pd.isna(close_value):
        return None
    bar_time = timestamp.to_pydatetime()
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    else:
        bar_time = bar_time.astimezone(timezone.utc)
    return HistoricalMarketBar(
        ticker=ticker,
        timeframe="1m",
        bar_time=bar_time,
        available_at=bar_time + timedelta(minutes=1),
        open_price=float(row_dict.get("Open", close_value)),
        high_price=float(row_dict.get("High", close_value)),
        low_price=float(row_dict.get("Low", close_value)),
        close_price=float(close_value),
        volume=float(row_dict.get("Volume", 0.0) or 0.0),
        source="yfinance_gap_repair",
    )


def _candidate_windows(audit: dict[str, object], *, provider_window_days: int) -> list[tuple[str, datetime, datetime]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=provider_window_days)
    windows: set[tuple[str, datetime, datetime]] = set()
    for item in audit.get("diagnostics", []):
        diagnostic = item.get("diagnostic", {}) if isinstance(item, dict) else {}
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get("reason") != "internal_cache_gap":
            continue
        ticker = str(diagnostic.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        start = _parse_timestamp(str(diagnostic["required_start"]))
        end = _parse_timestamp(str(diagnostic["required_end"]))
        if start < cutoff:
            continue
        cursor = start
        while cursor.date() <= end.date():
            if cursor.weekday() < 5:
                windows.add((ticker, *_session_window(cursor)))
            cursor += timedelta(days=1)
    return sorted(windows, key=lambda item: (item[0], item[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair recent recoverable 1m gaps from a replay bar coverage audit.")
    parser.add_argument("--audit-artifact", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, default=Path("artifacts/recent-intraday-gap-repair.json"))
    parser.add_argument("--provider-window-days", type=int, default=7)
    parser.add_argument("--max-windows", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    audit = json.loads(args.audit_artifact.read_text())
    windows = _candidate_windows(audit, provider_window_days=args.provider_window_days)[: args.max_windows]
    session = SessionLocal()
    outcomes: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    try:
        repository = HistoricalMarketDataRepository(session)
        for ticker, start, end in windows:
            before = repository.count_bars(ticker=ticker, timeframe="1m", start_at=start, end_at=end)
            if args.dry_run:
                outcome = {
                    "ticker": ticker,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "before_rows": before,
                    "after_rows": before,
                    "ingested": 0,
                    "status": "dry_run",
                }
                status_counts["dry_run"] += 1
                outcomes.append(outcome)
                continue
            frame = _download_1m(ticker, start, end)
            if frame.empty:
                status = "provider_empty"
                ingested = 0
            else:
                frame = _normalize_frame(ticker, frame)
                frame = frame[(frame.index >= start) & (frame.index <= end)]
                bars = [
                    bar
                    for timestamp, row in frame.iterrows()
                    if (bar := _bar_from_row(ticker, timestamp, row)) is not None
                ]
                ingested = repository.upsert_bars(bars)
                status = "repaired" if ingested > 0 else "no_valid_bars"
            after = repository.count_bars(ticker=ticker, timeframe="1m", start_at=start, end_at=end)
            status_counts[status] += 1
            outcomes.append(
                {
                    "ticker": ticker,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "before_rows": before,
                    "after_rows": after,
                    "ingested": ingested,
                    "status": status,
                }
            )
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "audit_artifact": str(args.audit_artifact),
            "provider_window_days": args.provider_window_days,
            "window_count": len(windows),
            "status_counts": dict(status_counts),
            "outcomes": outcomes,
        }
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(json.dumps({key: payload[key] for key in payload if key != "outcomes"}, indent=2, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()
