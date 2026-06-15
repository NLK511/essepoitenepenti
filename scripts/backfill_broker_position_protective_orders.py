#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import BrokerPositionRecord

STOP_TYPES = {"stop", "stop_limit", "stop_order"}
TAKE_PROFIT_TYPES = {"limit", "limit_order"}


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None and str(value).strip() else None


def extract_protective_order_evidence(payload: dict[str, Any]) -> dict[str, object]:
    legs_value = payload.get("legs")
    legs = (
        [leg for leg in legs_value if isinstance(leg, dict)] if isinstance(legs_value, list) else []
    )
    evidence: dict[str, object] = {}
    for leg in legs:
        leg_type = str(leg.get("type") or leg.get("order_type") or "").strip().lower()
        status = _str_or_none(leg.get("status"))
        if leg_type in STOP_TYPES:
            evidence["stop_loss_order_id"] = _str_or_none(leg.get("id"))
            evidence["stop_loss_order_status"] = status
            evidence["stop_loss_order_price"] = _float_or_none(leg.get("stop_price"))
        elif leg_type in TAKE_PROFIT_TYPES:
            evidence["take_profit_order_id"] = _str_or_none(leg.get("id"))
            evidence["take_profit_order_status"] = status
            evidence["take_profit_order_price"] = _float_or_none(leg.get("limit_price"))
    if any(evidence.values()):
        evidence["protective_orders_verified_at"] = datetime.now(UTC)
        evidence["protective_orders_source"] = "broker_order_legs_backfill"
    return evidence


def backfill(database_url: str, *, dry_run: bool = False) -> dict[str, object]:
    engine = create_engine(database_url, future=True)
    scanned = updated = with_evidence = ambiguous = 0
    try:
        with Session(bind=engine) as session:
            rows = session.scalars(select(BrokerPositionRecord)).all()
            for row in rows:
                scanned += 1
                evidence = extract_protective_order_evidence(_loads(row.raw_broker_payload_json))
                if not evidence:
                    continue
                with_evidence += 1
                if (
                    row.stop_loss_order_id == evidence.get("stop_loss_order_id")
                    and row.take_profit_order_id == evidence.get("take_profit_order_id")
                    and row.stop_loss_order_status == evidence.get("stop_loss_order_status")
                    and row.take_profit_order_status == evidence.get("take_profit_order_status")
                ):
                    continue
                if row.stop_loss_order_id and row.stop_loss_order_id != evidence.get(
                    "stop_loss_order_id"
                ):
                    ambiguous += 1
                    continue
                if row.take_profit_order_id and row.take_profit_order_id != evidence.get(
                    "take_profit_order_id"
                ):
                    ambiguous += 1
                    continue
                updated += 1
                if dry_run:
                    continue
                row.stop_loss_order_id = evidence.get("stop_loss_order_id")  # type: ignore[assignment]
                row.stop_loss_order_status = evidence.get("stop_loss_order_status")  # type: ignore[assignment]
                row.stop_loss_order_price = evidence.get("stop_loss_order_price")  # type: ignore[assignment]
                row.take_profit_order_id = evidence.get("take_profit_order_id")  # type: ignore[assignment]
                row.take_profit_order_status = evidence.get("take_profit_order_status")  # type: ignore[assignment]
                row.take_profit_order_price = evidence.get("take_profit_order_price")  # type: ignore[assignment]
                row.protective_orders_verified_at = evidence.get("protective_orders_verified_at")  # type: ignore[assignment]
                row.protective_orders_source = str(evidence.get("protective_orders_source") or "")
            if not dry_run:
                session.commit()
    finally:
        engine.dispose()
    return {
        "status": "passed",
        "dry_run": dry_run,
        "scanned": scanned,
        "positions_with_payload_evidence": with_evidence,
        "updated": updated,
        "ambiguous": ambiguous,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill broker-neutral protective order evidence from raw bracket payload legs."
        )
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-output", type=Path, default=None)
    args = parser.parse_args()
    report = backfill(args.database_url, dry_run=args.dry_run)
    rendered = json.dumps(report, indent=2, default=str)
    print(rendered)
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
