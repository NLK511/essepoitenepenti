from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.services.brokers import redacted_payload

router = APIRouter(prefix="/broker-accounts", tags=["broker-accounts"])


class CircuitBreakerClearRequest(BaseModel):
    reason: str = ""
    require_trusted_drawdown: bool = False


class DemoValidationArtifactRequest(BaseModel):
    artifact_id: str = ""
    notes: str = ""


class BrokerAccountControlsRequest(BaseModel):
    account_label: str | None = None
    enabled: bool | None = None
    autonomous_execution_enabled: bool | None = None
    manual_actions_enabled: bool | None = None
    halt_enabled: bool | None = None
    halt_reason: str | None = None
    symbol_allowlist: list[str] | None = None
    symbol_denylist: list[str] | None = None
    notional_cap_usd: float | None = None
    max_open_positions: int | None = None
    max_open_notional_usd: float | None = None
    max_position_notional_usd: float | None = None
    max_same_ticker_open_positions: int | None = None
    risk_settings: dict[str, object] | None = None


@router.get("")
async def list_broker_accounts(session: Session = Depends(get_db_session)) -> dict[str, object]:
    accounts = BrokerAccountRepository(session).list_accounts_redacted()
    safety = BrokerAccountSafetyRepository(session)
    return {"accounts": [_account_payload(account, safety=safety) for account in accounts]}


@router.get("/{broker_account_id}")
async def get_broker_account(
    broker_account_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    accounts = BrokerAccountRepository(session)
    try:
        account = accounts.get(broker_account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_payload(account, safety=BrokerAccountSafetyRepository(session))


@router.patch("/{broker_account_id}")
async def update_broker_account_controls(
    broker_account_id: str,
    request: BrokerAccountControlsRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    accounts = BrokerAccountRepository(session)
    try:
        account = accounts.update_controls(
            broker_account_id,
            request.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_payload(account, safety=BrokerAccountSafetyRepository(session))


@router.post("/{broker_account_id}/demo-validation-artifact")
async def record_demo_validation_artifact(
    broker_account_id: str,
    request: DemoValidationArtifactRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    artifact_id = request.artifact_id.strip()
    if not artifact_id:
        raise HTTPException(status_code=400, detail="demo validation artifact id is required")
    accounts = BrokerAccountRepository(session)
    try:
        account = accounts.update_controls(
            broker_account_id,
            {
                "risk_settings": {
                    "demo_validation_artifact_id": artifact_id,
                    "demo_validation_notes": request.notes.strip(),
                    "demo_validation_recorded_at": datetime.now(UTC).isoformat(),
                }
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_payload(account, safety=BrokerAccountSafetyRepository(session))


@router.get("/{broker_account_id}/safety")
async def get_broker_account_safety(
    broker_account_id: str, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    try:
        BrokerAccountRepository(session).get(broker_account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    safety = BrokerAccountSafetyRepository(session)
    drawdown = safety.get_drawdown_state(broker_account_id)
    return {
        "broker_account_id": broker_account_id,
        "circuit_breaker": safety.get_circuit_breaker(broker_account_id).model_dump(mode="json"),
        "drawdown": drawdown.model_dump(mode="json") if drawdown is not None else None,
    }


@router.post("/{broker_account_id}/circuit-breaker/clear")
async def clear_broker_account_circuit_breaker(
    broker_account_id: str,
    request: CircuitBreakerClearRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        BrokerAccountRepository(session).get(broker_account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        breaker = BrokerAccountSafetyRepository(session).clear_circuit_breaker(
            broker_account_id,
            reason=request.reason,
            require_trusted_drawdown=request.require_trusted_drawdown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return breaker.model_dump(mode="json")


def _account_payload(
    account: object, *, safety: BrokerAccountSafetyRepository
) -> dict[str, object]:
    values = account.model_dump(mode="json")
    values["credential_reference"] = (
        values.get("credential_reference") or f"broker_account:{values['broker_account_id']}"
    )
    values["has_credentials"] = bool(
        BrokerAccountRepository(safety.session).get_credentials(str(values["broker_account_id"]))
    )
    values["mode_badge"] = str(values.get("account_mode") or "").upper()
    values["validation_evidence"] = redacted_payload(values.get("validation_evidence") or {})
    values["risk_settings"] = redacted_payload(values.get("risk_settings") or {})
    breaker = safety.get_circuit_breaker(str(values["broker_account_id"]))
    drawdown = safety.get_drawdown_state(str(values["broker_account_id"]))
    values["circuit_breaker"] = breaker.model_dump(mode="json")
    values["drawdown"] = drawdown.model_dump(mode="json") if drawdown is not None else None
    return redacted_payload(values)  # type: ignore[return-value]
