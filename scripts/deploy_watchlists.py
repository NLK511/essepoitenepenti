"""Deploy the curated default watchlists and scheduled jobs.

Design goals for these defaults:
- 750 total equities split across U.S., Europe, and Asia/Pacific (250 per region)
- grouped by compact continent + macro-industry names
- scheduled in region-appropriate opening windows that are interesting for analysis
- fully staggered in 10-minute increments to avoid overlapping runs and reduce API quota spikes
- include a small set of daily macro and industry refresh jobs in the quiet windows between regional equity batches
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from sqlalchemy import select
    from trade_proposer_app.db import SessionLocal
    from trade_proposer_app.domain.enums import JobType
    from trade_proposer_app.persistence.models import JobRecord, WatchlistRecord
    from trade_proposer_app.repositories.watchlists import WatchlistRepository
    from trade_proposer_app.repositories.jobs import JobRepository
except ModuleNotFoundError:  # pragma: no cover - allows importing WATCHLIST_SPECS without optional runtime deps
    select = None
    SessionLocal = None
    JobType = None
    JobRecord = None
    WatchlistRecord = None
    WatchlistRepository = None
    JobRepository = None


WATCHLIST_SPECS = [
    {
        "name": "APAC-Tech",
        "region": "Asia/Pacific",
        "macro_industry": "technology and internet platforms",
        "cron": "00 00 * * MON-FRI",
        "schedule_rationale": "Runs at the Asia open; the default batch stays in the opening window and leaves 10 minutes before the next regional watchlist job.",
        "tickers": [
            "9988.HK", "0700.HK", "9618.HK", "3690.HK", "1810.HK", "9984.T", "6758.T", "6501.T", "8035.T", "7974.T",
            "2330.TW", "2317.TW", "2454.TW", "2308.TW", "3711.TW", "3034.TW", "005930.KS", "000660.KS", "035420.KS", "035720.KS",
            "6701.T", "6702.T", "6723.T", "6857.T", "6981.T", "6976.T", "6954.T", "4689.T", "4755.T", "2413.T",
            "9888.HK", "2015.HK", "9866.HK", "9868.HK", "0268.HK", "0762.HK", "0728.HK", "0941.HK", "2303.TW", "2382.TW",
            "3231.TW", "2357.TW", "2379.TW", "3008.TW", "066570.KS", "018260.KS", "XRO.AX", "WTC.AX", "REA.AX", "TNE.AX"
        ],
    },
    {
        "name": "APAC-Fin",
        "region": "Asia/Pacific",
        "macro_industry": "banks, insurers, and diversified financials",
        "cron": "10 00 * * MON-FRI",
        "schedule_rationale": "Follows the first Asia open with a 10-minute gap so rate-sensitive and bank-sensitive names are scored after the initial auction noise settles.",
        "tickers": [
            "0005.HK", "1299.HK", "3988.HK", "1398.HK", "3328.HK", "8306.T", "8316.T", "8411.T", "8630.T", "8604.T",
            "105560.KS", "086790.KS", "055550.KS", "2881.TW", "2882.TW", "2886.TW", "CBA.AX", "WBC.AX", "ANZ.AX", "NAB.AX",
            "8591.T", "8766.T", "8725.T", "8750.T", "8253.T", "8473.T", "2318.HK", "2628.HK", "0939.HK", "1658.HK",
            "3968.HK", "2891.TW", "2884.TW", "2885.TW", "5880.TW", "024110.KS", "003550.KS", "MQG.AX", "SUN.AX", "IAG.AX",
            "QBE.AX", "AMP.AX", "BEN.AX", "BOQ.AX", "2890.TW", "2880.TW", "2883.TW", "2887.TW", "2892.TW", "032830.KS"
        ],
    },
    {
        "name": "APAC-Health",
        "region": "Asia/Pacific",
        "macro_industry": "pharma, medtech, and life sciences",
        "cron": "20 00 * * MON-FRI",
        "schedule_rationale": "Stays inside the Asia opening window with a 10-minute gap after the prior job so defensive healthcare gets a cleaner read on session tone.",
        "tickers": [
            "4502.T", "4568.T", "4519.T", "4523.T", "4578.T", "4507.T", "4543.T", "7741.T", "7733.T", "4901.T",
            "2269.HK", "1093.HK", "1177.HK", "207940.KS", "068270.KS", "CSL.AX", "RMD.AX", "COH.AX", "2359.HK", "6618.HK",
            "4503.T", "4528.T", "4516.T", "4587.T", "4483.T", "1513.HK", "6160.HK", "0999.HK", "1801.HK", "2196.HK",
            "300760.SZ", "300015.SZ", "600276.SS", "302440.KS", "068760.KS", "128940.KS", "000100.KS", "1760.TW", "6446.TW", "9938.TW",
            "FPH.AX", "SHL.AX", "ANN.AX", "RHC.AX", "REG.AX", "PME.AX", "006280.KS", "008930.KS", "300003.SZ", "300012.SZ"
        ],
    },
    {
        "name": "APAC-Cons",
        "region": "Asia/Pacific",
        "macro_industry": "consumer, autos, transport, and brand-led demand",
        "cron": "30 00 * * MON-FRI",
        "schedule_rationale": "Keeps the consumer and auto complex in the Asia opening window while preserving a 10-minute gap from neighboring jobs.",
        "tickers": [
            "7203.T", "7267.T", "7269.T", "7211.T", "1211.HK", "2333.HK", "0175.HK", "005380.KS", "012330.KS", "000270.KS",
            "2914.T", "2502.T", "2503.T", "4452.T", "4911.T", "WOW.AX", "COL.AX", "QAN.AX", "CAR.AX", "CPU.AX",
            "7201.T", "7270.T", "7261.T", "6902.T", "7272.T", "9201.T", "9202.T", "9020.T", "9022.T", "4661.T",
            "0291.HK", "0151.HK", "0322.HK", "1880.HK", "1928.HK", "0027.HK", "0960.HK", "1109.HK", "6862.HK", "2020.HK",
            "2331.HK", "097950.KS", "033780.KS", "051900.KS", "139480.KS", "023530.KS", "WES.AX", "ALL.AX", "2501.T", "7202.T"
        ],
    },
    {
        "name": "APAC-Cyc",
        "region": "Asia/Pacific",
        "macro_industry": "industrials, energy, materials, and trading houses",
        "cron": "40 00 * * MON-FRI",
        "schedule_rationale": "Runs late in the Asia opening window so commodity and heavy-industrial names can absorb overnight macro and early futures moves without overlapping other regions.",
        "tickers": [
            "BHP.AX", "RIO.AX", "FMG.AX", "WDS.AX", "STO.AX", "0883.HK", "0857.HK", "0386.HK", "1605.T", "5020.T",
            "5019.T", "7011.T", "6367.T", "6273.T", "6301.T", "8001.T", "8002.T", "8053.T", "8058.T", "1101.TW",
            "8031.T", "6503.T", "6305.T", "7012.T", "7013.T", "9101.T", "9104.T", "9107.T", "5401.T", "5411.T",
            "3407.T", "3402.T", "4063.T", "1171.HK", "1088.HK", "2600.HK", "2899.HK", "2002.TW", "1301.TW", "1303.TW",
            "1326.TW", "005490.KS", "011170.KS", "010130.KS", "010950.KS", "096770.KS", "MIN.AX", "NST.AX", "EVN.AX", "WHC.AX"
        ],
    },
    {
        "name": "EU-Tech",
        "region": "Europe",
        "macro_industry": "software, semis, payments, and telecom-tech platforms",
        "cron": "00 07 * * MON-FRI",
        "schedule_rationale": "Starts at the European cash open so the list catches open-driven repricing in semis, enterprise software, and payment-sensitive names while preserving the 10-minute cadence.",
        "tickers": [
            "ASML.AS", "SAP.DE", "ADYEN.AS", "PRX.AS", "IFX.DE", "NOKIA.HE", "ERIC-B.ST", "STMPA.PA", "BEI.DE", "LOGN.SW",
            "TEMN.SW", "ASM.AS", "WKL.AS", "S92.DE", "DHER.DE", "DSY.PA", "WLN.PA", "TELIA.ST", "KPN.AS", "AMS.MC",
            "CAP.PA", "ATO.PA", "SOI.PA", "OVH.PA", "NEXI.MI", "INW.MI", "SINCH.ST", "EVO.ST", "UMG.AS", "WISE.L",
            "MONY.L", "RMV.L", "ASC.L", "PAY.L", "OCDO.L", "SGE.L", "AUTO.L", "BT-A.L", "VOD.L", "UBI.PA",
            "PROX.BR", "DTE.DE", "TEF.MC", "ELUX-B.ST", "GETI-B.ST", "TEL2-B.ST", "VIV.PA", "NDA-FI.HE", "GFT.DE", "SBB-B.ST"
        ],
    },
    {
        "name": "EU-Fin",
        "region": "Europe",
        "macro_industry": "banks, insurers, exchanges, and asset managers",
        "cron": "10 07 * * MON-FRI",
        "schedule_rationale": "European financials are most informative once rates, sovereign spreads, and open auction pressure have started to settle, so this run follows the first open burst by 10 minutes.",
        "tickers": [
            "HSBA.L", "SAN.MC", "BNP.PA", "ALV.DE", "UBSG.SW", "ISP.MI", "BBVA.MC", "INGA.AS", "ACA.PA", "BARC.L",
            "DBK.DE", "KBC.BR", "NWG.L", "CABK.MC", "UCG.MI", "MUV2.DE", "ZURN.SW", "LGEN.L", "PRU.L", "EXPN.L",
            "GLE.PA", "CS.PA", "CBK.DE", "STAN.L", "LLOY.L", "AV.L", "ADEN.SW", "BAER.SW", "SLHN.SW", "SREN.SW",
            "HELN.SW", "VONTO.SW", "SAB.MC", "BKT.MC", "MAP.MC", "SAMPO.HE", "DNB.OL", "SEB-A.ST", "SHB-A.ST", "SWED-A.ST",
            "INVE-B.ST", "KINV-B.ST", "LUND-B.ST", "AZN.ST", "DB1.DE", "LSEG.L", "ENX.PA", "BME.MC", "MBK.WA", "PKO.WA"
        ],
    },
    {
        "name": "EU-Health",
        "region": "Europe",
        "macro_industry": "pharma, diagnostics, medtech, and healthcare equipment",
        "cron": "20 07 * * MON-FRI",
        "schedule_rationale": "Healthcare is staggered after tech and banks because it is usually more useful to score once the market has revealed whether it wants defense, growth, or policy-sensitive rotation.",
        "tickers": [
            "NOVO-B.CO", "RO.SW", "NOVN.SW", "AZN.L", "GSK.L", "SAN.PA", "BAYN.DE", "ALC.SW", "UCB.BR", "FRE.DE",
            "SHL.DE", "QIA.DE", "GN.CO", "DEMANT.CO", "GMAB.CO", "SRT3.DE", "PHIA.AS", "FAES.MC", "ORNBV.HE", "LUN.CO",
            "AMBU-B.CO", "ZEAL.CO", "VAR1.DE", "EVT.DE", "FME.DE", "EMEIS.PA", "IPN.PA", "ERF.PA", "VLA.PA", "BVI.PA",
            "DBV.PA", "HIK.L", "SN.L", "BOL.PA", "OXIG.L", "IDP.MC", "GRI.MC", "ROVI.MC", "PHM.MC", "SKAN.SW",
            "EKTA-B.ST", "VITR.ST", "REJL-B.ST", "SGL.DE", "VIRP.PA", "MRX.DE", "NEWA-B.ST", "DIM.PA", "BICO.ST", "GNS.L"
        ],
    },
    {
        "name": "EU-Cons",
        "region": "Europe",
        "macro_industry": "consumer staples, luxury, beverage, and retail demand",
        "cron": "30 07 * * MON-FRI",
        "schedule_rationale": "Consumer and luxury names are checked once Europe has a cleaner macro and FX read, which tends to produce more useful demand-sensitive analysis than an immediate open scan.",
        "tickers": [
            "MC.PA", "OR.PA", "NESN.SW", "ABI.BR", "DGE.L", "ULVR.L", "RI.PA", "KER.PA", "ADS.DE", "HEN3.DE",
            "RKT.L", "CCH.L", "HEIA.AS", "BN.PA", "FERG.L", "BATS.L", "IMB.L", "ZAL.DE", "AG1.DE", "JDW.L",
            "RMS.PA", "CDA.PA", "RNO.PA", "AC.PA", "ELIOR.PA", "PUM.DE", "HFG.DE", "PAH3.DE", "HM-B.ST", "AXFO.ST",
            "INDU-C.ST", "PNDORA.CO", "CARL-B.CO", "ITX.MC", "AENA.MC", "IAG.L", "EZJ.L", "RYR.I", "ABF.L", "NXT.L",
            "JD.L", "PHNX.L", "CPG.L", "BME.L", "FRAS.L", "VGP.BR", "COFB.BR", "WDP.BR", "SOLB.BR", "SW.PA"
        ],
    },
    {
        "name": "EU-Cyc",
        "region": "Europe",
        "macro_industry": "industrials, energy, autos, chemicals, and materials",
        "cron": "40 07 * * MON-FRI",
        "schedule_rationale": "Cyclicals run after the earlier Europe groups because commodity, industrial, and auto names usually react best once the continental macro tape and sector leadership are clearer.",
        "tickers": [
            "SHEL.L", "BP.L", "TTE.PA", "ENI.MI", "EQNR.OL", "RIO.L", "GLEN.L", "AAL.L", "HOLN.SW", "CRH.L",
            "HEI.DE", "SY1.DE", "BAS.DE", "SIKA.SW", "AKZA.AS", "VOW3.DE", "MBG.DE", "BMW.DE", "AIR.PA", "SU.PA",
            "REP.MC", "ENG.MC", "ELE.MC", "IBE.MC", "FER.MC", "ACS.MC", "GALP.LS", "EDP.LS", "NHY.OL", "AKRBP.OL",
            "YAR.OL", "MOWI.OL", "ORK.OL", "SKA-B.ST", "VOLV-B.ST", "SAND.ST", "SKF-B.ST", "EPI-B.ST", "BOL.ST", "SSAB-A.ST",
            "MAERSK-B.CO", "VWS.CO", "ORSTED.CO", "FRO.OL", "SUBC.OL", "ANTO.L", "BAE.L", "RHM.DE", "RWE.DE", "EOAN.DE"
        ],
    },
    {
        "name": "US-Tech",
        "region": "United States",
        "macro_industry": "software, platforms, cloud, and internet growth",
        "cron": "00 13 * * MON-FRI",
        "schedule_rationale": "Runs into the U.S. open so the watchlist can react to overnight news, futures positioning, and large-cap tech tone while preserving the 10-minute cadence.",
        "tickers": [
            "AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "CRM", "ORCL", "ADBE", "NOW",
            "INTU", "PANW", "CRWD", "SNOW", "DDOG", "MDB", "TEAM", "ZS", "UBER", "ABNB",
            "NVDA", "AVGO", "AMD", "QCOM", "TXN", "MU", "ADI", "AMAT", "LRCX", "KLAC",
            "CDNS", "SNPS", "SHOP", "SQ", "PYPL", "DASH", "V", "MA", "ADP", "IBM",
            "CSCO", "INTC", "HPE", "DELL", "NET", "FTNT", "ANET", "ARM", "RBLX", "PLTR"
        ],
    },
    {
        "name": "US-Fin",
        "region": "United States",
        "macro_industry": "banks, brokers, exchanges, and insurers",
        "cron": "10 13 * * MON-FRI",
        "schedule_rationale": "U.S. financials follow tech so rate-sensitive and credit-sensitive names can be scored once premarket yields and opening futures direction are more visible.",
        "tickers": [
            "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "PNC", "USB",
            "COF", "AXP", "BK", "TFC", "CME", "ICE", "SPGI", "CB", "AIG", "MMC",
            "MCO", "MSCI", "MKTX", "BRK-B", "KRE", "KBE", "XLF", "TRV", "PGR", "ALL",
            "MET", "PRU", "AFL", "AJG", "BRO", "AON", "WTW", "AMP", "TROW", "BEN",
            "STT", "NTRS", "FITB", "MTB", "HBAN", "RF", "KEY", "CFG", "SYF", "ALLY"
        ],
    },
    {
        "name": "US-Health",
        "region": "United States",
        "macro_industry": "pharma, managed care, medtech, and providers",
        "cron": "20 13 * * MON-FRI",
        "schedule_rationale": "Healthcare is placed after the initial U.S. open sequence because the first 30 to 60 minutes usually reveal whether the tape prefers defense or high-beta growth.",
        "tickers": [
            "LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN",
            "GILD", "BMY", "MDT", "ISRG", "SYK", "BSX", "CI", "CVS", "HCA", "REGN",
            "VRTX", "ZTS", "BIIB", "MRNA", "BDX", "EW", "IDXX", "HUM", "ELV", "CNC",
            "MCK", "COR", "CAH", "ALGN", "DXCM", "IQV", "A", "WAT", "UHS", "TECH",
            "STE", "HOLX", "RGEN", "WST", "BIO", "RVTY", "MTD", "INCY", "NTRA", "PODD"
        ],
    },
    {
        "name": "US-Cons",
        "region": "United States",
        "macro_industry": "consumer staples, telecom, media, and household demand",
        "cron": "30 13 * * MON-FRI",
        "schedule_rationale": "Consumer and defensive demand names are checked after financials and healthcare so the run sees whether the market is rotating toward safety, staples, or communications defensives.",
        "tickers": [
            "WMT", "COST", "PG", "KO", "PEP", "MCD", "NKE", "HD", "LOW", "SBUX",
            "DIS", "CMCSA", "TMUS", "T", "VZ", "PM", "MO", "CL", "KMB", "GIS",
            "EL", "STZ", "MDLZ", "HSY", "K", "TSN", "ADM", "SYY", "KR", "TGT",
            "TJX", "ROST", "LULU", "EBAY", "ETSY", "BKNG", "EXPE", "MAR", "HLT", "MGM",
            "WYNN", "LVS", "RCL", "CCL", "NCLH", "YUM", "DPZ", "DRI", "TSLA", "F"
        ],
    },
    {
        "name": "US-Cyc",
        "region": "United States",
        "macro_industry": "industrials, energy, materials, and transport cyclicals",
        "cron": "40 13 * * MON-FRI",
        "schedule_rationale": "Placed last in the U.S. block so industrial, transport, and energy names can incorporate the clearest read on open leadership, crude tone, and macro risk appetite while still avoiding overlap.",
        "tickers": [
            "CAT", "DE", "GE", "HON", "RTX", "UNP", "UPS", "BA", "ETN", "MMM",
            "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "FCX", "LMT", "NOC", "GD",
            "TDG", "HWM", "IR", "ITW", "EMR", "ROP", "PH", "CMI", "PCAR", "FDX",
            "CSX", "NSC", "WM", "RSG", "VMC", "MLM", "SHW", "ECL", "APD", "LIN",
            "NEE", "DUK", "SO", "XEL", "PLD", "AMT", "CCI", "EQIX", "SPG", "O"
        ],
    },
]

SUPPORT_REFRESH_JOB_SPECS = [
    {
        "name": "Macro-Refresh-AM",
        "job_type": "macro_context_refresh",
        "cron": "00 06 * * MON-FRI",
        "schedule_rationale": "Runs before the Europe block.",
    },
    {
        "name": "Macro-Refresh-PM",
        "job_type": "macro_context_refresh",
        "cron": "00 18 * * MON-FRI",
        "schedule_rationale": "Runs after the U.S. block.",
    },
    {
        "name": "Industry-Refresh",
        "job_type": "industry_context_refresh",
        "cron": "30 10 * * MON-FRI",
        "schedule_rationale": "Gap between Europe and U.S. batches.",
    },
    {
        "name": "Bars-APAC",
        "job_type": "bars_data_refresh",
        "cron": "30 08 * * MON-FRI",
        "region_filter": "Asia/Pacific",
        "schedule_rationale": "Post-APAC close.",
    },
    {
        "name": "Bars-EU",
        "job_type": "bars_data_refresh",
        "cron": "00 17 * * MON-FRI",
        "region_filter": "Europe",
        "schedule_rationale": "Post-Europe close.",
    },
    {
        "name": "Bars-US",
        "job_type": "bars_data_refresh",
        "cron": "30 20 * * MON-FRI",
        "region_filter": "United States",
        "schedule_rationale": "Post-US close.",
    },
]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logging.info("Deploying curated default watchlists and jobs")
    if SessionLocal is None or JobType is None or WatchlistRepository is None or JobRepository is None or JobRecord is None or WatchlistRecord is None or select is None:
        raise RuntimeError("deploy_watchlists.py requires the project runtime dependencies to be installed")

    _validate_watchlist_specs(WATCHLIST_SPECS)

    with SessionLocal() as session:
        watchlist_repo = WatchlistRepository(session)
        job_repo = JobRepository(session)

        # 1. First, delete all OLD jobs with the "Auto: " prefix to clean up
        _delete_old_jobs(session)

        for spec in WATCHLIST_SPECS:
            normalized = _normalize_tickers(spec["tickers"])
            # Curated watchlists trigger overlap removal
            watchlist_record = _ensure_watchlist(
                session,
                watchlist_repo,
                spec["name"],
                normalized,
                trigger_removal=True,
                region=spec["region"],
                description=spec["macro_industry"],
            )
            job_name = f"{spec['name']}" # No prefix
            _ensure_job(
                session,
                job_repo,
                watchlist_record,
                job_name,
                spec["cron"],
                job_type=JobType.PROPOSAL_GENERATION,
            )

        for spec in SUPPORT_REFRESH_JOB_SPECS:
            target_watchlist = None
            job_tickers: list[str] = []
            job_type = JobType(spec["job_type"])

            _ensure_job(
                session,
                job_repo,
                target_watchlist,
                spec["name"],
                spec["cron"],
                job_type=job_type,
                tickers=job_tickers,
            )

    logging.info("Deployment complete")


def _delete_old_jobs(session) -> None:
    # Delete jobs that have "Auto: " prefix
    old_jobs = session.scalars(select(JobRecord).where(JobRecord.name.like("Auto: %"))).all()
    for job in old_jobs:
        logging.info("Deleting old job: %s", job.name)
        session.delete(job)
    
    # Also delete old "System: " watchlists
    old_ws = session.scalars(select(WatchlistRecord).where(WatchlistRecord.name.like("System: %"))).all()
    for ws in old_ws:
        logging.info("Deleting old watchlist: %s", ws.name)
        session.delete(ws)
    
    session.commit()


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

    if total != 750:
        raise ValueError(f"expected 750 seeded tickers across all default watchlists, found {total}")


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
    session,
    repo: WatchlistRepository,
    name: str,
    tickers: list[str],
    trigger_removal: bool = True,
    *,
    region: str = "",
    description: str = "",
) -> WatchlistRecord:
    if trigger_removal:
        _remove_tickers_from_other_watchlists(session, tickers, exclude_name=name)
        
    record = _find_watchlist_record(session, name)

    if record:
        current = [ticker for ticker in record.tickers_csv.split(",") if ticker]
        dirty = False
        if set(current) != set(tickers):
            record.tickers_csv = ",".join(tickers)
            dirty = True
        if (record.region or "") != region:
            record.region = region
            dirty = True
        if (record.description or "") != description:
            record.description = description
            dirty = True
        if dirty:
            session.commit()
            session.refresh(record)
            logging.info("Updated watchlist '%s'", name)
        else:
            logging.info("Watchlist '%s' already configured", name)
        return record

    watchlist = repo.create(name, tickers, description=description, region=region)
    logging.info("Created watchlist '%s'", watchlist.name)
    return _find_watchlist_record(session, watchlist.name)


def _ensure_job(
    session,
    repo: JobRepository,
    watchlist: WatchlistRecord | None,
    job_name: str,
    cron: str,
    job_type: JobType,
    tickers: list[str] | None = None,
) -> None:
    record = session.scalars(select(JobRecord).where(JobRecord.name == job_name)).first()
    watchlist_id = watchlist.id if watchlist is not None else None
    normalized_tickers = _normalize_tickers(tickers or [])
    if record:
        repo.update(
            job_id=record.id,
            name=job_name,
            tickers=normalized_tickers,
            schedule=cron,
            enabled=True,
            watchlist_id=watchlist_id,
            job_type=job_type,
        )
        logging.info("Updated job '%s' (%s)", job_name, job_type.value)
    else:
        repo.create(
            name=job_name,
            tickers=normalized_tickers,
            schedule=cron,
            enabled=True,
            watchlist_id=watchlist_id,
            job_type=job_type,
        )
        logging.info("Created job '%s' (%s)", job_name, job_type.value)


def _remove_tickers_from_other_watchlists(
    session,
    tickers: Iterable[str],
    exclude_name: str,
) -> None:
    interested = set(tickers)
    # We only remove tickers from regular curated watchlists, not system/refresh ones
    rows = session.scalars(
        select(WatchlistRecord)
        .where(WatchlistRecord.name != exclude_name)
        .where(~WatchlistRecord.name.like("Ref-%"))
    ).all()
    for row in rows:
        existing = [t for t in row.tickers_csv.split(",") if t]
        filtered = [t for t in existing if t not in interested]
        if len(filtered) != len(existing):
            row.tickers_csv = ",".join(filtered)
            session.commit()
            logging.info("Removed overlapping tickers from watchlist '%s'", row.name)


def _find_watchlist_record(session, name: str) -> WatchlistRecord | None:
    return session.scalars(select(WatchlistRecord).where(WatchlistRecord.name == name)).first()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Failed to deploy watchlists")
        raise
