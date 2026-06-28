#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.replay_evidence_audit import ReplayEvidenceAuditConfig, ReplayEvidenceAuditService


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit replay/tuning evidence quality and promotion readiness.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch-id", type=int)
    group.add_argument("--tuning-run-id", type=int)
    parser.add_argument("--artifact-dir", default="artifacts")
    parser.add_argument("--min-eligible-rows", type=int, default=10)
    parser.add_argument("--min-execution-rows", type=int, default=8)
    args = parser.parse_args()
    session = SessionLocal()
    try:
        service = ReplayEvidenceAuditService(
            session,
            ReplayEvidenceAuditConfig(
                min_eligible_rows=args.min_eligible_rows,
                min_execution_rows=args.min_execution_rows,
            ),
        )
        audit = service.audit_batch(args.batch_id) if args.batch_id is not None else service.audit_tuning_run(args.tuning_run_id or 0)
        artifact_dir = Path(args.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        subject = f"batch-{args.batch_id}" if args.batch_id is not None else f"tuning-run-{args.tuning_run_id}"
        path = artifact_dir / f"replay-evidence-audit-{subject}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
        audit["artifact_path"] = str(path)
        path.write_text(json.dumps(audit, indent=2, sort_keys=True, default=str))
        print(json.dumps(audit, indent=2, sort_keys=True, default=str))
    finally:
        session.close()


if __name__ == "__main__":
    main()
