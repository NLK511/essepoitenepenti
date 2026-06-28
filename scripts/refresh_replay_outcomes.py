#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.input_access import INPUT_ACCESS_POLICIES
from trade_proposer_app.services.replay_outcome_refresh import ReplayOutcomeRefreshService


def _parse_dt(value: str | None):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh existing replay outcomes from persisted price bars.")
    parser.add_argument("--batch-id", type=int, required=True)
    parser.add_argument("--as-of", default=None, help="Resolution timestamp; defaults to now.")
    parser.add_argument("--include-resolved", action="store_true")
    parser.add_argument("--no-reclassify", action="store_true")
    parser.add_argument("--policy", default="cache_only", choices=INPUT_ACCESS_POLICIES)
    parser.add_argument("--artifact-dir", default="artifacts")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        summary = ReplayOutcomeRefreshService(session).refresh_batch(
            args.batch_id,
            as_of=_parse_dt(args.as_of),
            include_resolved=bool(args.include_resolved),
            reclassify=not args.no_reclassify,
            input_access_policy=args.policy,
        )
        payload = summary.to_dict()
        artifact_dir = Path(args.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / f"replay-outcome-refresh-batch-{args.batch_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
        payload["artifact_path"] = str(path)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        session.commit()
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
