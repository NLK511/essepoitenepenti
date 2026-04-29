from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerPosition
from trade_proposer_app.persistence.models import BrokerPositionRecord


class BrokerPositionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_by_order_execution(self, position: BrokerPosition) -> BrokerPosition:
        existing = self.get_by_order_execution_id(position.broker_order_execution_id)
        if existing is None:
            return self.create(position)
        position.id = existing.id
        position.created_at = existing.created_at
        return self.update(position)

    def create(self, position: BrokerPosition) -> BrokerPosition:
        record = BrokerPositionRecord()
        self._apply(record, position)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def update(self, position: BrokerPosition) -> BrokerPosition:
        if position.id is None:
            raise ValueError("Broker position id is required for update")
        record = self.session.get(BrokerPositionRecord, position.id)
        if record is None:
            raise ValueError(f"Broker position {position.id} not found")
        self._apply(record, position)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def get(self, position_id: int) -> BrokerPosition:
        record = self.session.get(BrokerPositionRecord, position_id)
        if record is None:
            raise ValueError(f"Broker position {position_id} not found")
        return self._to_model(record)

    def get_by_order_execution_id(self, execution_id: int) -> BrokerPosition | None:
        record = self.session.scalar(select(BrokerPositionRecord).where(BrokerPositionRecord.broker_order_execution_id == execution_id))
        return self._to_model(record) if record is not None else None

    def list_all(self, *, run_id: int | None = None, limit: int = 200) -> list[BrokerPosition]:
        query = select(BrokerPositionRecord)
        if run_id is not None:
            query = query.where(BrokerPositionRecord.run_id == run_id)
        rows = self.session.scalars(query.order_by(BrokerPositionRecord.created_at.desc()).limit(max(1, limit))).all()
        return [self._to_model(row) for row in rows]

    def _apply(self, record: BrokerPositionRecord, position: BrokerPosition) -> None:
        record.broker_order_execution_id = position.broker_order_execution_id
        record.broker = position.broker
        record.account_mode = position.account_mode
        record.recommendation_plan_id = position.recommendation_plan_id
        record.recommendation_plan_ticker = position.recommendation_plan_ticker
        record.run_id = position.run_id
        record.job_id = position.job_id
        record.ticker = position.ticker
        record.action = position.action
        record.side = position.side
        record.quantity = position.quantity
        record.current_quantity = position.current_quantity
        record.status = position.status
        record.entry_order_id = position.entry_order_id
        record.entry_avg_price = position.entry_avg_price
        record.entry_filled_at = self._normalize_datetime(position.entry_filled_at)
        record.exit_order_id = position.exit_order_id
        record.exit_reason = position.exit_reason
        record.exit_avg_price = position.exit_avg_price
        record.exit_filled_at = self._normalize_datetime(position.exit_filled_at)
        record.realized_pnl = position.realized_pnl
        record.realized_return_pct = position.realized_return_pct
        record.realized_r_multiple = position.realized_r_multiple
        record.raw_broker_payload_json = self._dump(position.raw_broker_payload)
        record.error_message = position.error_message

    def _to_model(self, record: BrokerPositionRecord) -> BrokerPosition:
        return BrokerPosition(
            id=record.id,
            broker_order_execution_id=record.broker_order_execution_id,
            broker=record.broker,
            account_mode=record.account_mode,
            recommendation_plan_id=record.recommendation_plan_id,
            recommendation_plan_ticker=record.recommendation_plan_ticker,
            run_id=record.run_id,
            job_id=record.job_id,
            ticker=record.ticker,
            action=record.action,
            side=record.side,
            quantity=record.quantity,
            current_quantity=record.current_quantity,
            status=record.status,
            entry_order_id=record.entry_order_id,
            entry_avg_price=record.entry_avg_price,
            entry_filled_at=self._normalize_datetime(record.entry_filled_at),
            exit_order_id=record.exit_order_id,
            exit_reason=record.exit_reason,
            exit_avg_price=record.exit_avg_price,
            exit_filled_at=self._normalize_datetime(record.exit_filled_at),
            realized_pnl=record.realized_pnl,
            realized_return_pct=record.realized_return_pct,
            realized_r_multiple=record.realized_r_multiple,
            raw_broker_payload=self._load(record.raw_broker_payload_json, {}),
            error_message=record.error_message,
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=str)

    @staticmethod
    def _load(value: str | None, default: object) -> object:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
