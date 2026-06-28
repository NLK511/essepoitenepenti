#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.replay_eligibility_reclassification import ReplayEligibilityReclassificationService


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute replay eligibility rows for an existing replay batch.")
    parser.add_argument("--batch-id", type=int, required=True)
    parser.add_argument(
        "--policy",
        choices=["cache_only", "cache_then_remote", "remote_refresh", "fail_if_missing"],
        default="cache_only",
        help="Input access policy for rebuilding missing coverage reports. Defaults to cache_only.",
    )
    args = parser.parse_args()
    session = SessionLocal()
    try:
        summary = ReplayEligibilityReclassificationService(session).reclassify_batch(
            args.batch_id,
            input_access_policy=args.policy,
        )
        session.commit()
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
