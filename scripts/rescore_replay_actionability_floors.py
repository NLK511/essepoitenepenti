from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.actionability_floor_calibration import ActionabilityFloorCalibrationService


def main() -> None:
    parser = argparse.ArgumentParser(description="Rescore one historical replay batch across actionability confidence floors without rerunning replay.")
    parser.add_argument("--batch-id", type=int, required=True)
    parser.add_argument("--floors", nargs="+", type=float, default=[50.0, 52.0, 53.75, 55.0])
    parser.add_argument("--min-resolved-trades", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        payload = ActionabilityFloorCalibrationService(session).run(
            replay_batch_id=args.batch_id,
            floors=args.floors,
            min_resolved_trades=args.min_resolved_trades,
        )
    finally:
        session.close()
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
