from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationPlanOutcome
from trade_proposer_app.persistence.models import ReplayPlanOutcomeRecord


class ReplayPlanOutcomeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_outcome(
        self,
        *,
        replay_batch_id: int,
        replay_slice_id: int,
        run_id: int | None,
        recommendation_plan_id: int,
        candidate_config_hash: str | None,
        resolution_source: str,
        outcome: RecommendationPlanOutcome,
    ) -> dict[str, Any]:
        record = self.session.scalar(
            select(ReplayPlanOutcomeRecord).where(
                ReplayPlanOutcomeRecord.replay_slice_id == replay_slice_id,
                ReplayPlanOutcomeRecord.recommendation_plan_id == recommendation_plan_id,
                ReplayPlanOutcomeRecord.candidate_config_hash == (candidate_config_hash or ""),
            )
        )
        if record is None:
            record = ReplayPlanOutcomeRecord(
                replay_batch_id=replay_batch_id,
                replay_slice_id=replay_slice_id,
                recommendation_plan_id=recommendation_plan_id,
                candidate_config_hash=candidate_config_hash or "",
            )
            self.session.add(record)
        record.run_id = run_id
        record.resolution_source = resolution_source
        record.outcome = outcome.outcome
        record.status = outcome.status
        record.evaluated_at = self._dt(outcome.evaluated_at) or datetime.now(timezone.utc)
        record.outcome_json = json.dumps(outcome.model_dump(mode="json"), sort_keys=True)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dict(record)

    def bulk_upsert_outcomes(self, items: list[dict[str, Any]], *, commit: bool = True) -> int:
        if not items:
            return 0
        now = datetime.now(timezone.utc)
        records: list[dict[str, Any]] = []
        for item in items:
            outcome = item["outcome"]
            evaluated_at = self._dt(outcome.evaluated_at) or now
            records.append(
                {
                    "replay_batch_id": int(item["replay_batch_id"]),
                    "replay_slice_id": int(item["replay_slice_id"]),
                    "run_id": item.get("run_id"),
                    "recommendation_plan_id": int(item["recommendation_plan_id"]),
                    "candidate_config_hash": item.get("candidate_config_hash") or "",
                    "resolution_source": str(item.get("resolution_source") or ""),
                    "outcome": outcome.outcome,
                    "status": outcome.status,
                    "evaluated_at": evaluated_at,
                    "outcome_json": json.dumps(outcome.model_dump(mode="json"), sort_keys=True),
                    "created_at": now,
                    "updated_at": now,
                }
            )

        dialect = self.session.bind.dialect.name if self.session.bind else "postgresql"
        table = ReplayPlanOutcomeRecord.__table__
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(table).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["replay_slice_id", "recommendation_plan_id", "candidate_config_hash"],
                set_={
                    "replay_batch_id": stmt.excluded.replay_batch_id,
                    "run_id": stmt.excluded.run_id,
                    "resolution_source": stmt.excluded.resolution_source,
                    "outcome": stmt.excluded.outcome,
                    "status": stmt.excluded.status,
                    "evaluated_at": stmt.excluded.evaluated_at,
                    "outcome_json": stmt.excluded.outcome_json,
                    "updated_at": now,
                },
            )
            result = self.session.execute(stmt)
            if commit:
                self.session.commit()
            return int(result.rowcount or 0)

        count = 0
        for record in records:
            existing = self.session.scalar(
                select(ReplayPlanOutcomeRecord).where(
                    ReplayPlanOutcomeRecord.replay_slice_id == record["replay_slice_id"],
                    ReplayPlanOutcomeRecord.recommendation_plan_id == record["recommendation_plan_id"],
                    ReplayPlanOutcomeRecord.candidate_config_hash == record["candidate_config_hash"],
                )
            )
            if existing is None:
                self.session.add(ReplayPlanOutcomeRecord(**record))
            else:
                for key, value in record.items():
                    if key != "created_at":
                        setattr(existing, key, value)
            count += 1
        if commit:
            self.session.commit()
        return count

    def list_for_slice(self, replay_slice_id: int) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(ReplayPlanOutcomeRecord)
            .where(ReplayPlanOutcomeRecord.replay_slice_id == replay_slice_id)
            .order_by(ReplayPlanOutcomeRecord.id.asc())
        ).all()
        return [self._to_dict(row) for row in rows]

    @classmethod
    def _to_dict(cls, record: ReplayPlanOutcomeRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "replay_batch_id": record.replay_batch_id,
            "replay_slice_id": record.replay_slice_id,
            "run_id": record.run_id,
            "recommendation_plan_id": record.recommendation_plan_id,
            "candidate_config_hash": record.candidate_config_hash,
            "resolution_source": record.resolution_source,
            "outcome": record.outcome,
            "status": record.status,
            "evaluated_at": cls._dt(record.evaluated_at),
            "outcome_payload": cls._loads(record.outcome_json),
            "created_at": cls._dt(record.created_at),
            "updated_at": cls._dt(record.updated_at),
        }

    @staticmethod
    def _loads(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
