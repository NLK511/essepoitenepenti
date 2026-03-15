"""Deploy the suggested session-aligned watchlists and scheduled jobs."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import JobRecord, WatchlistRecord
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.repositories.jobs import JobRepository


WATCHLIST_SPECS = [
    {
        "name": "U.S. Tech Momentum",
        "tickers": [
            "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "CRM", "ORCL", "PYPL",
            "SHOP", "SAPH", "INTC", "AVGO", "AMD", "NOW",
        ],
        "cron": "30 14 * * MON-FRI",
    },
    {
        "name": "European Midday Reversion",
        "tickers": [
            "ASML", "SAN", "BP", "SHEL", "LVMUY", "OR", "DAI", "ING", "UBS", "RIO",
            "AIR", "SIEGY", "BASFY", "ENGIY", "NOVN",
        ],
        "cron": "30 11 * * MON-FRI",
    },
    {
        "name": "Asia-Pacific Opening Range",
        "tickers": [
            "0700.HK", "0005.HK", "9984.T", "7203.T", "6758.T", "9432.T", "2914.T", "8035.T",
            "BHP.AX", "RIO.AX", "CSL.AX", "WES.AX", "A2M.AX", "3888.HK", "3690.HK",
        ],
        "cron": "15 0 * * MON-FRI",
    },
    {
        "name": "Macro News & Rates Pulse",
        "tickers": [
            "SPY", "QQQ", "TLT", "IEF", "GLD", "USO", "VNQ", "XLF", "XLE", "XLK", "UUP",
            "TIP", "IWM", "XLY", "XLI",
        ],
        "cron": "30 12 * * MON-FRI",
    },
    {
        "name": "Energy & Commodities Morning Sweep",
        "tickers": [
            "CVX", "COP", "OXY", "SLB", "HAL", "KMI", "XOM", "BKR", "EQT", "NBL", "NOV",
            "TALO", "CHK", "PE", "VLO",
        ],
        "cron": "00 15 * * MON-FRI",
    },
    {
        "name": "AI & Automation Leaders",
        "tickers": [
            "LRCX", "CDNS", "SNPS", "AMAT", "CRWD", "PANW", "FTNT", "ZS", "MDB", "OKTA",
            "TEAM", "MTTR", "SNOW", "ADSK", "PLTR",
        ],
        "cron": "45 13 * * MON-FRI",
    },
    {
        "name": "Healthcare & Biotech Defensive Shift",
        "tickers": [
            "JNJ", "PFE", "MRK", "LLY", "ABBV", "BMY", "AMGN", "GILD", "ZTS", "UNH", "TDOC",
            "HCA", "ILMN", "MRNA", "REGN",
        ],
        "cron": "00 17 * * MON-FRI",
    },
]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logging.info("Deploying suggested watchlists and jobs")

    _validate_watchlist_specs(WATCHLIST_SPECS)

    with SessionLocal() as session:
        watchlist_repo = WatchlistRepository(session)
        job_repo = JobRepository(session)

        for spec in WATCHLIST_SPECS:
            normalized = _normalize_tickers(spec["tickers"])
            watchlist_record = _ensure_watchlist(session, watchlist_repo, spec["name"], normalized)
            job_name = f"Auto: {spec['name']}"
            _ensure_job(session, job_repo, watchlist_record, job_name, spec["cron"])

    logging.info("Deployment complete")


def _validate_watchlist_specs(specs: list[dict[str, object]]) -> None:
    seen: dict[str, str] = {}
    for spec in specs:
        normalized = _normalize_tickers(spec["tickers"])
        for ticker in normalized:
            if ticker in seen:
                raise ValueError(
                    f"ticker {ticker} is defined in both '{seen[ticker]}' and '{spec['name']}'"
                )
            seen[ticker] = spec["name"]


def _normalize_tickers(tickers: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for ticker in tickers:
        cleaned = ticker.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _ensure_watchlist(
    session, repo: WatchlistRepository, name: str, tickers: list[str]
) -> WatchlistRecord:
    record = _find_watchlist_record(session, name)
    duplicates = _find_duplicate_tickers(session, tickers, exclude_id=record.id if record else None)
    if duplicates:
        raise ValueError(
            f"could not deploy watchlist '{name}' because these tickers are already assigned: {', '.join(duplicates)}"
        )

    if record:
        current = [ticker for ticker in record.tickers_csv.split(",") if ticker]
        if current != tickers:
            record.tickers_csv = ",".join(tickers)
            session.commit()
            session.refresh(record)
            logging.info("Updated watchlist '%s'", name)
        else:
            logging.info("Watchlist '%s' already configured", name)
        return record

    watchlist = repo.create(name, tickers)
    logging.info("Created watchlist '%s'", watchlist.name)
    return _find_watchlist_record(session, watchlist.name)


def _ensure_job(
    session,
    repo: JobRepository,
    watchlist: WatchlistRecord,
    job_name: str,
    cron: str,
) -> None:
    record = session.scalars(select(JobRecord).where(JobRecord.name == job_name)).first()
    if record:
        repo.update(
            job_id=record.id,
            name=job_name,
            tickers=[],
            schedule=cron,
            enabled=True,
            watchlist_id=watchlist.id,
        )
        logging.info("Updated job '%s'", job_name)
    else:
        repo.create(
            name=job_name,
            tickers=[],
            schedule=cron,
            enabled=True,
            watchlist_id=watchlist.id,
        )
        logging.info("Created job '%s'", job_name)


def _find_watchlist_record(session, name: str) -> WatchlistRecord | None:
    return session.scalars(select(WatchlistRecord).where(WatchlistRecord.name == name)).first()


def _find_duplicate_tickers(
    session,
    tickers: Iterable[str],
    exclude_id: int | None = None,
) -> list[str]:
    duplicates: list[str] = []
    rows = session.scalars(select(WatchlistRecord)).all()
    interested = set(tickers)
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        existing = {ticker for ticker in row.tickers_csv.split(",") if ticker}
        for ticker in interested:
            if ticker in existing and ticker not in duplicates:
                duplicates.append(ticker)
    return duplicates


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Failed to deploy watchlists")
        raise
