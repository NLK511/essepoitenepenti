from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RiskHaltEvent
from trade_proposer_app.persistence.models import RiskHaltEventRecord


class RiskHaltEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        action: str,
        reason: str,
        previous_halt_enabled: bool,
        new_halt_enabled: bool,
        actor: str = "operator",
    ) -> RiskHaltEvent:
        record = RiskHaltEventRecord(
            action=action.strip().lower(),
            reason=reason.strip(),
            previous_halt_enabled=bool(previous_halt_enabled),
            new_halt_enabled=bool(new_halt_enabled),
            actor=actor.strip() or "operator",
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_latest(self, *, limit: int = 50) -> list[RiskHaltEvent]:
        rows = self.session.scalars(
            select(RiskHaltEventRecord)
            .order_by(RiskHaltEventRecord.created_at.desc(), RiskHaltEventRecord.id.desc())
            .limit(max(1, limit))
        ).all()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(record: RiskHaltEventRecord) -> RiskHaltEvent:
        return RiskHaltEvent(
            id=record.id,
            action=record.action,
            reason=record.reason,
            previous_halt_enabled=record.previous_halt_enabled,
            new_halt_enabled=record.new_halt_enabled,
            actor=record.actor,
            created_at=record.created_at if record.created_at.tzinfo is not None else record.created_at.replace(tzinfo=timezone.utc),
        )
