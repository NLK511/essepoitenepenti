from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import BrokerSteeringDecisionRecord
from trade_proposer_app.utils.json_payloads import loads_json_list, loads_json_object


class BrokerSteeringDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        recommendation_plan_id: int,
        ticker: str,
        decision,
        broker_order_id: int | None = None,
        broker_position_id: int | None = None,
        execution_status: str = "dry_run",
        executed_at: datetime | None = None,
        error_message: str = "",
    ) -> dict[str, object]:
        record = BrokerSteeringDecisionRecord(
            recommendation_plan_id=recommendation_plan_id,
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            ticker=ticker,
            decision=str(getattr(decision, "decision", decision)),
            execute_allowed=bool(getattr(decision, "execute_allowed", False)),
            executed_at=self._normalize_datetime(executed_at),
            execution_status=execution_status,
            reason_codes_json=self._dump(getattr(decision, "reason_codes", [])),
            proposed_stop_loss=getattr(decision, "proposed_stop_loss", None),
            proposed_take_profit=getattr(decision, "proposed_take_profit", None),
            current_price=getattr(decision, "current_price", None),
            current_stop_loss=getattr(decision, "current_stop_loss", None),
            current_take_profit=getattr(decision, "current_take_profit", None),
            risk_delta_json=self._dump(
                {
                    "risk_delta_usd": getattr(decision, "risk_delta_usd", None),
                    "risk_delta_percent": getattr(decision, "risk_delta_percent", None),
                }
            ),
            diagnostics_json=self._dump(getattr(decision, "diagnostics", {})),
            error_message=error_message,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dict(record)

    def list_all(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self.session.scalars(
            select(BrokerSteeringDecisionRecord)
            .order_by(BrokerSteeringDecisionRecord.created_at.desc(), BrokerSteeringDecisionRecord.id.desc())
            .limit(max(1, limit))
        ).all()
        return [self._to_dict(row) for row in rows]

    def count(
        self,
        *,
        execution_status: str | None = None,
        decisions: list[str] | None = None,
    ) -> int:
        query = select(func.count()).select_from(BrokerSteeringDecisionRecord)
        if execution_status is not None:
            query = query.where(BrokerSteeringDecisionRecord.execution_status == execution_status)
        if decisions:
            query = query.where(BrokerSteeringDecisionRecord.decision.in_(decisions))
        return int(self.session.scalar(query) or 0)

    def update_execution_result(
        self,
        decision_id: int,
        *,
        execution_status: str,
        executed_at: datetime | None = None,
        error_message: str = "",
    ) -> dict[str, object]:
        record = self.session.get(BrokerSteeringDecisionRecord, decision_id)
        if record is None:
            raise ValueError(f"Broker steering decision {decision_id} not found")
        record.execution_status = execution_status
        record.executed_at = self._normalize_datetime(executed_at) or record.executed_at
        record.error_message = error_message
        self.session.commit()
        self.session.refresh(record)
        return self._to_dict(record)

    def list_by_plan_id(self, recommendation_plan_id: int, limit: int = 100) -> list[dict[str, object]]:
        rows = self.session.scalars(
            select(BrokerSteeringDecisionRecord)
            .where(BrokerSteeringDecisionRecord.recommendation_plan_id == recommendation_plan_id)
            .order_by(BrokerSteeringDecisionRecord.created_at.desc(), BrokerSteeringDecisionRecord.id.desc())
            .limit(max(1, limit))
        ).all()
        return [self._to_dict(row) for row in rows]

    @classmethod
    def _to_dict(cls, record: BrokerSteeringDecisionRecord) -> dict[str, object]:
        return {
            "id": record.id,
            "recommendation_plan_id": record.recommendation_plan_id,
            "broker_order_id": record.broker_order_id,
            "broker_position_id": record.broker_position_id,
            "ticker": record.ticker,
            "decision": record.decision,
            "execute_allowed": record.execute_allowed,
            "executed_at": cls._normalize_datetime(record.executed_at).isoformat() if cls._normalize_datetime(record.executed_at) else None,
            "execution_status": record.execution_status,
            "reason_codes": loads_json_list(record.reason_codes_json),
            "proposed_stop_loss": record.proposed_stop_loss,
            "proposed_take_profit": record.proposed_take_profit,
            "current_price": record.current_price,
            "current_stop_loss": record.current_stop_loss,
            "current_take_profit": record.current_take_profit,
            "risk_delta": loads_json_object(record.risk_delta_json),
            "diagnostics": loads_json_object(record.diagnostics_json),
            "error_message": record.error_message,
            "created_at": cls._normalize_datetime(record.created_at).isoformat() if cls._normalize_datetime(record.created_at) else None,
            "updated_at": cls._normalize_datetime(record.updated_at).isoformat() if cls._normalize_datetime(record.updated_at) else None,
        }

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=str)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
