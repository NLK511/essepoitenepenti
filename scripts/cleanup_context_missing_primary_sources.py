#!/usr/bin/env python3
"""Dry-run or delete context snapshots that were created without primary news evidence.

This targets macro and industry context snapshots that were generated with
missing primary sources, typically indicated by:
- missing_inputs containing primary_news_evidence / primary_industry_news_evidence
- zero primary_news_item_count in source_breakdown

Safety model:
- dry-run by default
- apply mode requires both --apply and --yes
- date filters are optional
- macro and industry snapshots are handled separately

Examples:
  .venv/bin/python scripts/cleanup_context_missing_primary_sources.py
  .venv/bin/python scripts/cleanup_context_missing_primary_sources.py --start-date 2026-04-20 --end-date 2026-04-24
  .venv/bin/python scripts/cleanup_context_missing_primary_sources.py --apply --yes --output cleanup-context-backup.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import IndustryContextSnapshotRecord, MacroContextSnapshotRecord


@dataclass(frozen=True)
class SnapshotCandidate:
    kind: str
    id: int
    computed_at: datetime
    status: str
    summary_text: str
    missing_inputs: list[str]
    primary_news_item_count: int
    primary_news_coverage_quality: str | None
    run_id: int | None
    job_id: int | None


def parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError("dates must use YYYY-MM-DD or DD/MM/YYYY")


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, dict):
        return {str(key): _normalize(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(item) for item in value]
    return value


def _load_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _primary_news_item_count(source_breakdown: dict[str, Any]) -> int:
    raw = source_breakdown.get("primary_news_item_count", 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _primary_news_coverage_quality(source_breakdown: dict[str, Any]) -> str | None:
    raw = source_breakdown.get("primary_news_coverage_quality")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _missing_inputs(values: Iterable[Any]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _macro_candidate(record: MacroContextSnapshotRecord) -> SnapshotCandidate | None:
    missing_inputs = _missing_inputs(_load_json(record.missing_inputs_json, []))
    source_breakdown = _load_json(record.source_breakdown_json, {})
    if not isinstance(source_breakdown, dict):
        source_breakdown = {}
    primary_news_item_count = _primary_news_item_count(source_breakdown)
    if "primary_news_evidence" not in missing_inputs and primary_news_item_count > 0:
        return None
    return SnapshotCandidate(
        kind="macro",
        id=int(record.id),
        computed_at=record.computed_at,
        status=record.status,
        summary_text=record.summary_text,
        missing_inputs=sorted(missing_inputs),
        primary_news_item_count=primary_news_item_count,
        primary_news_coverage_quality=_primary_news_coverage_quality(source_breakdown),
        run_id=record.run_id,
        job_id=record.job_id,
    )


def _industry_candidate(record: IndustryContextSnapshotRecord) -> SnapshotCandidate | None:
    missing_inputs = _missing_inputs(_load_json(record.missing_inputs_json, []))
    source_breakdown = _load_json(record.source_breakdown_json, {})
    if not isinstance(source_breakdown, dict):
        source_breakdown = {}
    primary_news_item_count = _primary_news_item_count(source_breakdown)
    if "primary_industry_news_evidence" not in missing_inputs and "primary_news_evidence" not in missing_inputs and primary_news_item_count > 0:
        return None
    return SnapshotCandidate(
        kind="industry",
        id=int(record.id),
        computed_at=record.computed_at,
        status=record.status,
        summary_text=record.summary_text,
        missing_inputs=sorted(missing_inputs),
        primary_news_item_count=primary_news_item_count,
        primary_news_coverage_quality=_primary_news_coverage_quality(source_breakdown),
        run_id=record.run_id,
        job_id=record.job_id,
    )


def _in_date_range(value: datetime, start_date: date | None, end_date: date | None) -> bool:
    normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if start_date and normalized.date() < start_date:
        return False
    if end_date and normalized.date() > end_date:
        return False
    return True


def collect_candidates(
    session: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    include_macro: bool = True,
    include_industry: bool = True,
) -> list[SnapshotCandidate]:
    candidates: list[SnapshotCandidate] = []

    if include_macro:
        rows = session.scalars(select(MacroContextSnapshotRecord).order_by(MacroContextSnapshotRecord.computed_at.desc())).all()
        for record in rows:
            if start_date or end_date:
                if not _in_date_range(record.computed_at, start_date, end_date):
                    continue
            candidate = _macro_candidate(record)
            if candidate is not None:
                candidates.append(candidate)

    if include_industry:
        rows = session.scalars(select(IndustryContextSnapshotRecord).order_by(IndustryContextSnapshotRecord.computed_at.desc())).all()
        for record in rows:
            if start_date or end_date:
                if not _in_date_range(record.computed_at, start_date, end_date):
                    continue
            candidate = _industry_candidate(record)
            if candidate is not None:
                candidates.append(candidate)

    candidates.sort(key=lambda item: (item.computed_at, item.kind, item.id), reverse=True)
    return candidates


def build_payload(candidates: list[SnapshotCandidate], *, start_date: date | None, end_date: date | None) -> dict[str, Any]:
    macro = [candidate for candidate in candidates if candidate.kind == "macro"]
    industry = [candidate for candidate in candidates if candidate.kind == "industry"]
    return {
        "database_url": settings.database_url,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "candidate_count": len(candidates),
        "macro_candidate_count": len(macro),
        "industry_candidate_count": len(industry),
        "candidate_ids": {"macro": [item.id for item in macro], "industry": [item.id for item in industry]},
        "candidates": [
            {
                "kind": item.kind,
                "id": item.id,
                "computed_at": item.computed_at.isoformat(),
                "status": item.status,
                "missing_inputs": item.missing_inputs,
                "primary_news_item_count": item.primary_news_item_count,
                "primary_news_coverage_quality": item.primary_news_coverage_quality,
                "run_id": item.run_id,
                "job_id": item.job_id,
                "summary_text": item.summary_text[:160],
            }
            for item in candidates
        ],
    }


def _print_human(payload: dict[str, Any], *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"Context cleanup for missing primary sources ({mode})")
    print(f"Database: {payload['database_url']}")
    print(f"Candidate snapshots: {payload['candidate_count']}")
    print(f"- macro: {payload['macro_candidate_count']}")
    print(f"- industry: {payload['industry_candidate_count']}")
    print()
    print("Preview rows:")
    if payload["candidates"]:
        for item in payload["candidates"][:20]:
            print(
                "- "
                f"{item['kind']} id={item['id']} computed_at={item['computed_at']} status={item['status']} "
                f"primary_news_item_count={item['primary_news_item_count']} "
                f"missing_inputs={item['missing_inputs']}"
            )
    else:
        print("- none")


def _delete_candidates(session: Session, candidates: list[SnapshotCandidate]) -> dict[str, int]:
    macro_ids = [item.id for item in candidates if item.kind == "macro"]
    industry_ids = [item.id for item in candidates if item.kind == "industry"]
    deleted_macro = 0
    deleted_industry = 0

    if macro_ids:
        deleted_macro = int(
            session.execute(delete(MacroContextSnapshotRecord).where(MacroContextSnapshotRecord.id.in_(macro_ids))).rowcount or 0
        )
    if industry_ids:
        deleted_industry = int(
            session.execute(delete(IndustryContextSnapshotRecord).where(IndustryContextSnapshotRecord.id.in_(industry_ids))).rowcount or 0
        )
    session.commit()
    return {"macro": deleted_macro, "industry": deleted_industry}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=parse_date, default=None, help="Inclusive start date for cleanup")
    parser.add_argument("--end-date", type=parse_date, default=None, help="Inclusive end date for cleanup")
    parser.add_argument("--macro-only", action="store_true", help="Only consider macro snapshots")
    parser.add_argument("--industry-only", action="store_true", help="Only consider industry snapshots")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON backup/report path")
    parser.add_argument("--apply", action="store_true", help="Apply the cleanup instead of dry-run")
    parser.add_argument("--yes", action="store_true", help="Required with --apply to confirm destructive changes")
    args = parser.parse_args()

    if args.apply and not args.yes:
        parser.error("--apply requires --yes")

    include_macro = not args.industry_only
    include_industry = not args.macro_only
    if not include_macro and not include_industry:
        parser.error("choose at least one of --macro-only or --industry-only, or neither")

    engine = create_engine(settings.database_url, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        candidates = collect_candidates(
            session,
            start_date=args.start_date,
            end_date=args.end_date,
            include_macro=include_macro,
            include_industry=include_industry,
        )
        payload = build_payload(candidates, start_date=args.start_date, end_date=args.end_date)
        payload["mode"] = "apply" if args.apply else "dry_run"

        if args.output is not None:
            args.output.write_text(json.dumps(_normalize(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if not args.apply:
            if args.json:
                print(json.dumps(_normalize(payload), indent=2, sort_keys=True))
            else:
                _print_human(payload, apply=False)
                if args.output is not None:
                    print()
                    print(f"JSON report written to {args.output}")
            return 0

        if not candidates:
            if args.json:
                print(json.dumps(_normalize(payload), indent=2, sort_keys=True))
            else:
                _print_human(payload, apply=True)
                print()
                print("No matching snapshots found; nothing changed.")
            return 0

        deleted = _delete_candidates(session, candidates)
        payload["applied_changes"] = {
            "deleted_macro_snapshots": deleted["macro"],
            "deleted_industry_snapshots": deleted["industry"],
        }

        if args.output is not None:
            args.output.write_text(json.dumps(_normalize(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if args.json:
            print(json.dumps(_normalize(payload), indent=2, sort_keys=True))
        else:
            _print_human(payload, apply=True)
            print()
            print("Applied changes:")
            print(f"- deleted macro snapshots: {deleted['macro']}")
            print(f"- deleted industry snapshots: {deleted['industry']}")
            if args.output is not None:
                print(f"- JSON backup/report written to {args.output}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
