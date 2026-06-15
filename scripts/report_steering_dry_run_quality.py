#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import BrokerSteeringDecisionRecord

AMENDMENT_DECISIONS = {
    "move_stop_to_breakeven_or_profit",
    "move_stop_to_profit",
    "tighten_stop_loss",
    "lower_take_profit",
}
CLOSE_NOW_DECISIONS = {"close_position_now"}
DEFAULT_REVIEW_THRESHOLDS = {
    "dry_run_decisions": 30,
    "dry_run_amendments": 10,
    "dry_run_close_now": 10,
}


@dataclass(frozen=True)
class SteeringDecisionRow:
    id: int | None
    broker_account_id: str
    ticker: str
    decision: str
    execution_status: str
    execute_allowed: bool
    reason_codes: list[str]
    diagnostics: dict[str, Any]
    risk_delta: dict[str, Any]
    current_price: float | None
    current_stop_loss: float | None
    current_take_profit: float | None
    proposed_stop_loss: float | None
    proposed_take_profit: float | None
    error_message: str
    created_at: str | None


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def row_from_record(record: BrokerSteeringDecisionRecord) -> SteeringDecisionRow:
    reason_codes = _loads(record.reason_codes_json, [])
    diagnostics = _loads(record.diagnostics_json, {})
    risk_delta = _loads(record.risk_delta_json, {})
    return SteeringDecisionRow(
        id=record.id,
        broker_account_id=record.broker_account_id,
        ticker=record.ticker,
        decision=record.decision,
        execution_status=record.execution_status,
        execute_allowed=bool(record.execute_allowed),
        reason_codes=[str(item) for item in reason_codes] if isinstance(reason_codes, list) else [],
        diagnostics=diagnostics if isinstance(diagnostics, dict) else {},
        risk_delta=risk_delta if isinstance(risk_delta, dict) else {},
        current_price=record.current_price,
        current_stop_loss=record.current_stop_loss,
        current_take_profit=record.current_take_profit,
        proposed_stop_loss=record.proposed_stop_loss,
        proposed_take_profit=record.proposed_take_profit,
        error_message=record.error_message or "",
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def protective_evidence_label(row: SteeringDecisionRow) -> str:
    diagnostics = row.diagnostics
    if diagnostics.get("has_open_position") is False:
        return "position_already_closed"
    if diagnostics.get("linked_exit_orders_missing") is True:
        return "missing_active_protective_orders"
    if diagnostics.get("has_open_position") is True:
        return "protective_orders_present"
    if row.decision == "close_position_now" and row.error_message:
        return "missing_filled_exit_order"
    return "protective_orders_unavailable"


def suspicious_reasons(row: SteeringDecisionRow) -> list[str]:
    reasons: list[str] = []
    if row.decision in AMENDMENT_DECISIONS | CLOSE_NOW_DECISIONS and row.current_price is None:
        reasons.append("missing_current_price")
    if (
        row.decision in AMENDMENT_DECISIONS
        and row.proposed_stop_loss is None
        and row.proposed_take_profit is None
    ):
        reasons.append("amendment_without_proposed_level")
    if row.decision in CLOSE_NOW_DECISIONS and not row.reason_codes:
        reasons.append("close_now_without_reason_codes")
    if any("stale" in reason.lower() for reason in row.reason_codes):
        reasons.append("stale_evidence_reason")
    if any("missing" in reason.lower() for reason in row.reason_codes):
        reasons.append("missing_evidence_reason")
    if row.diagnostics.get("linked_exit_orders_missing") is True:
        reasons.append("missing_active_protective_orders")
    expiration_at = _parse_datetime(row.diagnostics.get("expiration_at"))
    diagnostic_now = _parse_datetime(row.diagnostics.get("now"))
    if (
        expiration_at is not None
        and diagnostic_now is not None
        and expiration_at < diagnostic_now
        and row.decision in AMENDMENT_DECISIONS | CLOSE_NOW_DECISIONS
    ):
        reasons.append("expired_plan_still_open")
    risk_delta = row.risk_delta.get("risk_delta_usd")
    try:
        if risk_delta is not None and float(risk_delta) > 0:
            reasons.append("risk_increasing_delta")
    except (TypeError, ValueError):
        reasons.append("unparseable_risk_delta")
    if row.error_message:
        reasons.append("has_error_message")
    return reasons


def build_report(rows: list[SteeringDecisionRow], *, sample_size: int, seed: int) -> dict[str, Any]:
    dry_rows = [row for row in rows if row.execution_status == "dry_run"]
    amendment_rows = [row for row in dry_rows if row.decision in AMENDMENT_DECISIONS]
    close_rows = [row for row in dry_rows if row.decision in CLOSE_NOW_DECISIONS]
    by_decision = Counter(row.decision for row in dry_rows)
    by_ticker = Counter(row.ticker for row in dry_rows)
    by_account = Counter(row.broker_account_id for row in dry_rows)
    reason_counts: Counter[str] = Counter()
    for row in dry_rows:
        reason_counts.update(row.reason_codes)
    protective_evidence_counts = Counter(protective_evidence_label(row) for row in dry_rows)
    suspicious: list[dict[str, Any]] = []
    suspicious_counts: Counter[str] = Counter()
    for row in dry_rows:
        reasons = suspicious_reasons(row)
        if reasons:
            suspicious_counts.update(reasons)
            suspicious.append({**sample_payload(row), "suspicious_reasons": reasons})
    rng = random.Random(seed)
    random_pool = list(dry_rows)
    random_samples = (
        rng.sample(random_pool, k=min(sample_size, len(random_pool))) if random_pool else []
    )
    recent_samples = sorted(dry_rows, key=lambda item: item.id or 0, reverse=True)[:sample_size]
    close_samples = sorted(close_rows, key=lambda item: item.id or 0, reverse=True)[:sample_size]
    amendment_samples = sorted(amendment_rows, key=lambda item: item.id or 0, reverse=True)[
        :sample_size
    ]
    return {
        "thresholds": {
            name: {
                "required": required,
                "actual": actual,
                "met": actual >= required,
            }
            for name, required, actual in [
                (
                    "dry_run_decisions",
                    DEFAULT_REVIEW_THRESHOLDS["dry_run_decisions"],
                    len(dry_rows),
                ),
                (
                    "dry_run_amendments",
                    DEFAULT_REVIEW_THRESHOLDS["dry_run_amendments"],
                    len(amendment_rows),
                ),
                (
                    "dry_run_close_now",
                    DEFAULT_REVIEW_THRESHOLDS["dry_run_close_now"],
                    len(close_rows),
                ),
            ]
        },
        "totals": {
            "all_rows_loaded": len(rows),
            "dry_run_decisions": len(dry_rows),
            "dry_run_amendments": len(amendment_rows),
            "dry_run_close_now": len(close_rows),
            "suspicious_decisions": len(suspicious),
        },
        "by_decision": dict(by_decision.most_common()),
        "by_ticker_top_25": dict(by_ticker.most_common(25)),
        "by_broker_account": dict(by_account.most_common()),
        "reason_codes_top_50": dict(reason_counts.most_common(50)),
        "suspicious_reason_counts": dict(suspicious_counts.most_common()),
        "protective_evidence_counts": dict(protective_evidence_counts.most_common()),
        "samples": {
            "recent": [sample_payload(row) for row in recent_samples],
            "random": [sample_payload(row) for row in random_samples],
            "close_now_recent": [sample_payload(row) for row in close_samples],
            "amendment_recent": [sample_payload(row) for row in amendment_samples],
            "suspicious_recent": suspicious[:sample_size],
        },
        "review_guidance": {
            "labels": ["correct", "too_aggressive", "too_conservative", "bad_data", "unclear"],
            "next_step": (
                "Manually review close_now_recent, amendment_recent, and suspicious_recent "
                "before enabling broker mutation."
            ),
        },
    }


def sample_payload(row: SteeringDecisionRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_account_id": row.broker_account_id,
        "ticker": row.ticker,
        "decision": row.decision,
        "execute_allowed": row.execute_allowed,
        "reason_codes": row.reason_codes,
        "current_price": row.current_price,
        "current_stop_loss": row.current_stop_loss,
        "current_take_profit": row.current_take_profit,
        "proposed_stop_loss": row.proposed_stop_loss,
        "proposed_take_profit": row.proposed_take_profit,
        "risk_delta": row.risk_delta,
        "diagnostics": row.diagnostics,
        "protective_evidence": protective_evidence_label(row),
        "error_message": row.error_message,
        "created_at": row.created_at,
    }


def write_csv_review_queue(path: Path, report: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for sample_group, samples in report["samples"].items():
        for sample in samples:
            rows.append({"sample_group": sample_group, **sample})
    fieldnames = [
        "sample_group",
        "id",
        "broker_account_id",
        "ticker",
        "decision",
        "execute_allowed",
        "reason_codes",
        "current_price",
        "current_stop_loss",
        "current_take_profit",
        "proposed_stop_loss",
        "proposed_take_profit",
        "risk_delta",
        "diagnostics",
        "protective_evidence",
        "error_message",
        "created_at",
        "suspicious_reasons",
        "human_review_label",
        "human_review_notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, default=str)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in {
                        **row,
                        "human_review_label": "",
                        "human_review_notes": "",
                    }.items()
                }
            )


def fetch_rows(session: Session, *, limit: int | None) -> list[SteeringDecisionRow]:
    query = select(BrokerSteeringDecisionRecord).order_by(BrokerSteeringDecisionRecord.id.desc())
    if limit is not None:
        query = query.limit(max(1, limit))
    return [row_from_record(record) for record in session.scalars(query).all()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report steering dry-run quality for manual review."
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional max rows to load, newest first."
    )
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--csv-review-output", type=Path, default=None)
    args = parser.parse_args()

    engine = create_engine(args.database_url, future=True)
    try:
        with Session(bind=engine) as session:
            rows = fetch_rows(session, limit=args.limit)
    finally:
        engine.dispose()
    report = build_report(rows, sample_size=args.sample_size, seed=args.seed)
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n")
    else:
        print(rendered)
    if args.csv_review_output:
        write_csv_review_queue(args.csv_review_output, report)
        print(f"Wrote CSV review queue to {args.csv_review_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
