"""Deploy the curated default watchlists and scheduled jobs.

Design goals for these defaults:
- 300 total equities split across U.S., Europe, and Asia/Pacific (100 per region)
- grouped by compact continent + macro-industry names
- scheduled in region-appropriate windows that are interesting for analysis
- fully staggered to avoid overlapping runs and reduce API quota spikes
"""
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
        "name": "APAC-Tech",
        "region": "Asia/Pacific",
        "macro_industry": "technology and internet platforms",
        "cron": "00 00 * * MON-FRI",
        "schedule_rationale": "Runs into the Asia open so overnight global macro and the first local platform/semiconductor reactions are visible without colliding with Europe or U.S. batches.",
        "tickers": [
            "9988.HK", "0700.HK", "9618.HK", "3690.HK", "1810.HK",
            "9984.T", "6758.T", "6501.T", "8035.T", "7974.T",
            "2330.TW", "2317.TW", "2454.TW", "2308.TW", "3711.TW",
            "3034.TW", "005930.KS", "000660.KS", "035420.KS", "035720.KS",
        ],
    },
    {
        "name": "APAC-Fin",
        "region": "Asia/Pacific",
        "macro_industry": "banks, insurers, and diversified financials",
        "cron": "30 00 * * MON-FRI",
        "schedule_rationale": "Follows the first Asia opening prints so rate-sensitive and bank-sensitive names can be scored after the initial auction noise settles.",
        "tickers": [
            "0005.HK", "1299.HK", "3988.HK", "1398.HK", "3328.HK",
            "8306.T", "8316.T", "8411.T", "8630.T", "8604.T",
            "105560.KS", "086790.KS", "055550.KS", "3231.TW", "2881.TW",
            "2882.TW", "2886.TW", "CBA.AX", "WBC.AX", "ANZ.AX",
        ],
    },
    {
        "name": "APAC-Health",
        "region": "Asia/Pacific",
        "macro_industry": "pharma, medtech, and life sciences",
        "cron": "00 01 * * MON-FRI",
        "schedule_rationale": "Sits after the earliest open because defensive healthcare usually benefits more from a cleaner read on session tone than from the very first minutes of price discovery.",
        "tickers": [
            "4502.T", "4568.T", "4519.T", "4523.T", "4578.T",
            "4507.T", "4543.T", "7741.T", "7733.T", "4901.T",
            "2269.HK", "1093.HK", "1177.HK", "207940.KS", "068270.KS",
            "CSL.AX", "RMD.AX", "COH.AX", "2359.HK", "6618.HK",
        ],
    },
    {
        "name": "APAC-Cons",
        "region": "Asia/Pacific",
        "macro_industry": "consumer, autos, transport, and brand-led demand",
        "cron": "30 01 * * MON-FRI",
        "schedule_rationale": "Scheduled once the local consumer and auto complex has enough volume to reflect demand sensitivity, travel tone, and retail-risk appetite.",
        "tickers": [
            "7203.T", "7267.T", "7269.T", "7211.T", "1211.HK",
            "2333.HK", "0175.HK", "005380.KS", "012330.KS", "000270.KS",
            "2914.T", "2502.T", "2503.T", "4452.T", "4911.T",
            "WOW.AX", "COL.AX", "QAN.AX", "CAR.AX", "CPU.AX",
        ],
    },
    {
        "name": "APAC-Cyc",
        "region": "Asia/Pacific",
        "macro_industry": "industrials, energy, materials, and trading houses",
        "cron": "00 02 * * MON-FRI",
        "schedule_rationale": "Runs after the first hour so commodity and heavy-industrial names can absorb overnight macro, China-linked demand, and early futures moves without overlapping other regions.",
        "tickers": [
            "BHP.AX", "RIO.AX", "FMG.AX", "WDS.AX", "STO.AX",
            "0883.HK", "0857.HK", "0386.HK", "1605.T", "5020.T",
            "5019.T", "7011.T", "6367.T", "6273.T", "6301.T",
            "8001.T", "8002.T", "8053.T", "8058.T", "1101.TW",
        ],
    },
    {
        "name": "EU-Tech",
        "region": "Europe",
        "macro_industry": "software, semis, payments, and telecom-tech platforms",
        "cron": "00 07 * * MON-FRI",
        "schedule_rationale": "Starts near the European cash open so the list catches open-driven repricing in semis, enterprise software, and payment-sensitive names before the broader midday cycle.",
        "tickers": [
            "ASML.AS", "SAP.DE", "ADYEN.AS", "PRX.AS", "IFX.DE",
            "NOKIA.HE", "ERIC-B.ST", "STM.PA", "BEI.DE", "LOGN.SW",
            "TEMN.SW", "ASM.AS", "WKL.AS", "S92.DE", "DHER.DE",
            "DSY.PA", "WLN.PA", "TELIA.ST", "KPN.AS", "AMS.MC",
        ],
    },
    {
        "name": "EU-Fin",
        "region": "Europe",
        "macro_industry": "banks, insurers, exchanges, and asset managers",
        "cron": "30 07 * * MON-FRI",
        "schedule_rationale": "European financials are most informative once rates, sovereign spreads, and open auction pressure have started to settle, so this run follows the first open burst.",
        "tickers": [
            "HSBA.L", "SAN.MC", "BNP.PA", "ALV.DE", "UBSG.SW",
            "ISP.MI", "BBVA.MC", "INGA.AS", "ACA.PA", "BARC.L",
            "DBK.DE", "KBC.BR", "NWG.L", "CABK.MC", "UCG.MI",
            "MUV2.DE", "ZURN.SW", "LGEN.L", "PRU.L", "BMED.MI",
        ],
    },
    {
        "name": "EU-Health",
        "region": "Europe",
        "macro_industry": "pharma, diagnostics, medtech, and healthcare equipment",
        "cron": "00 08 * * MON-FRI",
        "schedule_rationale": "Healthcare is staggered after tech and banks because it is usually more useful to score once the market has revealed whether it wants defense, growth, or policy-sensitive rotation.",
        "tickers": [
            "NOVO-B.CO", "ROG.SW", "NOVN.SW", "AZN.L", "GSK.L",
            "SAN.PA", "BAYN.DE", "ALC.SW", "UCB.BR", "FRE.DE",
            "SHL.DE", "QIA.DE", "GN.CO", "DEMANT.CO", "GMAB.CO",
            "SRT3.DE", "PHIA.AS", "ALM.MC", "ORNBV.HE", "GETI-B.ST",
        ],
    },
    {
        "name": "EU-Cons",
        "region": "Europe",
        "macro_industry": "consumer staples, luxury, beverage, and retail demand",
        "cron": "30 08 * * MON-FRI",
        "schedule_rationale": "Consumer and luxury names are checked once Europe has a cleaner macro and FX read, which tends to produce more useful demand-sensitive analysis than an immediate open scan.",
        "tickers": [
            "MC.PA", "OR.PA", "NESN.SW", "ABI.BR", "DGE.L",
            "ULVR.L", "RI.PA", "KER.PA", "ADS.DE", "HEN3.DE",
            "RKT.L", "CCH.L", "HEIA.AS", "BN.PA", "FERG.L",
            "BATS.L", "IMB.L", "ZAL.DE", "AUTO1.DE", "JDW.L",
        ],
    },
    {
        "name": "EU-Cyc",
        "region": "Europe",
        "macro_industry": "industrials, energy, autos, chemicals, and materials",
        "cron": "00 09 * * MON-FRI",
        "schedule_rationale": "Cyclicals run after the earlier Europe groups because commodity, industrial, and auto names usually react best once the continental macro tape and sector leadership are clearer.",
        "tickers": [
            "SHEL.L", "BP.L", "TTE.PA", "ENI.MI", "EQNR.OL",
            "RIO.L", "GLEN.L", "AAL.L", "HOLN.SW", "CRH.L",
            "HEI.DE", "SY1.DE", "BAS.DE", "SIKA.SW", "AKZA.AS",
            "VOW3.DE", "MBG.DE", "BMW.DE", "AIR.PA", "SU.PA",
        ],
    },
    {
        "name": "US-Tech",
        "region": "United States",
        "macro_industry": "software, platforms, cloud, and internet growth",
        "cron": "00 13 * * MON-FRI",
        "schedule_rationale": "Runs into the U.S. pre-open / early risk window so the watchlist can react to overnight news, futures positioning, and large-cap tech tone before the rest of the U.S. groups.",
        "tickers": [
            "AAPL", "MSFT", "GOOGL", "META", "AMZN",
            "NFLX", "CRM", "ORCL", "ADBE", "NOW",
            "INTU", "PANW", "CRWD", "SNOW", "DDOG",
            "MDB", "TEAM", "ZS", "UBER", "ABNB",
        ],
    },
    {
        "name": "US-Fin",
        "region": "United States",
        "macro_industry": "banks, brokers, exchanges, and insurers",
        "cron": "30 13 * * MON-FRI",
        "schedule_rationale": "U.S. financials follow tech so rate-sensitive and credit-sensitive names can be scored once premarket yields and opening futures direction are more visible.",
        "tickers": [
            "JPM", "BAC", "WFC", "C", "GS",
            "MS", "BLK", "SCHW", "PNC", "USB",
            "COF", "AXP", "BK", "TFC", "CME",
            "ICE", "SPGI", "CB", "AIG", "MMC",
        ],
    },
    {
        "name": "US-Health",
        "region": "United States",
        "macro_industry": "pharma, managed care, medtech, and providers",
        "cron": "00 14 * * MON-FRI",
        "schedule_rationale": "Healthcare is placed after the initial U.S. open sequence because the first 30 to 60 minutes usually reveal whether the tape prefers defense or high-beta growth.",
        "tickers": [
            "LLY", "UNH", "JNJ", "ABBV", "MRK",
            "PFE", "TMO", "ABT", "DHR", "AMGN",
            "GILD", "BMY", "MDT", "ISRG", "SYK",
            "BSX", "CI", "CVS", "HCA", "REGN",
        ],
    },
    {
        "name": "US-Cons",
        "region": "United States",
        "macro_industry": "consumer staples, telecom, media, and household demand",
        "cron": "30 14 * * MON-FRI",
        "schedule_rationale": "Consumer and defensive demand names are checked after financials and healthcare so the run sees whether the market is rotating toward safety, staples, or communications defensives.",
        "tickers": [
            "WMT", "COST", "PG", "KO", "PEP",
            "MCD", "NKE", "HD", "LOW", "SBUX",
            "DIS", "CMCSA", "TMUS", "T", "VZ",
            "PM", "MO", "CL", "KMB", "GIS",
        ],
    },
    {
        "name": "US-Cyc",
        "region": "United States",
        "macro_industry": "industrials, energy, materials, and transport cyclicals",
        "cron": "00 15 * * MON-FRI",
        "schedule_rationale": "Placed last in the U.S. block so industrial, transport, and energy names can incorporate the clearest read on open leadership, crude tone, and macro risk appetite while still avoiding overlap.",
        "tickers": [
            "CAT", "DE", "GE", "HON", "RTX",
            "UNP", "UPS", "BA", "ETN", "MMM",
            "XOM", "CVX", "COP", "SLB", "EOG",
            "OXY", "MPC", "PSX", "KMI", "FCX",
        ],
    },
]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logging.info("Deploying curated default watchlists and jobs")

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
    total = 0
    for spec in specs:
        normalized = _normalize_tickers(spec["tickers"])
        if len(normalized) != len(spec["tickers"]):
            raise ValueError(f"watchlist '{spec['name']}' contains empty or duplicate tickers")
        total += len(normalized)
        for ticker in normalized:
            if ticker in seen:
                raise ValueError(
                    f"ticker {ticker} is defined in both '{seen[ticker]}' and '{spec['name']}'"
                )
            seen[ticker] = spec["name"]

    if total != 300:
        raise ValueError(f"expected 300 seeded tickers across all default watchlists, found {total}")


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
