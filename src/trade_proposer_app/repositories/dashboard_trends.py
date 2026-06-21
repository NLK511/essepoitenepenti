from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import DashboardTrendSnapshotRecord
from trade_proposer_app.utils.json_payloads import loads_json_object


class DashboardTrendRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._ensure_table()

    def _ensure_table(self) -> None:
        bind = self.session.get_bind()
        if bind is None:
            return
        DashboardTrendSnapshotRecord.__table__.create(bind=bind, checkfirst=True)

    def get_snapshot(self, snapshot_date: date) -> dict[str, object] | None:
        record = self.session.scalar(
            select(DashboardTrendSnapshotRecord)
            .where(DashboardTrendSnapshotRecord.snapshot_date == snapshot_date)
            .limit(1)
        )
        if record is None:
            return None
        return loads_json_object(record.snapshot_json)

    def upsert_snapshot(self, snapshot_date: date, payload: dict[str, object]) -> dict[str, object]:
        record = self.session.scalar(
            select(DashboardTrendSnapshotRecord)
            .where(DashboardTrendSnapshotRecord.snapshot_date == snapshot_date)
            .limit(1)
        )
        snapshot_json = self._dump(payload)
        if record is None:
            record = DashboardTrendSnapshotRecord(
                snapshot_date=snapshot_date,
                computed_at=datetime.now(timezone.utc),
                snapshot_json=snapshot_json,
            )
            self.session.add(record)
        else:
            record.computed_at = datetime.now(timezone.utc)
            record.snapshot_json = snapshot_json
        self.session.commit()
        return payload

    @staticmethod
    def _dump(payload: dict[str, object]) -> str:
        return json.dumps(payload, default=str)
