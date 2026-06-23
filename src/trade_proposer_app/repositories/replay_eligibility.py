from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import ReplayEligibilityRecord


class ReplayEligibilityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_record(
        self,
        *,
        replay_batch_id: int,
        replay_slice_id: int,
        replay_plan_outcome_id: int | None,
        recommendation_plan_id: int,
        run_id: int | None,
        ticker: str,
        candidate_config_hash: str | None,
        tier: str,
        eligible_for_tuning: bool,
        resolution_source: str,
        outcome: str,
        rejection_reasons: list[str],
        diagnostics: dict[str, Any],
        eligibility_mode: str = "current_code_point_in_time_replay",
    ) -> dict[str, Any]:
        normalized_hash = candidate_config_hash or ""
        record = self.session.scalar(
            select(ReplayEligibilityRecord).where(
                ReplayEligibilityRecord.replay_slice_id == replay_slice_id,
                ReplayEligibilityRecord.recommendation_plan_id == recommendation_plan_id,
                ReplayEligibilityRecord.candidate_config_hash == normalized_hash,
            )
        )
        if record is None:
            record = ReplayEligibilityRecord(
                replay_batch_id=replay_batch_id,
                replay_slice_id=replay_slice_id,
                recommendation_plan_id=recommendation_plan_id,
                candidate_config_hash=normalized_hash,
            )
            self.session.add(record)
        record.replay_batch_id = replay_batch_id
        record.replay_plan_outcome_id = replay_plan_outcome_id
        record.run_id = run_id
        record.ticker = ticker.upper()
        record.eligibility_mode = eligibility_mode
        record.tier = tier
        record.eligible_for_tuning = bool(eligible_for_tuning)
        record.resolution_source = resolution_source
        record.outcome = outcome
        record.rejection_reasons_json = json.dumps(sorted(set(rejection_reasons)))
        record.diagnostics_json = json.dumps(diagnostics, sort_keys=True, default=str)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dict(record)

    def list_for_slice(self, replay_slice_id: int) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(ReplayEligibilityRecord)
            .where(ReplayEligibilityRecord.replay_slice_id == replay_slice_id)
            .order_by(ReplayEligibilityRecord.id.asc())
        ).all()
        return [self._to_dict(row) for row in rows]

    @classmethod
    def _to_dict(cls, record: ReplayEligibilityRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "replay_batch_id": record.replay_batch_id,
            "replay_slice_id": record.replay_slice_id,
            "replay_plan_outcome_id": record.replay_plan_outcome_id,
            "recommendation_plan_id": record.recommendation_plan_id,
            "run_id": record.run_id,
            "ticker": record.ticker,
            "candidate_config_hash": record.candidate_config_hash,
            "eligibility_mode": record.eligibility_mode,
            "tier": record.tier,
            "eligible_for_tuning": record.eligible_for_tuning,
            "resolution_source": record.resolution_source,
            "outcome": record.outcome,
            "rejection_reasons": cls._loads_list(record.rejection_reasons_json),
            "diagnostics": cls._loads_dict(record.diagnostics_json),
            "created_at": cls._dt(record.created_at),
            "updated_at": cls._dt(record.updated_at),
        }

    @staticmethod
    def _loads_dict(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _loads_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in loaded] if isinstance(loaded, list) else []

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
