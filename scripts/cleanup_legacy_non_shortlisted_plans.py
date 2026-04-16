#!/usr/bin/env python3
"""Dry-run or clean up legacy non-shortlisted plan rows.

This targets historical cheap-scan-only RecommendationPlan rows that were created
for non-shortlisted tickers before the persistence-policy change.

Safety model:
- dry-run by default
- apply mode requires both --apply and --yes
- linked RecommendationDecisionSample rows are preserved
- linked RecommendationOutcome rows are deleted
- linked RecommendationDecisionSample.recommendation_plan_id is nulled before
  deleting the legacy plan row so the audit sample remains valid

Examples:
  .venv/bin/python scripts/cleanup_legacy_non_shortlisted_plans.py
  .venv/bin/python scripts/cleanup_legacy_non_shortlisted_plans.py --limit 100 --json
  .venv/bin/python scripts/cleanup_legacy_non_shortlisted_plans.py --apply --yes --output cleanup-backup.json
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


LEGACY_FROM = """
FROM recommendation_plans AS p
LEFT JOIN recommendation_decision_samples AS ds
    ON ds.recommendation_plan_id = p.id
"""

LEGACY_FILTER = """
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

DETAIL_QUERY = text(
    f"""
    SELECT
        p.id,
        p.run_id,
        p.job_id,
        p.ticker,
        p.horizon,
        p.created_at,
        p.entry_price_low,
        p.entry_price_high,
        p.stop_loss,
        p.take_profit,
        p.signal_breakdown_json,
        ds.id AS decision_sample_id,
        ds.ticker_signal_snapshot_id,
        ds.shortlisted,
        ds.decision_reason,
        o.id AS outcome_id,
        o.outcome,
        o.status AS outcome_status
    {LEGACY_FROM}
    LEFT JOIN recommendation_outcomes AS o
        ON o.recommendation_plan_id = p.id
    {LEGACY_FILTER}
    ORDER BY p.created_at DESC, p.id DESC
    """
)

RUN_BREAKDOWN_QUERY = text(
    f"""
    SELECT p.run_id, COUNT(*) AS row_count
    {LEGACY_FROM}
    {LEGACY_FILTER}
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


def _build_payload(rows: list[dict[str, Any]], run_breakdown: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    plan_ids = [int(row["id"]) for row in rows]
    decision_sample_ids = sorted({int(row["decision_sample_id"]) for row in rows if row.get("decision_sample_id") is not None})
    outcome_ids = sorted({int(row["outcome_id"]) for row in rows if row.get("outcome_id") is not None})
    return {
        "database_url": settings.database_url,
        "candidate_plan_count": len(plan_ids),
        "candidate_decision_sample_count": len(decision_sample_ids),
        "candidate_outcome_count": len(outcome_ids),
        "preview_limit": limit,
        "plan_ids": plan_ids,
        "decision_sample_ids": decision_sample_ids,
        "outcome_ids": outcome_ids,
        "run_breakdown": run_breakdown,
        "candidates": rows[:limit],
    }


def _print_human(payload: dict[str, Any], *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"Legacy non-shortlisted plan cleanup ({mode})")
    print(f"Database: {payload['database_url']}")
    print(f"Candidate plans: {payload['candidate_plan_count']}")
    print(f"Decision samples to preserve and detach: {payload['candidate_decision_sample_count']}")
    print(f"Outcome rows to delete: {payload['candidate_outcome_count']}")
    print()
    print("Top runs by candidate count:")
    if payload["run_breakdown"]:
        for item in payload["run_breakdown"]:
            print(f"- run_id={item['run_id']}: {item['row_count']} rows")
    else:
        print("- none")
    print()
    print(f"Preview rows (limit={payload['preview_limit']}):")
    if payload["candidates"]:
        for item in payload["candidates"]:
            print(
                "- "
                f"plan_id={item['id']} ticker={item['ticker']} run_id={item['run_id']} "
                f"decision_sample_id={item['decision_sample_id']} outcome_id={item['outcome_id']} "
                f"created_at={item['created_at']}"
            )
    else:
        print("- none")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Preview row limit")
    parser.add_argument("--run-limit", type=int, default=20, help="Run breakdown row limit")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON backup/report path")
    parser.add_argument("--apply", action="store_true", help="Apply the cleanup instead of dry-run")
    parser.add_argument("--yes", action="store_true", help="Required with --apply to confirm destructive changes")
    args = parser.parse_args()

    if args.apply and not args.yes:
        parser.error("--apply requires --yes")
    if "postgresql" not in settings.database_url:
        parser.error("this cleanup script currently supports Postgres only")

    engine = create_engine(settings.database_url, future=True)
    with engine.connect() as conn:
        rows = _rows_to_dicts(conn.execute(DETAIL_QUERY).fetchall())
        run_breakdown = _rows_to_dicts(conn.execute(RUN_BREAKDOWN_QUERY, {"limit": args.run_limit}).fetchall())

    payload = _build_payload(rows, run_breakdown, limit=args.limit)
    payload["mode"] = "apply" if args.apply else "dry_run"

    if args.output is not None:
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not args.apply:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(payload, apply=False)
            if args.output is not None:
                print()
                print(f"JSON report written to {args.output}")
        return 0

    plan_ids = payload["plan_ids"]
    if not plan_ids:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(payload, apply=True)
            print()
            print("No matching legacy rows found; nothing changed.")
        return 0

    with engine.begin() as conn:
        detached_samples = conn.execute(
            text(
                """
                UPDATE recommendation_decision_samples
                SET recommendation_plan_id = NULL
                WHERE recommendation_plan_id = ANY(:plan_ids)
                """
            ),
            {"plan_ids": plan_ids},
        ).rowcount or 0
        deleted_outcomes = conn.execute(
            text(
                """
                DELETE FROM recommendation_outcomes
                WHERE recommendation_plan_id = ANY(:plan_ids)
                """
            ),
            {"plan_ids": plan_ids},
        ).rowcount or 0
        deleted_plans = conn.execute(
            text(
                """
                DELETE FROM recommendation_plans
                WHERE id = ANY(:plan_ids)
                """
            ),
            {"plan_ids": plan_ids},
        ).rowcount or 0

    payload["applied_changes"] = {
        "detached_decision_samples": int(detached_samples),
        "deleted_outcomes": int(deleted_outcomes),
        "deleted_plans": int(deleted_plans),
    }

    if args.output is not None:
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload, apply=True)
        print()
        print("Applied changes:")
        print(f"- detached decision samples: {detached_samples}")
        print(f"- deleted outcomes: {deleted_outcomes}")
        print(f"- deleted plans: {deleted_plans}")
        if args.output is not None:
            print(f"- JSON backup/report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
