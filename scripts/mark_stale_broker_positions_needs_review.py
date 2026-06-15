#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import BrokerPositionRecord, RecommendationPlanRecord


def _now(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def expired_position_ids(session: Session, *, now: datetime) -> list[int]:
    positions = session.scalars(
        select(BrokerPositionRecord).where(
            BrokerPositionRecord.status.in_(["submitted", "open", "closing"])
        )
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
    result: list[int] = []
    for position in positions:
        plan = plans.get(position.recommendation_plan_id)
        computed_at = _as_utc(plan.computed_at if plan is not None else None)
        holding_days = (
            int(plan.holding_period_days) if plan is not None and plan.holding_period_days else None
        )
        if computed_at is None or holding_days is None:
            continue
        expiration_at = computed_at + timedelta(days=max(1, holding_days))
        if expiration_at < now and position.id is not None:
            result.append(int(position.id))
    return result


def mark_needs_review(
    database_url: str,
    *,
    now: datetime,
    reason: str,
    apply: bool,
) -> dict[str, object]:
    engine = create_engine(database_url, future=True)
    try:
        with Session(bind=engine) as session:
            ids = expired_position_ids(session, now=now)
            updated = 0
            if apply:
                rows = session.scalars(
                    select(BrokerPositionRecord).where(BrokerPositionRecord.id.in_(ids))
                ).all()
                for row in rows:
                    row.status = "needs_review"
                    row.error_message = reason
                    row.updated_at = now
                    updated += 1
                session.commit()
            return {
                "status": "passed",
                "apply": apply,
                "candidate_count": len(ids),
                "updated": updated,
                "reason": reason,
                "position_ids": ids,
            }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mark expired app broker-position ledger rows as needs_review after operator review."
        )
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--now", default=None)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-output", type=Path, default=None)
    args = parser.parse_args()
    if args.apply and not args.reason.strip():
        parser.error("--reason is required when applying changes")
    report = mark_needs_review(
        args.database_url, now=_now(args.now), reason=args.reason.strip(), apply=args.apply
    )
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(rendered)
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
