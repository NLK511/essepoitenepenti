#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INTRADAY_LOOKBACK_DAYS = 7
DEFAULT_DAILY_PERIOD = "max"
DEFAULT_INTRADAY_PERIOD = "7d"


def _trimmed_split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def _flatten_json_tickers(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    tickers: list[str] = []
    for item in payload:
        if isinstance(item, str) and item.strip():
            tickers.append(item.strip().upper())
    return tickers


def discover_tickers(session) -> list[str]:
    tickers: set[str] = set()

    queries = [
        "SELECT tickers_csv FROM watchlists",
        "SELECT tickers_csv FROM jobs",
        "SELECT ticker FROM ticker_signal_snapshots WHERE ticker IS NOT NULL AND ticker <> ''",
        "SELECT ticker FROM recommendation_plans WHERE ticker IS NOT NULL AND ticker <> ''",
        "SELECT ticker FROM broker_order_executions WHERE ticker IS NOT NULL AND ticker <> ''",
        "SELECT DISTINCT ticker FROM historical_market_bars WHERE ticker IS NOT NULL AND ticker <> ''",
    ]
    for query in queries:
        for row in session.execute(text(query)):
            for value in row:
                if isinstance(value, str):
                    if query.endswith("tickers_csv FROM watchlists") or query.endswith("tickers_csv FROM jobs"):
                        tickers.update(_trimmed_split_csv(value))
                    else:
                        tickers.add(value.strip().upper())

    for row in session.execute(text("SELECT tickers_json FROM historical_replay_batches")):
        for value in row:
            if isinstance(value, str):
                tickers.update(_flatten_json_tickers(value))

    return sorted(tickers)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_downloaded_frame(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    if ticker in df.columns.get_level_values(1):
        return df.xs(ticker, axis=1, level=1)
    if ticker in df.columns.get_level_values(0):
        return df.xs(ticker, axis=1, level=0)

    standard_cols = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    for level in range(df.columns.nlevels):
        if any(col in standard_cols for col in df.columns.get_level_values(level)):
            normalized = df.copy()
            normalized.columns = normalized.columns.get_level_values(level)
            return normalized
    return df


def _create_bar(ticker: str, timeframe: str, timestamp: pd.Timestamp, row: pd.Series, *, source: str, confidence: float) -> HistoricalMarketBar | None:
    try:
        row_dict = {str(k).strip(): v for k, v in row.to_dict().items()}
        close_val = row_dict.get("Close") or row_dict.get("Adj Close")
        if close_val is None or pd.isna(close_val):
            return None

        open_val = row_dict.get("Open", close_val)
        high_val = row_dict.get("High", close_val)
        low_val = row_dict.get("Low", close_val)
        vol_val = row_dict.get("Volume", 0.0)

        bar_time = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else pd.Timestamp(timestamp).to_pydatetime()
        bar_time = _normalize_timestamp(bar_time)

        if timeframe == "1m":
            available_at = bar_time + timedelta(minutes=1)
        else:
            available_at = datetime.combine(bar_time.date(), datetime.max.time(), tzinfo=timezone.utc)

        return HistoricalMarketBar(
            ticker=ticker,
            timeframe=timeframe,
            bar_time=bar_time,
            available_at=available_at,
            open_price=float(open_val),
            high_price=float(high_val),
            low_price=float(low_val),
            close_price=float(close_val),
            volume=float(vol_val) if not pd.isna(vol_val) else 0.0,
            source=source,
            source_tier="tier_a",
            point_in_time_confidence=confidence,
            metadata_json=json.dumps(
                {
                    "provider": "yahoo",
                    "recovery": True,
                    "timeframe": timeframe,
                },
                sort_keys=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("failed to convert bar %s %s %s: %s", ticker, timeframe, timestamp, exc)
        return None


def _download_frame(ticker: str, timeframe: str, *, daily_period: str, intraday_period: str) -> pd.DataFrame:
    if timeframe == "1d":
        return yf.download(
            ticker,
            period=daily_period,
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
    if timeframe == "1m":
        return yf.download(
            ticker,
            period=intraday_period,
            interval="1m",
            progress=False,
            auto_adjust=False,
        )
    raise ValueError(f"unsupported timeframe: {timeframe}")


def recover_ticker(session, repo: HistoricalMarketDataRepository, ticker: str, *, daily_period: str, intraday_period: str) -> dict[str, object]:
    result: dict[str, object] = {
        "ticker": ticker,
        "daily_ingested": 0,
        "intraday_ingested": 0,
        "warnings": [],
    }

    for timeframe, source, confidence in (
        ("1d", "yahoo_recovery_daily", 0.95),
        ("1m", "yahoo_recovery_intraday", 1.0),
    ):
        try:
            logger.info("[%s] downloading %s bars", ticker, timeframe)
            df = _download_frame(ticker, timeframe, daily_period=daily_period, intraday_period=intraday_period)
            if df is None or df.empty:
                result["warnings"].append(f"{ticker} {timeframe}: no data returned")
                continue

            df = _normalize_downloaded_frame(ticker, df)
            bars: list[HistoricalMarketBar] = []
            for timestamp, row in df.iterrows():
                bar = _create_bar(ticker, timeframe, timestamp, row, source=source, confidence=confidence)
                if bar is not None:
                    bars.append(bar)

            if not bars:
                result["warnings"].append(f"{ticker} {timeframe}: no valid bars produced")
                continue

            ingested = repo.upsert_bars(bars)
            result_key = "daily_ingested" if timeframe == "1d" else "intraday_ingested"
            result[result_key] = int(ingested)
            logger.info("[%s] persisted %s %s bars", ticker, ingested, timeframe)
            del df
            del bars
            gc.collect()
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] failed to recover %s bars", ticker, timeframe)
            result["warnings"].append(f"{ticker} {timeframe}: {exc}")

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover historical bars from Yahoo Finance into the local database.")
    parser.add_argument("--tickers", nargs="*", default=None, help="Optional explicit tickers to recover instead of discovering them from the database.")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on how many tickers to process after discovery (0 means no cap).")
    parser.add_argument("--daily-period", default=DEFAULT_DAILY_PERIOD, help="Yahoo/yfinance period for daily bars (default: max).")
    parser.add_argument("--intraday-period", default=DEFAULT_INTRADAY_PERIOD, help="Yahoo/yfinance period for 1m bars (default: 7d).")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    logger.info("Using database URL: %s", db_url)
    engine = create_engine(db_url, future=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    try:
        with Session() as session:
            repo = HistoricalMarketDataRepository(session)
            if args.tickers:
                tickers = sorted({ticker.strip().upper() for ticker in args.tickers if ticker and ticker.strip()})
            else:
                tickers = discover_tickers(session)
            if args.limit and args.limit > 0:
                tickers = tickers[: args.limit]

            logger.info("Discovered %s tickers", len(tickers))
            if not tickers:
                logger.warning("No tickers discovered; nothing to recover")
                return 0

            totals = {"tickers": 0, "daily_ingested": 0, "intraday_ingested": 0, "warnings": 0}
            for index, ticker in enumerate(tickers, start=1):
                logger.info("[%s/%s] recovering %s", index, len(tickers), ticker)
                outcome = recover_ticker(session, repo, ticker, daily_period=args.daily_period, intraday_period=args.intraday_period)
                totals["tickers"] += 1
                totals["daily_ingested"] += int(outcome["daily_ingested"])
                totals["intraday_ingested"] += int(outcome["intraday_ingested"])
                totals["warnings"] += len(outcome["warnings"])
                for warning in outcome["warnings"]:
                    logger.warning("%s", warning)

            logger.info(
                "Recovery complete: tickers=%s daily_ingested=%s intraday_ingested=%s warnings=%s",
                totals["tickers"],
                totals["daily_ingested"],
                totals["intraday_ingested"],
                totals["warnings"],
            )
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
