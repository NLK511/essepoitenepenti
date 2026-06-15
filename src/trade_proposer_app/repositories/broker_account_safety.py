from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerCircuitBreaker, BrokerDrawdownState
from trade_proposer_app.persistence.models import (
    BrokerCircuitBreakerRecord,
    BrokerDrawdownStateRecord,
)


class BrokerAccountSafetyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_circuit_breaker(self, broker_account_id: str) -> BrokerCircuitBreaker:
        record = self.session.get(BrokerCircuitBreakerRecord, broker_account_id)
        if record is None:
            return BrokerCircuitBreaker(broker_account_id=broker_account_id)
        return self._breaker_to_model(record)

    def activate_circuit_breaker(
        self, broker_account_id: str, *, reason: str
    ) -> BrokerCircuitBreaker:
        now = datetime.now(timezone.utc)
        record = self.session.get(BrokerCircuitBreakerRecord, broker_account_id)
        if record is None:
            record = BrokerCircuitBreakerRecord(broker_account_id=broker_account_id)
            self.session.add(record)
        record.active = True
        record.reason = reason
        record.failure_count = int(record.failure_count or 0) + 1
        record.activated_at = now
        record.cleared_at = None
        record.clear_reason = ""
        self.session.commit()
        self.session.refresh(record)
        return self._breaker_to_model(record)

    def clear_circuit_breaker(
        self,
        broker_account_id: str,
        *,
        reason: str,
        require_trusted_drawdown: bool = False,
    ) -> BrokerCircuitBreaker:
        if not reason.strip():
            raise ValueError("circuit breaker clear reason is required")
        if require_trusted_drawdown:
            drawdown = self.get_drawdown_state(broker_account_id)
            if drawdown is None or not drawdown.trusted or drawdown.current_equity is None:
                raise ValueError("trusted drawdown state is required to clear circuit breaker")
        now = datetime.now(timezone.utc)
        record = self.session.get(BrokerCircuitBreakerRecord, broker_account_id)
        if record is None:
            record = BrokerCircuitBreakerRecord(broker_account_id=broker_account_id)
            self.session.add(record)
        record.active = False
        record.cleared_at = now
        record.clear_reason = reason.strip()
        self.session.commit()
        self.session.refresh(record)
        return self._breaker_to_model(record)

    def get_drawdown_state(self, broker_account_id: str) -> BrokerDrawdownState | None:
        record = self.session.get(BrokerDrawdownStateRecord, broker_account_id)
        return self._drawdown_to_model(record) if record is not None else None

    def record_drawdown_baseline(
        self,
        broker_account_id: str,
        *,
        current_equity: float,
        daily_high_water_equity: float,
        total_high_water_equity: float,
        broker_timezone: str,
        trusted: bool,
        baseline_source: str = "operator",
    ) -> BrokerDrawdownState:
        record = self.session.get(BrokerDrawdownStateRecord, broker_account_id)
        if record is None:
            record = BrokerDrawdownStateRecord(broker_account_id=broker_account_id)
            self.session.add(record)
        record.current_equity = float(current_equity)
        record.daily_high_water_equity = float(daily_high_water_equity)
        record.total_high_water_equity = float(total_high_water_equity)
        record.broker_timezone = broker_timezone or "UTC"
        record.daily_boundary = datetime.now(timezone.utc).date().isoformat()
        record.trusted = bool(trusted)
        record.baseline_source = baseline_source
        self.session.commit()
        self.session.refresh(record)
        return self._drawdown_to_model(record)

    @staticmethod
    def _breaker_to_model(record: BrokerCircuitBreakerRecord) -> BrokerCircuitBreaker:
        return BrokerCircuitBreaker(
            broker_account_id=record.broker_account_id,
            active=record.active,
            reason=record.reason,
            failure_count=record.failure_count,
            activated_at=record.activated_at,
            cleared_at=record.cleared_at,
            clear_reason=record.clear_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _drawdown_to_model(record: BrokerDrawdownStateRecord) -> BrokerDrawdownState:
        return BrokerDrawdownState(
            broker_account_id=record.broker_account_id,
            current_equity=record.current_equity,
            daily_high_water_equity=record.daily_high_water_equity,
            total_high_water_equity=record.total_high_water_equity,
            broker_timezone=record.broker_timezone,
            daily_boundary=record.daily_boundary,
            trusted=record.trusted,
            baseline_source=record.baseline_source,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
