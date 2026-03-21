from fastapi import APIRouter, Form, HTTPException, status
from pydantic import BaseModel

from trade_proposer_app.config import settings

router = APIRouter()


class LoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
async def login(username: str = Form(...), password: str = Form(...)) -> LoginResponse:
    expected_username = (settings.single_user_auth_username or "").strip()
    expected_password = settings.single_user_auth_password or ""
    if not expected_username or not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    if username.strip() != expected_username or password != expected_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = (settings.single_user_auth_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication token is not configured",
        )
    return LoginResponse(token=token)
