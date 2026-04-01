from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppSetting, ProviderCredential
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.optimizations import WeightOptimizationError, WeightOptimizationService

router = APIRouter(prefix="/settings", tags=["settings"])


def create_optimization_service(session: Session, repository: SettingsRepository) -> WeightOptimizationService:
    return WeightOptimizationService(
        session=session,
        minimum_resolved_trades=repository.get_optimization_minimum_resolved_trades(),
    )


@router.get("")
async def list_settings(session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SettingsRepository(session)
    return {
        "settings": repository.list_settings(),
        "providers": repository.list_provider_credentials(),
        "optimization": create_optimization_service(session, repository).describe_state(),
        "autotune": repository.get_autotune_config(),
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


@router.post("/news")
async def set_news_settings(
    macro_article_limit: str = Form(default="12"),
    industry_article_limit: str = Form(default="12"),
    ticker_article_limit: str = Form(default="12"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    repository.set_settings(
        {
            "news_macro_article_limit": macro_article_limit.strip() or settings_map.get("news_macro_article_limit", "12"),
            "news_industry_article_limit": industry_article_limit.strip() or settings_map.get("news_industry_article_limit", "12"),
            "news_ticker_article_limit": ticker_article_limit.strip() or settings_map.get("news_ticker_article_limit", "12"),
        }
    )
    return {"status": "success"}


@router.post("/social")
async def set_social_settings(
    sentiment_enabled: str = Form(default="false"),
    nitter_enabled: str = Form(default="false"),
    nitter_base_url: str = Form(default="http://127.0.0.1:8080"),
    nitter_timeout_seconds: str = Form(default="6"),
    nitter_max_items_per_query: str = Form(default="12"),
    nitter_query_window_hours: str = Form(default="12"),
    nitter_include_replies: str = Form(default="false"),
    nitter_enable_ticker: str = Form(default="false"),
    weight_news: str = Form(default="1.0"),
    weight_social: str = Form(default="0.6"),
    weight_macro: str = Form(default="0.2"),
    weight_industry: str = Form(default="0.3"),
    weight_ticker: str = Form(default="0.5"),
    enable_author_weighting: str = Form(default="true"),
    enable_engagement_weighting: str = Form(default="true"),
    enable_duplicate_suppression: str = Form(default="true"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    repository.set_settings(
        {
            "social_sentiment_enabled": sentiment_enabled.strip().lower(),
            "social_nitter_enabled": nitter_enabled.strip().lower(),
            "social_nitter_base_url": nitter_base_url.strip() or "http://127.0.0.1:8080",
            "social_nitter_timeout_seconds": nitter_timeout_seconds.strip() or "6",
            "social_nitter_max_items_per_query": nitter_max_items_per_query.strip() or "12",
            "social_nitter_query_window_hours": nitter_query_window_hours.strip() or "12",
            "social_nitter_include_replies": nitter_include_replies.strip().lower(),
            "social_nitter_enable_ticker": nitter_enable_ticker.strip().lower(),
            "social_weight_news": weight_news.strip() or "1.0",
            "social_weight_social": weight_social.strip() or "0.6",
            "social_weight_macro": weight_macro.strip() or "0.2",
            "social_weight_industry": weight_industry.strip() or "0.3",
            "social_weight_ticker": weight_ticker.strip() or "0.5",
            "social_enable_author_weighting": enable_author_weighting.strip().lower(),
            "social_enable_engagement_weighting": enable_engagement_weighting.strip().lower(),
            "social_enable_duplicate_suppression": enable_duplicate_suppression.strip().lower(),
        }
    )
    return {"settings": repository.get_social_settings()}


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
    return {"optimization": create_optimization_service(session, repository).describe_state()}


@router.post("/autotune")
async def set_autotune_settings(
    threshold_offset: str = Form(default="0"),
    confidence_adjustment: str = Form(default="0"),
    near_miss_gap_cutoff: str = Form(default="0"),
    shortlist_aggressiveness: str = Form(default="0"),
    degraded_penalty: str = Form(default="0"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    try:
        config = repository.set_autotune_config(
            threshold_offset=float(threshold_offset.strip() or 0),
            confidence_adjustment=float(confidence_adjustment.strip() or 0),
            near_miss_gap_cutoff=float(near_miss_gap_cutoff.strip() or 0),
            shortlist_aggressiveness=float(shortlist_aggressiveness.strip() or 0),
            degraded_penalty=float(degraded_penalty.strip() or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid autotune settings: {exc}") from exc
    return {"autotune": config}


@router.post("/optimization/rollback")
async def rollback_optimization_weights(
    backup_path: str = Form(default=""),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    service = create_optimization_service(session, repository)
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
