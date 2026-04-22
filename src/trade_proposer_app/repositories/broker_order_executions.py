from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerOrderExecution
from trade_proposer_app.persistence.models import BrokerOrderExecutionRecord


class BrokerOrderExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, order: BrokerOrderExecution) -> BrokerOrderExecution:
        record = BrokerOrderExecutionRecord(
            broker=order.broker,
            account_mode=order.account_mode,
            recommendation_plan_id=order.recommendation_plan_id,
            recommendation_plan_ticker=order.recommendation_plan_ticker,
            run_id=order.run_id,
            job_id=order.job_id,
            ticker=order.ticker,
            action=order.action,
            side=order.side,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            quantity=order.quantity,
            notional_amount=order.notional_amount,
            entry_price=order.entry_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            status=order.status,
            broker_order_id=order.broker_order_id,
            client_order_id=order.client_order_id,
            submitted_at=self._normalize_datetime(order.submitted_at),
            filled_at=self._normalize_datetime(order.filled_at),
            canceled_at=self._normalize_datetime(order.canceled_at),
            request_payload_json=self._dump(order.request_payload),
            response_payload_json=self._dump(order.response_payload),
            error_message=order.error_message,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def upsert(self, order: BrokerOrderExecution) -> BrokerOrderExecution:
        existing = self.get_by_client_order_id(order.broker, order.client_order_id)
        if existing is not None:
            return existing
        return self.create(order)

    def get(self, execution_id: int) -> BrokerOrderExecution:
        record = self.session.get(BrokerOrderExecutionRecord, execution_id)
        if record is None:
            raise ValueError(f"Broker order execution {execution_id} not found")
        return self._to_model(record)

    def get_by_client_order_id(self, broker: str, client_order_id: str) -> BrokerOrderExecution | None:
        record = self.session.scalar(
            select(BrokerOrderExecutionRecord).where(
                BrokerOrderExecutionRecord.broker == broker,
                BrokerOrderExecutionRecord.client_order_id == client_order_id,
            )
        )
        return self._to_model(record) if record is not None else None

    def list_all(self, limit: int = 200) -> list[BrokerOrderExecution]:
        rows = self.session.scalars(
            select(BrokerOrderExecutionRecord).order_by(BrokerOrderExecutionRecord.created_at.desc()).limit(max(1, limit))
        ).all()
        return [self._to_model(row) for row in rows]

    def list_by_run(self, run_id: int, limit: int = 200) -> list[BrokerOrderExecution]:
        rows = self.session.scalars(
            select(BrokerOrderExecutionRecord)
            .where(BrokerOrderExecutionRecord.run_id == run_id)
            .order_by(BrokerOrderExecutionRecord.created_at.asc())
            .limit(max(1, limit))
        ).all()
        return [self._to_model(row) for row in rows]

    def _to_model(self, record: BrokerOrderExecutionRecord) -> BrokerOrderExecution:
        return BrokerOrderExecution(
            id=record.id,
            broker=record.broker,
            account_mode=record.account_mode,
            recommendation_plan_id=record.recommendation_plan_id,
            recommendation_plan_ticker=record.recommendation_plan_ticker,
            run_id=record.run_id,
            job_id=record.job_id,
            ticker=record.ticker,
            action=record.action,
            side=record.side,
            order_type=record.order_type,
            time_in_force=record.time_in_force,
            quantity=record.quantity,
            notional_amount=record.notional_amount,
            entry_price=record.entry_price,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            status=record.status,
            broker_order_id=record.broker_order_id,
            client_order_id=record.client_order_id,
            submitted_at=self._normalize_datetime(record.submitted_at),
            filled_at=self._normalize_datetime(record.filled_at),
            canceled_at=self._normalize_datetime(record.canceled_at),
            request_payload=self._load(record.request_payload_json, {}),
            response_payload=self._load(record.response_payload_json, {}),
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
