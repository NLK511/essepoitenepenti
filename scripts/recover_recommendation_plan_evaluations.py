#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import case, desc, select
from sqlalchemy.orm import Session

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import RecommendationOutcomeRecord, RecommendationPlanRecord
from trade_proposer_app.services.recommendation_plan_evaluations import (
    RecommendationPlanEvaluationService,
)


def select_recovery_candidate_ids(
    session: Session,
    *,
    limit: int,
    only_tagged: bool = False,
    include_stale_unresolved: bool = False,
) -> list[int]:
    outcome_plan_ids = select(RecommendationOutcomeRecord.recommendation_plan_id)
    resolved_plan_ids = select(RecommendationOutcomeRecord.recommendation_plan_id).where(
        RecommendationOutcomeRecord.status == "resolved"
    )
    tagged_priority = case(
        (RecommendationPlanRecord.signal_breakdown_json.like("%upstream_signal_quality_drivers%"), 1),
        else_=0,
    )
    query = (
        select(RecommendationPlanRecord.id)
        .where(RecommendationPlanRecord.action.in_(["long", "short", "no_action", "watchlist"]))
        .order_by(
            desc(tagged_priority),
            RecommendationPlanRecord.computed_at.asc(),
            RecommendationPlanRecord.id.asc(),
        )
        .limit(max(1, int(limit)))
    )
    if only_tagged:
        query = query.where(
            RecommendationPlanRecord.signal_breakdown_json.like(
                "%upstream_signal_quality_drivers%"
            )
        )
    if include_stale_unresolved:
        query = query.where(RecommendationPlanRecord.id.not_in(resolved_plan_ids))
    else:
        query = query.where(RecommendationPlanRecord.id.not_in(outcome_plan_ids))
    return [int(item) for item in session.scalars(query).all()]


def run_recovery(
    *,
    chunk_size: int,
    only_tagged: bool,
    include_stale_unresolved: bool,
    dry_run: bool,
    artifact_path: Path | None,
) -> dict[str, object]:
    started = datetime.now(timezone.utc)
    processed_total = 0
    synced_total = 0
    chunks = 0
    outcomes: Counter[str] = Counter()

    while True:
        session = SessionLocal()
        try:
            ids = select_recovery_candidate_ids(
                session,
                limit=chunk_size,
                only_tagged=only_tagged,
                include_stale_unresolved=include_stale_unresolved,
            )
            if not ids or dry_run:
                summary = {
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "dry_run": dry_run,
                    "chunk_size": chunk_size,
                    "only_tagged": only_tagged,
                    "include_stale_unresolved": include_stale_unresolved,
                    "next_candidate_count": len(ids),
                    "next_candidate_ids": ids[:20],
                    "chunks": chunks,
                    "processed": processed_total,
                    "synced": synced_total,
                    "outcomes": dict(sorted(outcomes.items())),
                }
                _write_artifact(artifact_path, summary)
                return summary

            chunks += 1
            result = RecommendationPlanEvaluationService(session).run_evaluation(
                recommendation_plan_ids=ids,
                as_of=datetime.now(timezone.utc),
            )
            session.commit()
            processed_total += int(result.evaluated_recommendation_plans or 0)
            synced_total += int(result.synced_recommendation_plan_outcomes or 0)
            outcomes.update(
                {
                    "pending": int(result.pending_recommendation_plan_outcomes or 0),
                    "win": int(result.win_recommendation_plan_outcomes or 0),
                    "loss": int(result.loss_recommendation_plan_outcomes or 0),
                    "no_action": int(result.no_action_recommendation_plan_outcomes or 0),
                    "watchlist": int(result.watchlist_recommendation_plan_outcomes or 0),
                }
            )
            progress = {
                "started_at": started.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "dry_run": dry_run,
                "chunk_size": chunk_size,
                "only_tagged": only_tagged,
                "include_stale_unresolved": include_stale_unresolved,
                "chunks": chunks,
                "processed": processed_total,
                "synced": synced_total,
                "last_chunk_size": len(ids),
                "last_first_id": ids[0],
                "last_last_id": ids[-1],
                "outcomes": dict(sorted(outcomes.items())),
            }
            _write_artifact(artifact_path, progress)
            print(json.dumps(progress, sort_keys=True), flush=True)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _write_artifact(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover missing recommendation plan evaluations in explicit chunks."
    )
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--only-tagged", action="store_true")
    parser.add_argument("--include-stale-unresolved", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args()

    summary = run_recovery(
        chunk_size=args.chunk_size,
        only_tagged=args.only_tagged,
        include_stale_unresolved=args.include_stale_unresolved,
        dry_run=args.dry_run,
        artifact_path=args.artifact,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
