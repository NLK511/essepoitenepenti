#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import ReplayPlanOutcomeRecord
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.replay_bar_coverage import ReplayBarCoverageService


def _parse_sources(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit cached 1m bar coverage for replay outcomes.")
    parser.add_argument("--batch-id", action="append", type=int, default=[])
    parser.add_argument("--only-blocked", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resolution-source", default="pending,pending_intraday_required")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/replay-bar-coverage-audit.json"),
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        query = select(ReplayPlanOutcomeRecord).order_by(ReplayPlanOutcomeRecord.id.asc())
        if args.batch_id:
            query = query.where(ReplayPlanOutcomeRecord.replay_batch_id.in_(args.batch_id))
        sources = _parse_sources(args.resolution_source)
        if sources:
            query = query.where(ReplayPlanOutcomeRecord.resolution_source.in_(sources))
        if args.only_blocked:
            query = query.where(ReplayPlanOutcomeRecord.resolution_source != "intraday")
        if args.limit is not None:
            query = query.limit(args.limit)
        rows = session.scalars(query).all()
        plans = RecommendationPlanRepository(session)
        coverage = ReplayBarCoverageService(session)
        reason_counts: Counter[str] = Counter()
        ticker_counts: Counter[str] = Counter()
        diagnostics: list[dict[str, object]] = []
        missing_plans = 0
        for row in rows:
            try:
                plan = plans.get_plan(row.recommendation_plan_id)
            except ValueError:
                missing_plans += 1
                continue
            diagnostic = coverage.diagnose_plan(plan)
            reason_counts[diagnostic.reason] += 1
            ticker_counts[diagnostic.ticker] += 1
            diagnostics.append(
                {
                    "replay_batch_id": row.replay_batch_id,
                    "replay_plan_outcome_id": row.id,
                    "recommendation_plan_id": row.recommendation_plan_id,
                    "resolution_source": row.resolution_source,
                    "outcome": row.outcome,
                    "status": row.status,
                    "diagnostic": diagnostic.to_dict(),
                }
            )
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested": {
                "batch_ids": args.batch_id,
                "only_blocked": args.only_blocked,
                "resolution_sources": sorted(sources),
                "limit": args.limit,
            },
            "selected_outcome_count": len(rows),
            "diagnosed_outcome_count": len(diagnostics),
            "missing_plan_count": missing_plans,
            "reason_counts": dict(reason_counts),
            "ticker_counts": dict(ticker_counts.most_common(50)),
            "diagnostics": diagnostics,
        }
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        print(json.dumps({k: payload[k] for k in payload if k != "diagnostics"}, indent=2, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()
