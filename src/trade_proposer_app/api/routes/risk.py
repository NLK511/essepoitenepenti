from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerRiskAssessment
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.risk_management import BrokerRiskManager

router = APIRouter(prefix="/risk", tags=["risk"])


def _manager(session: Session) -> BrokerRiskManager:
    return BrokerRiskManager(SettingsRepository(session), BrokerPositionRepository(session))


@router.get("", response_model=BrokerRiskAssessment)
async def get_risk_assessment(session: Session = Depends(get_db_session)) -> BrokerRiskAssessment:
    return _manager(session).assess()


@router.post("/halt", response_model=BrokerRiskAssessment)
async def halt_trading(reason: str = Form(default="manual halt"), session: Session = Depends(get_db_session)) -> BrokerRiskAssessment:
    return _manager(session).halt(reason.strip() or "manual halt")


@router.post("/resume", response_model=BrokerRiskAssessment)
async def resume_trading(session: Session = Depends(get_db_session)) -> BrokerRiskAssessment:
    return _manager(session).resume()
