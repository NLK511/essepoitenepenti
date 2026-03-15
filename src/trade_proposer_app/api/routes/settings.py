from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppSetting, ProviderCredential
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.optimizations import WeightOptimizationError, WeightOptimizationService

router = APIRouter(prefix="/settings", tags=["settings"])


def create_optimization_service(repository: SettingsRepository) -> WeightOptimizationService:
    return WeightOptimizationService(
        minimum_resolved_trades=repository.get_optimization_minimum_resolved_trades(),
    )


@router.get("")
async def list_settings(session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SettingsRepository(session)
    return {
        "settings": repository.list_settings(),
        "providers": repository.list_provider_credentials(),
        "optimization": create_optimization_service(repository).describe_state(),
    }


@router.post("/app")
async def set_app_setting(
    key: str = Form(...),
    value: str = Form(...),
    session: Session = Depends(get_db_session),
) -> AppSetting:
    return SettingsRepository(session).set_setting(key=key.strip(), value=value.strip())


@router.post("/summary")
async def set_summary_settings(
    backend: str = Form(...),
    model: str = Form(default=""),
    timeout_seconds: str = Form(default="60"),
    max_tokens: str = Form(default="220"),
    pi_command: str = Form(default="pi"),
    pi_agent_dir: str = Form(default=""),
    pi_cli_args: str = Form(default=""),
    prompt: str = Form(default=""),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    repository.set_settings(
        {
            "summary_backend": backend.strip() or settings_map["summary_backend"],
            "summary_model": model.strip(),
            "summary_timeout_seconds": timeout_seconds.strip() or settings_map["summary_timeout_seconds"],
            "summary_max_tokens": max_tokens.strip() or settings_map["summary_max_tokens"],
            "summary_pi_command": pi_command.strip() or settings_map["summary_pi_command"],
            "summary_pi_agent_dir": pi_agent_dir.strip(),
            "summary_pi_cli_args": pi_cli_args.strip(),
            "summary_prompt": prompt.strip() or settings_map["summary_prompt"],
        }
    )
    return {"settings": repository.get_summary_settings()}


@router.post("/optimization")
async def set_optimization_settings(
    minimum_resolved_trades: str = Form(...),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    normalized = minimum_resolved_trades.strip()
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="minimum_resolved_trades must be an integer") from exc
    if parsed < 1:
        raise HTTPException(status_code=400, detail="minimum_resolved_trades must be at least 1")
    repository = SettingsRepository(session)
    repository.set_setting("optimization_minimum_resolved_trades", str(parsed))
    return {"optimization": create_optimization_service(repository).describe_state()}


@router.post("/optimization/rollback")
async def rollback_optimization_weights(
    backup_path: str = Form(default=""),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    service = create_optimization_service(repository)
    try:
        normalized_backup_path = backup_path.strip()
        rollback = (
            service.restore_backup(normalized_backup_path)
            if normalized_backup_path
            else service.rollback_latest_backup()
        )
    except WeightOptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "rollback": rollback,
        "optimization": service.describe_state(),
    }


@router.post("/providers")
async def set_provider_credential(
    provider: str = Form(...),
    api_key: str = Form(default=""),
    api_secret: str = Form(default=""),
    session: Session = Depends(get_db_session),
) -> ProviderCredential:
    return SettingsRepository(session).upsert_provider_credential(
        provider=provider.strip(),
        api_key=api_key.strip(),
        api_secret=api_secret.strip(),
    )
