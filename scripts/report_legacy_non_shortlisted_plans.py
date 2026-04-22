#!/usr/bin/env python3
"""Report legacy cheap-scan-only non-shortlisted plan rows.

These rows were created before the persistence policy changed to stop creating
full RecommendationPlan records for ordinary non-shortlisted tickers.

The script is intentionally read-only. It helps identify historical rows that
could be archived or removed later with a separate, explicit cleanup step.

Examples:
  .venv/bin/python scripts/report_legacy_non_shortlisted_plans.py
  .venv/bin/python scripts/report_legacy_non_shortlisted_plans.py --limit 100
  .venv/bin/python scripts/report_legacy_non_shortlisted_plans.py --json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from trade_proposer_app.config import settings


_LEGACY_WHERE = """
FROM recommendation_plans AS p
LEFT JOIN recommendation_decision_samples AS ds
    ON ds.recommendation_plan_id = p.id
WHERE p.action = 'no_action'
  AND p.entry_price_low IS NULL
  AND p.entry_price_high IS NULL
  AND p.stop_loss IS NULL
  AND p.take_profit IS NULL
  AND COALESCE(ds.shortlisted, FALSE) = FALSE
  AND COALESCE(ds.decision_reason, '') = 'not_shortlisted'
  AND (
      CAST(NULLIF(p.signal_breakdown_json, '') AS jsonb) ->> 'shortlisted' IS NULL
      OR LOWER(CAST(NULLIF(p.signal_breakdown_json, '') AS jsonb) ->> 'shortlisted') = 'false'
  )
"""

LEGACY_QUERY = text(
    f"""
    SELECT
        p.id,
        p.run_id,
        p.job_id,
        p.ticker,
        p.horizon,
        p.action,
        p.entry_price_low,
        p.entry_price_high,
        p.stop_loss,
        p.take_profit,
        p.created_at,
        p.signal_breakdown_json,
        ds.id AS decision_sample_id,
        ds.shortlisted,
        ds.decision_reason,
        ds.ticker_signal_snapshot_id
    {_LEGACY_WHERE}
    ORDER BY p.created_at DESC, p.id DESC
    LIMIT :limit
    """
)

COUNT_QUERY = text(
    f"""
    SELECT COUNT(*)
    {_LEGACY_WHERE}
    """
)

RUN_BREAKDOWN_QUERY = text(
    f"""
    SELECT p.run_id, COUNT(*) AS row_count
    {_LEGACY_WHERE}
    GROUP BY p.run_id
    ORDER BY row_count DESC, p.run_id DESC
    LIMIT :limit
    """
)


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _rows_to_dicts(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [_normalize(dict(row._mapping)) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="Maximum matching plan rows to print")
    parser.add_argument("--run-limit", type=int, default=20, help="Maximum run breakdown rows to print")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the full report payload as JSON",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url, future=True)
    with engine.connect() as conn:
        total = conn.execute(COUNT_QUERY).scalar_one()
        rows = _rows_to_dicts(conn.execute(LEGACY_QUERY, {"limit": args.limit}).fetchall())
        run_breakdown = _rows_to_dicts(conn.execute(RUN_BREAKDOWN_QUERY, {"limit": args.run_limit}).fetchall())

    payload = {
        "database_url": settings.database_url,
        "total_candidate_rows": int(total),
        "printed_limit": args.limit,
        "run_breakdown_limit": args.run_limit,
        "candidates": rows,
        "run_breakdown": run_breakdown,
    }

    if args.output is not None:
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("Legacy non-shortlisted plan candidate report")
    print(f"Database: {settings.database_url}")
    print(f"Total candidate rows: {total}")
    print()
    print("Top runs by candidate count:")
    if run_breakdown:
        for item in run_breakdown:
            print(f"- run_id={item['run_id']}: {item['row_count']} rows")
    else:
        print("- none")
    print()
    print(f"Most recent candidate rows (limit={args.limit}):")
    if rows:
        for item in rows:
            print(
                "- "
                f"plan_id={item['id']} ticker={item['ticker']} run_id={item['run_id']} "
                f"job_id={item['job_id']} created_at={item['created_at']} "
                f"decision_sample_id={item['decision_sample_id']} signal_snapshot_id={item['ticker_signal_snapshot_id']}"
            )
    else:
        print("- none")
    if args.output is not None:
        print()
        print(f"JSON report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
