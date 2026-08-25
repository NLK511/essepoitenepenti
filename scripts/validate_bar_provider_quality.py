#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trade_proposer_app.services.brokers.etoro import EtoroClient  # noqa: E402
from trade_proposer_app.services.historical_market_data import (  # noqa: E402
    EtoroHistoricalBarProvider,
    HistoricalBarProvider,
    YahooHistoricalBarProvider,
)

DEFAULT_ETORO_BROKER_ACCOUNT_ID = "etoro-demo-main"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare bar providers without writing canonical historical_market_bars rows."
    )
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers, for example AAPL,MSFT")
    parser.add_argument("--timeframe", default="1m", choices=["1m", "5m", "15m", "30m", "1h", "1d", "1wk"])
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--primary", default="yahoo", choices=["yahoo"])
    parser.add_argument("--candidate", default="etoro", choices=["etoro"])
    parser.add_argument(
        "--broker-account-id",
        default=DEFAULT_ETORO_BROKER_ACCOUNT_ID,
        help="Broker-account credential fallback when ETORO_API_KEY/ETORO_USER_KEY are not set.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    end_at = datetime.now(timezone.utc)
    start_at = end_at - timedelta(days=max(1, args.days))
    if args.dry_run:
        artifact = {
            "status": "dry_run",
            "tickers": tickers,
            "timeframe": args.timeframe,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "primary": args.primary,
            "candidate": args.candidate,
            "credential_sources": [
                "ETORO_API_KEY/ETORO_USER_KEY",
                f"broker_account:{args.broker_account_id}",
            ],
        }
        write_artifact(args.artifact, artifact)
        print(json.dumps(artifact, indent=2, sort_keys=True))
        return 0

    credentials = resolve_etoro_credentials(
        env=os.environ,
        broker_account_id=args.broker_account_id,
    )
    primary = YahooHistoricalBarProvider()
    candidate = EtoroHistoricalBarProvider(
        client=EtoroClient(
            api_key=credentials["api_key"],
            user_key=credentials["user_key"],
        )
    )
    report = compare_providers(
        primary=primary,
        candidate=candidate,
        tickers=tickers,
        timeframe=args.timeframe,
        start_at=start_at,
        end_at=end_at,
    )
    write_artifact(args.artifact, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "failed" else 1


def resolve_etoro_credentials(
    *,
    env: Mapping[str, str],
    broker_account_id: str,
    session_factory=None,
    repository_cls=None,
) -> dict[str, str]:
    api_key = env.get("ETORO_API_KEY") or ""
    user_key = env.get("ETORO_USER_KEY") or ""
    if api_key and user_key:
        return {"api_key": api_key, "user_key": user_key, "source": "environment"}

    if session_factory is None:
        from trade_proposer_app.db import SessionLocal

        session_factory = SessionLocal
    if repository_cls is None:
        from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository

        repository_cls = BrokerAccountRepository

    session = session_factory()
    try:
        repository = repository_cls(session)
        credentials = repository.get_credentials(broker_account_id)
    finally:
        session.close()

    api_key = credentials.get("x_api_key") or credentials.get("api_key") or ""
    user_key = credentials.get("x_user_key") or credentials.get("user_key") or ""
    if api_key and user_key:
        return {
            "api_key": api_key,
            "user_key": user_key,
            "source": f"broker_account:{broker_account_id}",
        }

    raise RuntimeError(
        "Missing eToro credentials. Set ETORO_API_KEY/ETORO_USER_KEY or store "
        f"x_api_key/x_user_key on broker account {broker_account_id}."
    )


def compare_providers(
    *,
    primary: HistoricalBarProvider,
    candidate: HistoricalBarProvider,
    tickers: list[str],
    timeframe: str,
    start_at: datetime,
    end_at: datetime,
) -> dict[str, object]:
    ticker_reports: list[dict[str, object]] = []
    for ticker in tickers:
        try:
            primary_bars = primary.fetch_bars(ticker, timeframe, start_at, end_at).bars
            candidate_bars = candidate.fetch_bars(ticker, timeframe, start_at, end_at).bars
            ticker_reports.append(
                compare_bar_sets(
                    ticker=ticker,
                    timeframe=timeframe,
                    primary_provider=primary.provider_name,
                    candidate_provider=candidate.provider_name,
                    primary_bars=primary_bars,
                    candidate_bars=candidate_bars,
                )
            )
        except Exception as exc:  # noqa: BLE001
            ticker_reports.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "status": "error",
                    "error": str(exc),
                }
            )
    error_count = sum(1 for item in ticker_reports if item["status"] == "error")
    comparable = [item for item in ticker_reports if item["status"] == "compared"]
    return {
        "status": "failed" if error_count else "completed",
        "primary_provider": primary.provider_name,
        "candidate_provider": candidate.provider_name,
        "timeframe": timeframe,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "ticker_count": len(tickers),
        "error_count": error_count,
        "compared_ticker_count": len(comparable),
        "median_abs_close_diff_bps": median(
            [float(item["median_abs_close_diff_bps"]) for item in comparable if item.get("median_abs_close_diff_bps") is not None]
        ) if any(item.get("median_abs_close_diff_bps") is not None for item in comparable) else None,
        "tickers": ticker_reports,
    }


def compare_bar_sets(
    *,
    ticker: str,
    timeframe: str,
    primary_provider: str,
    candidate_provider: str,
    primary_bars,
    candidate_bars,
) -> dict[str, object]:
    primary_by_time = {bar.bar_time: bar for bar in primary_bars}
    candidate_by_time = {bar.bar_time: bar for bar in candidate_bars}
    overlap = sorted(set(primary_by_time) & set(candidate_by_time))
    diffs: list[float] = []
    invalid_candidate_ohlc = 0
    zero_candidate_volume = 0
    for bar_time in overlap:
        primary_bar = primary_by_time[bar_time]
        candidate_bar = candidate_by_time[bar_time]
        if primary_bar.close_price:
            diffs.append(abs(candidate_bar.close_price - primary_bar.close_price) / primary_bar.close_price * 10_000)
        if candidate_bar.high_price < max(candidate_bar.open_price, candidate_bar.close_price):
            invalid_candidate_ohlc += 1
        if candidate_bar.low_price > min(candidate_bar.open_price, candidate_bar.close_price):
            invalid_candidate_ohlc += 1
        if candidate_bar.volume <= 0:
            zero_candidate_volume += 1
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "status": "compared",
        "primary_provider": primary_provider,
        "candidate_provider": candidate_provider,
        "primary_bar_count": len(primary_bars),
        "candidate_bar_count": len(candidate_bars),
        "overlap_bar_count": len(overlap),
        "candidate_coverage_vs_primary": round((len(overlap) / len(primary_bars)) if primary_bars else 0.0, 4),
        "median_abs_close_diff_bps": round(median(diffs), 4) if diffs else None,
        "max_abs_close_diff_bps": round(max(diffs), 4) if diffs else None,
        "invalid_candidate_ohlc_count": invalid_candidate_ohlc,
        "zero_candidate_volume_count": zero_candidate_volume,
    }


def write_artifact(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
