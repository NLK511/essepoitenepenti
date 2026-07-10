#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text

from trade_proposer_app.config import settings


def _json(value: object) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return {} if value is None else value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _neutral_reason(source: dict[str, Any], drivers: list[Any], quality: str, evidence: str, coverage: str) -> str:
    if quality in {"blocked", "failed"}:
        return "context_quality_blocked"
    if quality in {"degraded", "partial"}:
        return "context_quality_degraded"
    if evidence in {"missing", "missing_snapshot"}:
        return "missing_industry_evidence"
    if coverage == "missing":
        return "missing_industry_coverage"
    if not drivers:
        return "no_salient_industry_drivers"
    for reason in source.get("score_reasons") or []:
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
    return "true_neutral_or_balanced_context"


def _summarize(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    quality: Counter[str] = Counter()
    evidence: Counter[str] = Counter()
    coverage: Counter[str] = Counter()
    status: Counter[str] = Counter()
    neutral: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    by_industry: dict[str, Counter[str]] = {}
    active_driver_count = 0
    zero_confidence_count = 0
    stale_count = 0
    decision_usable_count = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        industry_key, industry_label, row_status, confidence, expires_at, active_json, source_json, warnings_json = row
        source = _json(source_json)
        source = source if isinstance(source, dict) else {}
        drivers = _json(active_json)
        drivers = drivers if isinstance(drivers, list) else []
        row_warnings = _json(warnings_json)
        row_warnings = row_warnings if isinstance(row_warnings, list) else []
        q = str(source.get("context_quality_status") or "unknown")
        e = str(source.get("evidence_state") or "missing")
        c = str(source.get("coverage_state") or "missing")
        quality[q] += 1
        evidence[e] += 1
        coverage[c] += 1
        status[str(row_status or "unknown")] += 1
        if drivers:
            active_driver_count += 1
        try:
            if float(confidence or 0.0) == 0.0:
                zero_confidence_count += 1
        except (TypeError, ValueError):
            zero_confidence_count += 1
        if expires_at is not None:
            expires = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
            if expires < now:
                stale_count += 1
        if q == "usable" and e == "usable" and drivers:
            decision_usable_count += 1
        reason = _neutral_reason(source, drivers, q, e, c)
        if q != "usable" or e != "usable" or not drivers:
            neutral[reason] += 1
        label = str(industry_label or industry_key or "unknown")
        by_industry.setdefault(label, Counter())[q] += 1
        for warning in row_warnings:
            if isinstance(warning, str) and warning.strip():
                warnings[warning.strip()] += 1
    total = len(rows)
    return {
        "total_count": total,
        "status_counts": dict(status),
        "quality_status_counts": dict(quality),
        "evidence_state_counts": dict(evidence),
        "coverage_state_counts": dict(coverage),
        "active_driver_count": active_driver_count,
        "empty_driver_count": total - active_driver_count,
        "zero_confidence_count": zero_confidence_count,
        "stale_count": stale_count,
        "decision_usable_count": decision_usable_count,
        "decision_usable_rate_percent": round((decision_usable_count / total * 100.0) if total else 0.0, 1),
        "active_driver_rate_percent": round((active_driver_count / total * 100.0) if total else 0.0, 1),
        "top_neutral_reasons": neutral.most_common(10),
        "top_warnings": warnings.most_common(10),
        "industry_quality_counts": {label: dict(counts) for label, counts in sorted(by_industry.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report industry-context evidence quality and usefulness readiness.")
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT industry_key, industry_label, status, confidence_percent, expires_at,
                       active_drivers_json, source_breakdown_json, warnings_json
                FROM industry_context_snapshots
                ORDER BY computed_at DESC
                LIMIT :limit
                """
            ),
            {"limit": args.limit},
        ).fetchall()
    summary = _summarize(rows)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return
    print(f"Industry snapshots: {summary['total_count']}")
    print(f"Decision-usable: {summary['decision_usable_count']} ({summary['decision_usable_rate_percent']}%)")
    print(f"Active-driver rate: {summary['active_driver_rate_percent']}%")
    print(f"Stale: {summary['stale_count']}  Zero-confidence: {summary['zero_confidence_count']}")
    print(f"Quality: {summary['quality_status_counts']}")
    print(f"Evidence: {summary['evidence_state_counts']}")
    print(f"Coverage: {summary['coverage_state_counts']}")
    print(f"Top neutral reasons: {summary['top_neutral_reasons']}")


if __name__ == "__main__":
    main()
