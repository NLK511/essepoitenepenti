from datetime import datetime, timezone

from pydantic import BaseModel, Field

from trade_proposer_app.domain.enums import JobType, RecommendationDirection, RecommendationState, RunStatus, StrategyHorizon


class NewsArticle(BaseModel):
    title: str
    summary: str | None = None
    publisher: str | None = None
    link: str | None = None
    published_at: datetime | None = None


class NewsBundle(BaseModel):
    ticker: str
    articles: list[NewsArticle] = Field(default_factory=list)
    feeds_used: list[str] = Field(default_factory=list)
    feed_errors: list[str] = Field(default_factory=list)


class SignalEngagement(BaseModel):
    likes: int = 0
    replies: int = 0
    retweets: int = 0
    quotes: int = 0


class SignalItem(BaseModel):
    source_type: str
    provider: str
    item_id: str | None = None
    title: str = ""
    body: str = ""
    author: str | None = None
    author_handle: str | None = None
    publisher: str | None = None
    link: str | None = None
    published_at: datetime | None = None
    engagement: SignalEngagement = Field(default_factory=SignalEngagement)
    raw_metadata: dict[str, object] = Field(default_factory=dict)
    matched_entities: dict[str, object] = Field(default_factory=dict)
    scope_tags: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    credibility_score: float = 0.0
    dedupe_key: str | None = None


class SignalBundle(BaseModel):
    ticker: str
    items: list[SignalItem] = Field(default_factory=list)
    feeds_used: list[str] = Field(default_factory=list)
    feed_errors: list[str] = Field(default_factory=list)
    coverage: dict[str, object] = Field(default_factory=dict)
    query_diagnostics: dict[str, object] = Field(default_factory=dict)


class SentimentAnalysis(BaseModel):
    score: float
    label: str
    contexts: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class SummaryAnalysis(BaseModel):
    summary: str = ""
    method: str = "failed"
    llm_error: str | None = None
    problems: list[str] = Field(default_factory=list)


class TechnicalSnapshot(BaseModel):
    price: float
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    rsi: float | None = None
    atr: float | None = None


class RunDiagnostics(BaseModel):
    warnings: list[str] = Field(default_factory=list)
    provider_errors: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    news_feed_errors: list[str] = Field(default_factory=list)
    summary_error: str | None = None
    llm_error: str | None = None
    raw_output: str | None = None
    analysis_json: str | None = None
    feature_vector_json: str | None = None
    normalized_feature_vector_json: str | None = None
    aggregations_json: str | None = None
    confidence_weights_json: str | None = None
    summary_method: str | None = None

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


class Recommendation(BaseModel):
    id: int | None = None
    run_id: int | None = None
    ticker: str
    direction: RecommendationDirection
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    indicator_summary: str = ""
    state: RecommendationState = RecommendationState.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluated_at: datetime | None = None


class RunOutput(BaseModel):
    recommendation: Recommendation
    diagnostics: RunDiagnostics = Field(default_factory=RunDiagnostics)


class RecommendationHistoryItem(BaseModel):
    recommendation_id: int
    run_id: int
    run_status: str
    ticker: str
    direction: RecommendationDirection
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    indicator_summary: str = ""
    state: RecommendationState = RecommendationState.PENDING
    created_at: datetime
    evaluated_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    provider_errors: list[str] = Field(default_factory=list)
    summary_error: str | None = None
    llm_error: str | None = None


class PrototypeTradeLogEntry(BaseModel):
    id: int
    timestamp: str
    ticker: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float | None = None
    status: RecommendationState
    close_timestamp: str | None = None
    duration_days: float | None = None
    analysis_json: str | None = None


class TickerPerformanceSummary(BaseModel):
    ticker: str
    app_recommendation_count: int = 0
    pending_recommendation_count: int = 0
    win_recommendation_count: int = 0
    loss_recommendation_count: int = 0
    warning_recommendation_count: int = 0
    long_recommendation_count: int = 0
    short_recommendation_count: int = 0
    neutral_recommendation_count: int = 0
    average_confidence: float | None = None
    prototype_trade_log_path: str = ""
    prototype_trade_log_available: bool = False
    prototype_trade_count: int = 0
    resolved_trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    pending_trade_count: int = 0
    win_rate_percent: float | None = None
    average_resolved_duration_days: float | None = None


class TickerAnalysisPage(BaseModel):
    ticker: str
    performance: TickerPerformanceSummary
    recommendation_history: list[RecommendationHistoryItem] = Field(default_factory=list)
    prototype_trades: list[PrototypeTradeLogEntry] = Field(default_factory=list)


class EvaluationRunResult(BaseModel):
    evaluated_trade_log_entries: int = 0
    synced_recommendations: int = 0
    pending_recommendations: int = 0
    win_recommendations: int = 0
    loss_recommendations: int = 0
    evaluated_recommendation_plans: int = 0
    synced_recommendation_plan_outcomes: int = 0
    pending_recommendation_plan_outcomes: int = 0
    win_recommendation_plan_outcomes: int = 0
    loss_recommendation_plan_outcomes: int = 0
    no_action_recommendation_plan_outcomes: int = 0
    watchlist_recommendation_plan_outcomes: int = 0
    output: str = ""


class Watchlist(BaseModel):
    id: int | None = None
    name: str
    description: str = ""
    region: str = ""
    exchange: str = ""
    timezone: str = ""
    default_horizon: StrategyHorizon = StrategyHorizon.ONE_WEEK
    allow_shorts: bool = True
    optimize_evaluation_timing: bool = False
    tickers: list[str] = Field(default_factory=list)


class WatchlistEvaluationPolicy(BaseModel):
    watchlist_id: int | None = None
    watchlist_name: str
    default_horizon: StrategyHorizon
    schedule_source: str
    schedule_timezone: str
    primary_cron: str | None = None
    primary_window_label: str = ""
    secondary_window_label: str = ""
    shortlist_strategy: str = "cheap_scan_then_deep_analysis"
    warnings: list[str] = Field(default_factory=list)


class Job(BaseModel):
    id: int | None = None
    name: str
    job_type: JobType = JobType.PROPOSAL_GENERATION
    tickers: list[str] = Field(default_factory=list)
    watchlist_id: int | None = None
    watchlist_name: str | None = None
    watchlist_description: str = ""
    watchlist_region: str = ""
    watchlist_exchange: str = ""
    watchlist_timezone: str = ""
    watchlist_default_horizon: StrategyHorizon | None = None
    watchlist_allow_shorts: bool = True
    watchlist_optimize_evaluation_timing: bool = False
    enabled: bool = True
    cron: str | None = None
    last_enqueued_at: datetime | None = None


class Run(BaseModel):
    id: int | None = None
    job_id: int
    job_type: JobType = JobType.PROPOSAL_GENERATION
    status: RunStatus = RunStatus.QUEUED
    error_message: str | None = None
    scheduled_for: datetime | None = None
    summary_json: str | None = None
    artifact_json: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    timing_json: str | None = None


class AppSetting(BaseModel):
    key: str
    value: str


class SentimentSnapshot(BaseModel):
    id: int | None = None
    scope: str
    subject_key: str
    subject_label: str
    status: str = "completed"
    score: float = 0.0
    label: str = "NEUTRAL"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    coverage_json: str | None = None
    source_breakdown_json: str | None = None
    drivers_json: str | None = None
    signals_json: str | None = None
    diagnostics_json: str | None = None
    summary_text: str = ""
    job_id: int | None = None
    run_id: int | None = None


class MacroContextSnapshot(BaseModel):
    id: int | None = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ok"
    summary_text: str = ""
    saliency_score: float = 0.0
    confidence_percent: float = 0.0
    active_themes: list[dict[str, object]] = Field(default_factory=list)
    regime_tags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    source_breakdown: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    run_id: int | None = None
    job_id: int | None = None


class IndustryContextSnapshot(BaseModel):
    id: int | None = None
    industry_key: str
    industry_label: str = ""
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ok"
    summary_text: str = ""
    direction: str = "neutral"
    saliency_score: float = 0.0
    confidence_percent: float = 0.0
    active_drivers: list[dict[str, object]] = Field(default_factory=list)
    linked_macro_themes: list[str] = Field(default_factory=list)
    linked_industry_themes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    source_breakdown: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    run_id: int | None = None
    job_id: int | None = None


class TickerSignalSnapshot(BaseModel):
    id: int | None = None
    ticker: str
    horizon: StrategyHorizon = StrategyHorizon.ONE_WEEK
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ok"
    direction: str = "neutral"
    swing_probability_percent: float = 0.0
    confidence_percent: float = 0.0
    attention_score: float = 0.0
    macro_exposure_score: float = 0.0
    industry_alignment_score: float = 0.0
    ticker_sentiment_score: float = 0.0
    technical_setup_score: float = 0.0
    catalyst_score: float = 0.0
    expected_move_score: float = 0.0
    execution_quality_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    source_breakdown: dict[str, object] = Field(default_factory=dict)
    diagnostics: dict[str, object] = Field(default_factory=dict)
    run_id: int | None = None
    job_id: int | None = None


class RecommendationPlanOutcome(BaseModel):
    id: int | None = None
    recommendation_plan_id: int
    ticker: str = ""
    action: str = ""
    outcome: str
    status: str = "open"
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entry_touched: bool | None = None
    stop_loss_hit: bool | None = None
    take_profit_hit: bool | None = None
    horizon_return_1d: float | None = None
    horizon_return_3d: float | None = None
    horizon_return_5d: float | None = None
    max_favorable_excursion: float | None = None
    max_adverse_excursion: float | None = None
    realized_holding_period_days: float | None = None
    direction_correct: bool | None = None
    confidence_bucket: str = ""
    setup_family: str = ""
    notes: str = ""
    run_id: int | None = None


class RecommendationPlan(BaseModel):
    id: int | None = None
    ticker: str
    horizon: StrategyHorizon = StrategyHorizon.ONE_WEEK
    action: str
    status: str = "ok"
    confidence_percent: float = 0.0
    entry_price_low: float | None = None
    entry_price_high: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    holding_period_days: int | None = None
    risk_reward_ratio: float | None = None
    thesis_summary: str = ""
    rationale_summary: str = ""
    risks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, object] = Field(default_factory=dict)
    signal_breakdown: dict[str, object] = Field(default_factory=dict)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: int | None = None
    job_id: int | None = None
    watchlist_id: int | None = None
    ticker_signal_snapshot_id: int | None = None
    latest_outcome: RecommendationPlanOutcome | None = None


class ProviderCredential(BaseModel):
    provider: str
    api_key: str = ""
    api_secret: str = ""


class PreflightCheck(BaseModel):
    name: str
    status: str
    message: str
    details: list[str] = Field(default_factory=list)


class AppPreflightReport(BaseModel):
    status: str
    checked_at: datetime
    engine: str
    checks: list[PreflightCheck] = Field(default_factory=list)
