from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppSetting
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.preflight import AppPreflightService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.settings_mutations import SettingsMutationService

router = APIRouter(prefix="/settings", tags=["settings"])


def _settings_payload(session: Session, repository: SettingsRepository | None = None) -> dict[str, object]:
    repository = repository or SettingsRepository(session)
    domain_settings = SettingsDomainService(repository=repository)
    strategy_settings = domain_settings.strategy_settings()
    execution_settings = domain_settings.execution_settings()
    risk_settings = domain_settings.risk_settings()
    return {
        "settings": repository.list_settings(),
        "providers": [
            {"provider": item.provider, "api_key": item.api_key}
            for item in repository.list_provider_credentials_redacted()
        ],
        "signal_gating_tuning": strategy_settings.signal_gating,
        "evaluation_realism": execution_settings.evaluation_realism,
        "order_execution": execution_settings.broker_order_execution,
        "risk_management": risk_settings.risk_management,
        "plan_generation_tuning": {
            "settings": strategy_settings.plan_generation_tuning,
            "active_config": repository.get_plan_generation_active_config(PlanGenerationTuningRepository(session)),
        },
    }


@router.get("")
async def list_settings(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return _settings_payload(session)


@router.get("/workbench")
async def get_settings_workbench(session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SettingsRepository(session)
    settings_payload = _settings_payload(session, repository)
    preflight = AppPreflightService(SettingsDomainService(repository=repository).operator_settings().social).run()
    return {
        **settings_payload,
        "preflight": preflight,
        "broker_orders": BrokerOrderExecutionRepository(session).list_all(limit=12),
    }


@router.post("/evaluation-realism")
async def set_evaluation_realism_settings(
    stop_buffer_pct: str = Form(default="0.05"),
    take_profit_buffer_pct: str = Form(default="0.05"),
    friction_pct: str = Form(default="0.1"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        config = SettingsMutationService(session).set_evaluation_realism_settings(
            stop_buffer_pct=stop_buffer_pct,
            take_profit_buffer_pct=take_profit_buffer_pct,
            friction_pct=friction_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"evaluation_realism": config}


@router.post("/app")
async def set_app_setting(
    key: str = Form(...),
    value: str = Form(...),
    session: Session = Depends(get_db_session),
) -> AppSetting:
    return SettingsMutationService(session).set_app_setting(key=key, value=value)


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
    return SettingsMutationService(session).set_summary_settings(
        backend=backend,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        pi_command=pi_command,
        pi_agent_dir=pi_agent_dir,
        pi_cli_args=pi_cli_args,
        prompt=prompt,
    )


@router.post("/news")
async def set_news_settings(
    macro_article_limit: str = Form(default="12"),
    industry_article_limit: str = Form(default="12"),
    ticker_article_limit: str = Form(default="12"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return SettingsMutationService(session).set_news_settings(
        macro_article_limit=macro_article_limit,
        industry_article_limit=industry_article_limit,
        ticker_article_limit=ticker_article_limit,
    )


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
    return SettingsMutationService(session).set_social_settings(
        sentiment_enabled=sentiment_enabled,
        nitter_enabled=nitter_enabled,
        nitter_base_url=nitter_base_url,
        nitter_timeout_seconds=nitter_timeout_seconds,
        nitter_max_items_per_query=nitter_max_items_per_query,
        nitter_query_window_hours=nitter_query_window_hours,
        nitter_include_replies=nitter_include_replies,
        nitter_enable_ticker=nitter_enable_ticker,
        weight_news=weight_news,
        weight_social=weight_social,
        weight_macro=weight_macro,
        weight_industry=weight_industry,
        weight_ticker=weight_ticker,
        enable_author_weighting=enable_author_weighting,
        enable_engagement_weighting=enable_engagement_weighting,
        enable_duplicate_suppression=enable_duplicate_suppression,
    )


@router.post("/signal-gating-tuning")
async def set_signal_gating_tuning_settings(
    threshold_offset: str = Form(default="0"),
    confidence_adjustment: str = Form(default="0"),
    near_miss_gap_cutoff: str = Form(default="0"),
    shortlist_aggressiveness: str = Form(default="0"),
    degraded_penalty: str = Form(default="0"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        config = SettingsMutationService(session).set_signal_gating_tuning_settings(
            threshold_offset=threshold_offset,
            confidence_adjustment=confidence_adjustment,
            near_miss_gap_cutoff=near_miss_gap_cutoff,
            shortlist_aggressiveness=shortlist_aggressiveness,
            degraded_penalty=degraded_penalty,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return config


@router.post("/plan-generation-tuning")
async def set_plan_generation_tuning_settings(
    auto_enabled: str = Form(default="false"),
    auto_promote_enabled: str = Form(default="false"),
    min_actionable_resolved: str = Form(default="20"),
    min_validation_resolved: str = Form(default="8"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        config = SettingsMutationService(session).set_plan_generation_tuning_settings(
            auto_enabled=auto_enabled,
            auto_promote_enabled=auto_promote_enabled,
            min_actionable_resolved=min_actionable_resolved,
            min_validation_resolved=min_validation_resolved,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return config


@router.post("/risk-management")
async def set_risk_management_settings(
    enabled: str = Form(default="true"),
    max_daily_realized_loss_usd: str = Form(default="50"),
    max_open_positions: str = Form(default="3"),
    max_open_notional_usd: str = Form(default="3000"),
    max_position_notional_usd: str = Form(default="1000"),
    max_same_ticker_open_positions: str = Form(default="1"),
    max_consecutive_losses: str = Form(default="3"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        config = SettingsMutationService(session).set_risk_management_settings(
            enabled=enabled,
            max_daily_realized_loss_usd=max_daily_realized_loss_usd,
            max_open_positions=max_open_positions,
            max_open_notional_usd=max_open_notional_usd,
            max_position_notional_usd=max_position_notional_usd,
            max_same_ticker_open_positions=max_same_ticker_open_positions,
            max_consecutive_losses=max_consecutive_losses,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return config


@router.post("/order-execution")
async def set_order_execution_settings(
    enabled: str = Form(default="false"),
    broker: str = Form(default="alpaca"),
    account_mode: str = Form(default="paper"),
    notional_per_plan: str = Form(default="1000"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        config = SettingsMutationService(session).set_order_execution_settings(
            enabled=enabled,
            broker=broker,
            account_mode=account_mode,
            notional_per_plan=notional_per_plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return config


@router.post("/providers")
async def set_provider_credential(
    provider: str = Form(...),
    api_key: str = Form(default=""),
    api_secret: str = Form(default=""),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    try:
        credential = SettingsMutationService(session).set_provider_credential(provider=provider, api_key=api_key, api_secret=api_secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return credential
