from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppSetting, ProviderCredential
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.settings import SettingsRepository

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("")
async def list_settings(session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SettingsRepository(session)
    signal_gating_tuning = repository.get_signal_gating_tuning_config()
    evaluation_realism = repository.get_evaluation_realism_config()
    return {
        "settings": repository.list_settings(),
        "providers": repository.list_provider_credentials(),
        "signal_gating_tuning": signal_gating_tuning,
        "evaluation_realism": evaluation_realism,
        "plan_generation_tuning": {
            "settings": repository.get_plan_generation_tuning_settings(),
            "active_config": repository.get_plan_generation_active_config(PlanGenerationTuningRepository(session)),
        },
    }


@router.post("/evaluation-realism")
async def set_evaluation_realism_settings(
    stop_buffer_pct: str = Form(default="0.05"),
    take_profit_buffer_pct: str = Form(default="0.05"),
    friction_pct: str = Form(default="0.1"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    try:
        config = repository.set_evaluation_realism_config(
            stop_buffer_pct=float(stop_buffer_pct.strip() or 0.05),
            take_profit_buffer_pct=float(take_profit_buffer_pct.strip() or 0.05),
            friction_pct=float(friction_pct.strip() or 0.1),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid evaluation realism settings: {exc}") from exc
    return {"evaluation_realism": config}


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


def _set_signal_gating_tuning_settings(
    repository: SettingsRepository,
    *,
    threshold_offset: str = "0",
    confidence_adjustment: str = "0",
    near_miss_gap_cutoff: str = "0",
    shortlist_aggressiveness: str = "0",
    degraded_penalty: str = "0",
) -> dict[str, object]:
    try:
        config = repository.set_signal_gating_tuning_config(
            threshold_offset=float(threshold_offset.strip() or 0),
            confidence_adjustment=float(confidence_adjustment.strip() or 0),
            near_miss_gap_cutoff=float(near_miss_gap_cutoff.strip() or 0),
            shortlist_aggressiveness=float(shortlist_aggressiveness.strip() or 0),
            degraded_penalty=float(degraded_penalty.strip() or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid signal gating tuning settings: {exc}") from exc
    return {"signal_gating_tuning": config}


@router.post("/signal-gating-tuning")
async def set_signal_gating_tuning_settings(
    threshold_offset: str = Form(default="0"),
    confidence_adjustment: str = Form(default="0"),
    near_miss_gap_cutoff: str = Form(default="0"),
    shortlist_aggressiveness: str = Form(default="0"),
    degraded_penalty: str = Form(default="0"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return _set_signal_gating_tuning_settings(
        SettingsRepository(session),
        threshold_offset=threshold_offset,
        confidence_adjustment=confidence_adjustment,
        near_miss_gap_cutoff=near_miss_gap_cutoff,
        shortlist_aggressiveness=shortlist_aggressiveness,
        degraded_penalty=degraded_penalty,
    )


@router.post("/plan-generation-tuning")
async def set_plan_generation_tuning_settings(
    auto_enabled: str = Form(default="false"),
    auto_promote_enabled: str = Form(default="false"),
    min_actionable_resolved: str = Form(default="20"),
    min_validation_resolved: str = Form(default="8"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SettingsRepository(session)
    try:
        config = repository.set_plan_generation_tuning_settings(
            auto_enabled=(auto_enabled.strip().lower() in {"1", "true", "yes", "on"}),
            auto_promote_enabled=(auto_promote_enabled.strip().lower() in {"1", "true", "yes", "on"}),
            min_actionable_resolved=int(min_actionable_resolved.strip() or 20),
            min_validation_resolved=int(min_validation_resolved.strip() or 8),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid plan generation tuning settings: {exc}") from exc
    return {"plan_generation_tuning": config}


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
