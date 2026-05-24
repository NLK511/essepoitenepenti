from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerReconciliationSnapshot
from trade_proposer_app.persistence.models import BrokerReconciliationSnapshotRecord


class BrokerReconciliationSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, snapshot: BrokerReconciliationSnapshot) -> BrokerReconciliationSnapshot:
        record = BrokerReconciliationSnapshotRecord(
            broker=snapshot.broker,
            account_mode=snapshot.account_mode,
            snapshot_type=snapshot.snapshot_type,
            run_id=snapshot.run_id,
            job_id=snapshot.job_id,
            broker_order_execution_id=snapshot.broker_order_execution_id,
            ticker=snapshot.ticker.upper() if snapshot.ticker else "",
            account_payload_json=self._dump(snapshot.account_payload or {}),
            open_orders_payload_json=self._dump(snapshot.open_orders_payload),
            open_positions_payload_json=self._dump(snapshot.open_positions_payload),
            warnings_json=self._dump(snapshot.warnings),
            drift_severity=snapshot.drift_severity,
            drift_reasons_json=self._dump(snapshot.drift_reasons),
            created_at=self._normalize_datetime(snapshot.created_at) or datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_latest(self, *, run_id: int | None = None, limit: int = 50) -> list[BrokerReconciliationSnapshot]:
        query = select(BrokerReconciliationSnapshotRecord)
        if run_id is not None:
            query = query.where(BrokerReconciliationSnapshotRecord.run_id == run_id)
        query = query.order_by(BrokerReconciliationSnapshotRecord.created_at.desc(), BrokerReconciliationSnapshotRecord.id.desc()).limit(max(1, min(int(limit), 500)))
        return [self._to_model(record) for record in self.session.scalars(query).all()]

    def list_latest_for_ticker(self, ticker: str, *, limit: int = 1) -> list[BrokerReconciliationSnapshot]:
        query = (
            select(BrokerReconciliationSnapshotRecord)
            .where(BrokerReconciliationSnapshotRecord.ticker == ticker.upper())
            .order_by(BrokerReconciliationSnapshotRecord.created_at.desc(), BrokerReconciliationSnapshotRecord.id.desc())
            .limit(max(1, min(int(limit), 50)))
        )
        return [self._to_model(record) for record in self.session.scalars(query).all()]

    def _to_model(self, record: BrokerReconciliationSnapshotRecord) -> BrokerReconciliationSnapshot:
        return BrokerReconciliationSnapshot(
            id=record.id,
            broker=record.broker,
            account_mode=record.account_mode,
            snapshot_type=record.snapshot_type,
            run_id=record.run_id,
            job_id=record.job_id,
            broker_order_execution_id=record.broker_order_execution_id,
            ticker=record.ticker,
            account_payload=self._load_dict(record.account_payload_json),
            open_orders_payload=self._load_list_of_dicts(record.open_orders_payload_json),
            open_positions_payload=self._load_list_of_dicts(record.open_positions_payload_json),
            warnings=[str(item) for item in self._load_list(record.warnings_json)],
            drift_severity=record.drift_severity,
            drift_reasons=[str(item) for item in self._load_list(record.drift_reasons_json)],
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
        )

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=str, sort_keys=True)

    @classmethod
    def _load_dict(cls, raw: str | None) -> dict[str, object]:
        value = cls._load(raw, {})
        return value if isinstance(value, dict) else {}

    @classmethod
    def _load_list(cls, raw: str | None) -> list[object]:
        value = cls._load(raw, [])
        return value if isinstance(value, list) else []

    @classmethod
    def _load_list_of_dicts(cls, raw: str | None) -> list[dict[str, object]]:
        return [item for item in cls._load_list(raw) if isinstance(item, dict)]

    @staticmethod
    def _load(raw: str | None, default: object) -> object:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
