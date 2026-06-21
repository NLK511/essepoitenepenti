from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AccountRiskState, RiskHaltEvent
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.risk_management import BrokerRiskManager

router = APIRouter(prefix="/risk", tags=["risk"])


class GlobalBrokerRiskCapsRequest(BaseModel):
    global_max_live_open_notional_usd: float | None = None
    global_max_live_daily_drawdown_usd: float | None = None
    global_max_live_daily_drawdown_pct: float | None = None
    global_max_live_order_count_per_day: int | None = None


def _manager(session: Session) -> BrokerRiskManager:
    return BrokerRiskManager(
        SettingsRepository(session),
        BrokerPositionRepository(session),
        RiskHaltEventRepository(session),
    )


@router.get("", response_model=AccountRiskState)
async def get_risk_assessment(session: Session = Depends(get_db_session)) -> AccountRiskState:
    return _manager(session).assess()


@router.get("/halt-events", response_model=list[RiskHaltEvent])
async def list_halt_events(
    limit: int = 50,
    session: Session = Depends(get_db_session),
) -> list[RiskHaltEvent]:
    return RiskHaltEventRepository(session).list_latest(limit=limit)


@router.post("/halt", response_model=AccountRiskState)
async def halt_trading(
    reason: str = Form(default="manual halt"), session: Session = Depends(get_db_session)
) -> AccountRiskState:
    return _manager(session).halt(reason.strip() or "manual halt")


@router.post("/resume", response_model=AccountRiskState)
async def resume_trading(session: Session = Depends(get_db_session)) -> AccountRiskState:
    return _manager(session).resume()


@router.get("/broker-caps")
async def get_global_broker_risk_caps(
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    settings = SettingsRepository(session)
    return {
        "caps": settings.get_global_broker_risk_caps(),
        "live_summary": _global_live_summary(session),
    }


@router.patch("/broker-caps")
async def update_global_broker_risk_caps(
    request: GlobalBrokerRiskCapsRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    settings = SettingsRepository(session)
    caps = settings.set_global_broker_risk_caps(
        max_live_open_notional_usd=request.global_max_live_open_notional_usd,
        max_live_daily_drawdown_usd=request.global_max_live_daily_drawdown_usd,
        max_live_daily_drawdown_pct=request.global_max_live_daily_drawdown_pct,
        max_live_order_count_per_day=request.global_max_live_order_count_per_day,
    )
    return {"caps": caps, "live_summary": _global_live_summary(session)}


def _global_live_summary(session: Session) -> dict[str, object]:
    accounts = BrokerAccountRepository(session).list_all()
    enabled_live_accounts = [
        account for account in accounts if account.enabled and account.account_mode == "live"
    ]
    active_live_orders = [
        order
        for order in BrokerOrderExecutionRepository(session).list_all(limit=5000)
        if order.account_mode == "live"
        and order.status
        not in {
            "skipped",
            "failed",
            "rejected",
            "canceled",
            "cancelled",
            "closed",
            "win",
            "loss",
            "needs_review",
        }
    ]
    today = datetime.now(UTC).date()
    return {
        "enabled_live_account_count": len(enabled_live_accounts),
        "enabled_live_broker_accounts": [
            account.broker_account_id for account in enabled_live_accounts
        ],
        "active_live_open_notional_usd": round(
            sum(float(order.notional_amount or 0.0) for order in active_live_orders), 4
        ),
        "live_order_count_today": sum(
            1 for order in active_live_orders if order.created_at.astimezone(UTC).date() == today
        ),
    }
