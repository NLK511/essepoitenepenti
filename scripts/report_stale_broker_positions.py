#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import BrokerPositionRecord, RecommendationPlanRecord

ACTIVE_POSITION_STATUSES = {"open", "closing"}
ACTIVE_PROTECTIVE_STATUSES = {"new", "open", "accepted", "submitted", "partially_filled"}


def _normalize_now(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_active_protective(order_id: str | None, status: str | None) -> bool:
    if not order_id:
        return False
    normalized = str(status or "").strip().lower()
    return normalized in ACTIVE_PROTECTIVE_STATUSES


def _position_row_payload(
    position: BrokerPositionRecord, plan: RecommendationPlanRecord | None, now: datetime
) -> dict[str, Any]:
    status = str(position.status or "").strip().lower()
    computed_at = _as_utc(plan.computed_at if plan is not None else None)
    holding_days = (
        int(plan.holding_period_days) if plan is not None and plan.holding_period_days else None
    )
    expiration_at = None
    if computed_at is not None and holding_days is not None:
        from datetime import timedelta

        expiration_at = computed_at + timedelta(days=max(1, holding_days))
    expired = bool(expiration_at is not None and expiration_at < now)
    quantity_zero_submitted = status == "submitted" and int(position.current_quantity or 0) <= 0
    open_amendable = status in ACTIVE_POSITION_STATUSES and int(position.current_quantity or 0) > 0
    protective_present = _is_active_protective(
        position.stop_loss_order_id, position.stop_loss_order_status
    ) or _is_active_protective(position.take_profit_order_id, position.take_profit_order_status)
    stale_verification = position.protective_orders_verified_at is None
    return {
        "position_id": position.id,
        "broker_account_id": position.broker_account_id,
        "ticker": position.ticker,
        "status": position.status,
        "current_quantity": position.current_quantity,
        "recommendation_plan_id": position.recommendation_plan_id,
        "computed_at": computed_at.isoformat() if computed_at else None,
        "expiration_at": expiration_at.isoformat() if expiration_at else None,
        "expired_plan": expired,
        "quantity_zero_submitted": quantity_zero_submitted,
        "open_amendable": open_amendable,
        "protective_orders_present": protective_present,
        "protective_orders_verified_at": position.protective_orders_verified_at.isoformat()
        if position.protective_orders_verified_at
        else None,
        "protective_orders_source": position.protective_orders_source,
        "stale_protective_verification": stale_verification,
    }


def build_report(session: Session, *, now: datetime) -> dict[str, Any]:
    positions = session.scalars(
        select(BrokerPositionRecord)
        .where(BrokerPositionRecord.status.in_(["submitted", "open", "closing"]))
        .order_by(BrokerPositionRecord.created_at.desc())
    ).all()
    plan_ids = {
        position.recommendation_plan_id for position in positions if position.recommendation_plan_id
    }
    plans = {}
    if plan_ids:
        plans = {
            plan.id: plan
            for plan in session.scalars(
                select(RecommendationPlanRecord).where(RecommendationPlanRecord.id.in_(plan_ids))
            ).all()
        }
    rows = [
        _position_row_payload(position, plans.get(position.recommendation_plan_id), now)
        for position in positions
    ]
    summary = {
        "active_app_position_rows": len(rows),
        "open_amendable_rows": sum(1 for row in rows if row["open_amendable"]),
        "expired_plan_rows": sum(1 for row in rows if row["expired_plan"]),
        "quantity_zero_submitted_rows": sum(1 for row in rows if row["quantity_zero_submitted"]),
        "missing_active_protective_orders": sum(
            1 for row in rows if row["open_amendable"] and not row["protective_orders_present"]
        ),
        "stale_protective_verification_rows": sum(
            1 for row in rows if row["stale_protective_verification"]
        ),
    }
    return {"status": "passed", "generated_at": now.isoformat(), "summary": summary, "rows": rows}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "position_id",
        "broker_account_id",
        "ticker",
        "status",
        "current_quantity",
        "recommendation_plan_id",
        "computed_at",
        "expiration_at",
        "expired_plan",
        "quantity_zero_submitted",
        "open_amendable",
        "protective_orders_present",
        "protective_orders_verified_at",
        "protective_orders_source",
        "stale_protective_verification",
        "human_review_label",
        "human_review_notes",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "human_review_label": "", "human_review_notes": ""})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report stale app broker-position ledger rows for manual review."
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--now", default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--csv-output", type=Path, default=None)
    args = parser.parse_args()
    now = _normalize_now(args.now)
    engine = create_engine(args.database_url, future=True)
    try:
        with Session(bind=engine) as session:
            report = build_report(session, now=now)
    finally:
        engine.dispose()
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n")
    else:
        print(rendered)
    if args.csv_output:
        write_csv(args.csv_output, report["rows"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
