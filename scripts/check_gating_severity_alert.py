#!/usr/bin/env python
from __future__ import annotations

import argparse
import json

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.gating_severity_alerts import GatingSeverityAlertService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate whether decision/shortlist gating may be too severe."
    )
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument(
        "--no-record-event",
        action="store_true",
        help="Print report without writing an observability event",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        payload = GatingSeverityAlertService(session).evaluate(
            window_days=args.window_days,
            record_event=not args.no_record_event,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()
