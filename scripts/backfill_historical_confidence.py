#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.historical_confidence_backfill import HistoricalConfidenceBackfillService


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill persisted historical plan confidence from stored confidence components.")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="Persist the backfill. Without this flag the script is a dry run.")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        summary = HistoricalConfidenceBackfillService(session).backfill(
            batch_size=int(args.batch_size),
            limit=args.limit,
            dry_run=not bool(args.apply),
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True, default=str))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
