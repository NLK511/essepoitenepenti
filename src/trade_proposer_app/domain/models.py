from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from trade_proposer_app.domain.enums import JobType, RecommendationDirection, RecommendationState, RunStatus, StrategyHorizon


class DictLikeModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    def _mapping(self) -> dict[str, object]:
        values = dict(self.__dict__)
        if self.model_extra:
            values.update(self.model_extra)
        return values

    def __getitem__(self, key: str) -> object:
        return self._mapping()[key]

    def get(self, key: str, default: object | None = None) -> object | None:
        return self._mapping().get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._mapping()

    def keys(self):
        return self._mapping().keys()

    def items(self):
        return self._mapping().items()

    def values(self):
        return self._mapping().values()


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
    query_diagnostics: dict[str, object] = Field(default_factory=dict)


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


class TickerPerformanceSummary(BaseModel):
    ticker: str
    app_plan_count: int = 0
    actionable_plan_count: int = 0
    long_plan_count: int = 0
    short_plan_count: int = 0
    no_action_plan_count: int = 0
    watchlist_plan_count: int = 0
    open_plan_count: int = 0
    win_plan_count: int = 0
    loss_plan_count: int = 0
    warning_plan_count: int = 0
    average_confidence: float | None = None


class TickerAnalysisPage(BaseModel):
    ticker: str
    performance: TickerPerformanceSummary
    recommendation_plans: list["RecommendationPlan"] = Field(default_factory=list)


class EvaluationRunResult(BaseModel):
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
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    timing_json: str | None = None


class BrokerOrderExecution(BaseModel):
    id: int | None = None
    broker: str = "alpaca"
    account_mode: str = "paper"
    recommendation_plan_id: int
    recommendation_plan_ticker: str = ""
    run_id: int | None = None
    job_id: int | None = None
    ticker: str
    action: str
    side: str
    order_type: str
    time_in_force: str = "gtc"
    quantity: int = 0
    notional_amount: float = 0.0
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    status: str = "queued"
    broker_order_id: str | None = None
    client_order_id: str = ""
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    canceled_at: datetime | None = None
    request_payload: dict[str, object] = Field(default_factory=dict)
    response_payload: dict[str, object] = Field(default_factory=dict)
    error_message: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerHeartbeat(BaseModel):
    worker_id: str
    hostname: str
    pid: int
    status: str
    last_heartbeat_at: datetime
    started_at: datetime
    version: str | None = None
    active_run_id: int | None = None
    metadata_json: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AppSetting(BaseModel):
    key: str
    value: str


class MacroContextRefreshPayload(BaseModel):
    subject_key: str
    subject_label: str
    score: float = 0.0
    label: str = "NEUTRAL"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    coverage: dict[str, object] = Field(default_factory=dict)
    source_breakdown: dict[str, object] = Field(default_factory=dict)
    drivers: list[dict[str, object]] = Field(default_factory=list)
    signals: dict[str, object] = Field(default_factory=dict)
    diagnostics: dict[str, object] = Field(default_factory=dict)
    summary_text: str = ""
    job_id: int | None = None
    run_id: int | None = None


class IndustryContextRefreshPayload(BaseModel):
    subject_key: str
    subject_label: str
    score: float = 0.0
    label: str = "NEUTRAL"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    coverage: dict[str, object] = Field(default_factory=dict)
    source_breakdown: dict[str, object] = Field(default_factory=dict)
    drivers: list[dict[str, object]] = Field(default_factory=list)
    signals: dict[str, object] = Field(default_factory=dict)
    diagnostics: dict[str, object] = Field(default_factory=dict)
    summary_text: str = ""
    job_id: int | None = None
    run_id: int | None = None


class MacroContextSnapshot(BaseModel):
    id: int | None = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
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
    expires_at: datetime | None = None
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


class KeyLabelDetail(DictLikeModel):
    key: str
    label: str


class RecommendationTransmissionSummary(DictLikeModel):
    alignment_percent: float | None = None
    context_bias: str | None = None
    transmission_bias: str | None = None
    transmission_bias_detail: KeyLabelDetail | None = None
    catalyst_intensity_percent: float | None = None
    context_strength_percent: float | None = None
    context_event_relevance_percent: float | None = None
    contradiction_count: int | None = None
    transmission_tags: list[str] = Field(default_factory=list)
    transmission_tag_details: list[KeyLabelDetail] = Field(default_factory=list)
    primary_drivers: list[str] = Field(default_factory=list)
    primary_driver_details: list[KeyLabelDetail] = Field(default_factory=list)
    industry_exposure_channels: list[str] = Field(default_factory=list)
    industry_exposure_channel_details: list[KeyLabelDetail] = Field(default_factory=list)
    ticker_exposure_channels: list[str] = Field(default_factory=list)
    ticker_exposure_channel_details: list[KeyLabelDetail] = Field(default_factory=list)
    expected_transmission_window: str | None = None
    expected_transmission_window_detail: KeyLabelDetail | None = None
    conflict_flags: list[str] = Field(default_factory=list)
    conflict_flag_details: list[KeyLabelDetail] = Field(default_factory=list)
    decay_state: str | None = None
    transmission_confidence_adjustment: float | None = None
    lane_hint: str | None = None
    ticker_relationship_edges: list[dict[str, object]] = Field(default_factory=list)
    matched_ticker_relationships: list[dict[str, object]] = Field(default_factory=list)
    matched_ticker_relationship_details: list[dict[str, object]] = Field(default_factory=list)
    transmission_alignment_score: float | None = None


class RecommendationCalibrationReview(DictLikeModel):
    enabled: bool | None = None
    review_status: str | None = None
    review_status_label: str | None = None
    raw_confidence_percent: float | None = None
    calibrated_confidence_percent: float | None = None
    confidence_adjustment: float | None = None
    base_confidence_threshold: float | None = None
    effective_confidence_threshold: float | None = None
    threshold_adjustment: float | None = None
    overall_win_rate_percent: float | None = None
    setup_family: "RecommendationCalibrationBucket | dict[str, object] | None" = None
    confidence_bucket: "RecommendationCalibrationBucket | dict[str, object] | None" = None
    horizon: "RecommendationCalibrationBucket | dict[str, object] | None" = None
    transmission_bias: "RecommendationCalibrationBucket | dict[str, object] | None" = None
    context_regime: "RecommendationCalibrationBucket | dict[str, object] | None" = None
    horizon_setup_family: "RecommendationCalibrationBucket | dict[str, object] | None" = None
    reasons: list[str] = Field(default_factory=list)
    reason_details: list[KeyLabelDetail] = Field(default_factory=list)


class RecommendationPlanEvidenceSummary(DictLikeModel):
    summary: str = ""
    setup_family: str | None = None
    action_reason: str | None = None
    action_reason_label: str | None = None
    action_reason_detail: str | None = None
    confidence_components: dict[str, float] = Field(default_factory=dict)
    raw_confidence_percent: float | None = None
    calibrated_confidence_percent: float | None = None
    confidence_adjustment: float | None = None
    calibration_review: RecommendationCalibrationReview | None = None
    transmission_summary: RecommendationTransmissionSummary | None = None
    entry_style: str | None = None
    stop_style: str | None = None
    target_style: str | None = None
    timing_expectation: str | None = None
    evaluation_focus: list[str] = Field(default_factory=list)
    invalidation_summary: str | None = None


class RecommendationPlanSignalBreakdown(DictLikeModel):
    attention_score: float | None = None
    macro_exposure_score: float | None = None
    industry_alignment_score: float | None = None
    ticker_sentiment_score: float | None = None
    technical_setup_score: float | None = None
    catalyst_score: float | None = None
    expected_move_score: float | None = None
    execution_quality_score: float | None = None
    setup_family: str | None = None
    confidence_components: dict[str, float] = Field(default_factory=dict)
    raw_confidence_percent: float | None = None
    calibrated_confidence_percent: float | None = None
    confidence_bucket: str | None = None
    calibration_review: RecommendationCalibrationReview | None = None
    transmission_summary: RecommendationTransmissionSummary | None = None
    mode: str | None = None


class TickerSignalSourceBreakdown(RecommendationTransmissionSummary):
    cheap_scan_summary: str | None = None
    cheap_scan_model: str | None = None
    deep_analysis_available: bool | None = None
    deep_analysis_model: str | None = None
    summary_method: str | None = None
    base_confidence_percent: float | None = None


class TickerSignalDiagnostics(RecommendationTransmissionSummary):
    mode: str | None = None
    shortlisted: bool | None = None
    shortlist_rank: int | None = None
    shortlist_reasons: list[str] = Field(default_factory=list)
    shortlist_reason_details: list[KeyLabelDetail] = Field(default_factory=list)
    shortlist_eligible: bool | None = None
    selection_lane: str | None = None
    selection_lane_label: str | None = None
    cheap_scan_confidence_percent: float | None = None
    cheap_scan_directional_score: float | None = None
    catalyst_proxy_score: float | None = None
    cheap_scan_component_scores: dict[str, object] = Field(default_factory=dict)


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
    source_breakdown: TickerSignalSourceBreakdown = Field(default_factory=TickerSignalSourceBreakdown)
    diagnostics: TickerSignalDiagnostics = Field(default_factory=TickerSignalDiagnostics)
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
    entry_miss_distance_percent: float | None = None
    near_entry_miss: bool | None = None
    direction_worked_without_entry: bool | None = None
    max_favorable_excursion: float | None = None
    max_adverse_excursion: float | None = None
    realized_holding_period_days: float | None = None
    direction_correct: bool | None = None
    confidence_percent: float | None = None
    confidence_bucket: str = ""
    setup_family: str = ""
    horizon: str | None = None
    transmission_bias: str | None = None
    transmission_bias_label: str | None = None
    transmission_bias_detail: KeyLabelDetail | None = None
    context_regime: str | None = None
    context_regime_label: str | None = None
    context_regime_detail: KeyLabelDetail | None = None
    notes: str = ""
    run_id: int | None = None


class RecommendationDecisionSample(BaseModel):
    id: int | None = None
    recommendation_plan_id: int | None = None
    ticker: str
    horizon: str
    action: str
    decision_type: str = "no_action"
    decision_reason: str = ""
    shortlisted: bool = False
    shortlist_rank: int | None = None
    shortlist_decision: dict[str, object] = Field(default_factory=dict)
    confidence_percent: float = 0.0
    calibrated_confidence_percent: float | None = None
    effective_threshold_percent: float | None = None
    confidence_gap_percent: float | None = None
    setup_family: str = ""
    transmission_bias: str | None = None
    context_regime: str | None = None
    review_priority: str = "normal"
    review_label: str | None = None
    review_notes: str = ""
    reviewed_at: datetime | None = None
    decision_context: dict[str, object] = Field(default_factory=dict)
    signal_breakdown: dict[str, object] = Field(default_factory=dict)
    evidence_summary: dict[str, object] = Field(default_factory=dict)
    benchmark_direction: str | None = None
    benchmark_status: str = "pending"
    benchmark_target_1d_hit: bool | None = None
    benchmark_target_5d_hit: bool | None = None
    benchmark_max_favorable_pct: float | None = None
    benchmark_evaluated_at: datetime | None = None
    run_id: int | None = None
    job_id: int | None = None
    watchlist_id: int | None = None
    ticker_signal_snapshot_id: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    evidence_summary: RecommendationPlanEvidenceSummary = Field(default_factory=RecommendationPlanEvidenceSummary)
    signal_breakdown: RecommendationPlanSignalBreakdown = Field(default_factory=RecommendationPlanSignalBreakdown)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: int | None = None
    job_id: int | None = None
    watchlist_id: int | None = None
    ticker_signal_snapshot_id: int | None = None
    latest_outcome: RecommendationPlanOutcome | None = None


class RecommendationCalibrationBucket(DictLikeModel):
    key: str
    label: str
    slice_name: str = ""
    slice_label: str = ""
    total_count: int = 0
    resolved_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    open_count: int = 0
    no_action_count: int = 0
    watchlist_count: int = 0
    sample_status: str = "insufficient"
    min_required_resolved_count: int = 0
    win_rate_percent: float | None = None
    average_return_1d: float | None = None
    average_return_3d: float | None = None
    average_return_5d: float | None = None
    average_mfe: float | None = None
    average_mae: float | None = None


class RecommendationPlanStats(BaseModel):
    total_plans: int = 0
    open_plans: int = 0
    expired_plans: int = 0
    scored_outcomes: int = 0
    win_rate_percent: float | None = None
    window: str = "all"
    resolved_outcomes: int = 0
    open_outcomes: int = 0
    expired_outcomes: int = 0
    win_outcomes: int = 0
    loss_outcomes: int = 0
    no_action_outcomes: int = 0
    watchlist_outcomes: int = 0


class RecommendationCalibrationReliabilityBin(BaseModel):
    bin_key: str
    bin_label: str
    sample_count: int = 0
    resolved_count: int = 0
    predicted_probability: float | None = None
    realized_win_rate_percent: float | None = None
    brier_score: float | None = None
    calibration_error: float | None = None


class RecommendationCalibrationReport(BaseModel):
    version_label: str = "v1"
    method: str = "confidence_binned_reliability"
    sample_count: int = 0
    resolved_count: int = 0
    brier_score: float | None = None
    expected_calibration_error: float | None = None
    bins: list[RecommendationCalibrationReliabilityBin] = Field(default_factory=list)


class RecommendationCalibrationSummary(BaseModel):
    total_outcomes: int = 0
    resolved_outcomes: int = 0
    open_outcomes: int = 0
    win_outcomes: int = 0
    loss_outcomes: int = 0
    no_action_outcomes: int = 0
    watchlist_outcomes: int = 0
    overall_win_rate_percent: float | None = None
    calibration_report: RecommendationCalibrationReport | None = None
    smoothed_calibration_report: RecommendationCalibrationReport | None = None
    by_confidence_bucket: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_setup_family: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_action: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_horizon: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_transmission_bias: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_context_regime: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_horizon_setup_family: list[RecommendationCalibrationBucket] = Field(default_factory=list)


class RecommendationEvidenceConcentrationCohort(BaseModel):
    slice_name: str
    slice_label: str = ""
    key: str
    label: str
    sample_status: str = "insufficient"
    resolved_count: int = 0
    min_required_resolved_count: int = 0
    win_rate_percent: float | None = None
    average_return_5d: float | None = None
    edge_vs_overall_win_rate_percent: float | None = None
    edge_vs_overall_return_5d: float | None = None
    concentration_score: float = 0.0
    interpretation: str = ""


class RecommendationEvidenceConcentrationSummary(BaseModel):
    total_outcomes_reviewed: int = 0
    resolved_outcomes_reviewed: int = 0
    overall_win_rate_percent: float | None = None
    overall_average_return_5d: float | None = None
    ready_for_expansion: bool = False
    focus_message: str = ""
    strongest_positive_cohorts: list[RecommendationEvidenceConcentrationCohort] = Field(default_factory=list)
    weakest_cohorts: list[RecommendationEvidenceConcentrationCohort] = Field(default_factory=list)


class RecommendationWalkForwardSlice(BaseModel):
    slice_index: int = 0
    window_label: str = ""
    computed_after: datetime | None = None
    computed_before: datetime | None = None
    evaluated_after: datetime | None = None
    evaluated_before: datetime | None = None
    total_outcomes: int = 0
    resolved_outcomes: int = 0
    overall_win_rate_percent: float | None = None
    calibration_report: RecommendationCalibrationReport | None = None
    actual_actionable_win_rate_percent: float | None = None
    high_confidence_win_rate_percent: float | None = None
    actual_actionable_average_return_5d: float | None = None
    high_confidence_average_return_5d: float | None = None
    ready_for_expansion: bool = False
    setup_family_count: int = 0
    horizon_count: int = 0
    transmission_bias_count: int = 0
    context_regime_count: int = 0


class RecommendationWalkForwardSummary(BaseModel):
    total_slices: int = 0
    lookback_days: int = 0
    validation_days: int = 0
    step_days: int = 0
    min_resolved_outcomes: int = 0
    slices: list[RecommendationWalkForwardSlice] = Field(default_factory=list)


class RecommendationBaselineComparison(BaseModel):
    key: str
    label: str
    description: str = ""
    total_plan_count: int = 0
    trade_plan_count: int = 0
    resolved_trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    open_trade_count: int = 0
    win_rate_percent: float | None = None
    average_return_5d: float | None = None
    average_confidence_percent: float | None = None


class RecommendationBaselineSummary(BaseModel):
    total_plans_reviewed: int = 0
    total_trade_plans_reviewed: int = 0
    comparisons: list[RecommendationBaselineComparison] = Field(default_factory=list)
    family_cohorts: list[RecommendationBaselineComparison] = Field(default_factory=list)


class RecommendationSetupFamilyReview(BaseModel):
    family: str
    label: str
    total_outcomes: int = 0
    resolved_outcomes: int = 0
    open_outcomes: int = 0
    win_outcomes: int = 0
    loss_outcomes: int = 0
    overall_win_rate_percent: float | None = None
    average_return_1d: float | None = None
    average_return_3d: float | None = None
    average_return_5d: float | None = None
    average_mfe: float | None = None
    average_mae: float | None = None
    by_horizon: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_transmission_bias: list[RecommendationCalibrationBucket] = Field(default_factory=list)
    by_context_regime: list[RecommendationCalibrationBucket] = Field(default_factory=list)


class RecommendationSetupFamilyReviewSummary(BaseModel):
    total_outcomes_reviewed: int = 0
    families: list[RecommendationSetupFamilyReview] = Field(default_factory=list)


class RecommendationSignalGatingTuningRun(BaseModel):
    id: int | None = None
    objective_name: str = "signal_gating_tuning_raw_grid"
    status: str = "completed"
    applied: bool = False
    filters: dict[str, object] = Field(default_factory=dict)
    sample_count: int = 0
    resolved_sample_count: int = 0
    benchmark_sample_count: int = 0
    scoreable_sample_count: int = 0
    candidate_count: int = 0
    baseline_threshold: float | None = None
    baseline_score: float | None = None
    best_threshold: float | None = None
    best_score: float | None = None
    winning_config: dict[str, object] = Field(default_factory=dict)
    candidate_results: list[dict[str, object]] = Field(default_factory=list)
    summary: dict[str, object] = Field(default_factory=dict)
    artifact: dict[str, object] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanGenerationTuningCandidate(BaseModel):
    id: int | None = None
    run_id: int | None = None
    rank: int | None = None
    status: str = "evaluated"
    is_baseline: bool = False
    promotion_eligible: bool = False
    config: dict[str, object] = Field(default_factory=dict)
    changed_keys: list[str] = Field(default_factory=list)
    score_summary: dict[str, object] = Field(default_factory=dict)
    metric_breakdown: dict[str, object] = Field(default_factory=dict)
    sample_breakdown: dict[str, object] = Field(default_factory=dict)
    validation_summary: dict[str, object] = Field(default_factory=dict)
    rejection_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanGenerationTuningConfigVersion(BaseModel):
    id: int | None = None
    version_label: str
    status: str = "candidate"
    source: str = "manual"
    parent_config_version_id: int | None = None
    source_run_id: int | None = None
    source_candidate_id: int | None = None
    config: dict[str, object] = Field(default_factory=dict)
    parameter_schema_version: str = "v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanGenerationTuningEvent(BaseModel):
    id: int | None = None
    event_type: str
    run_id: int | None = None
    config_version_id: int | None = None
    candidate_id: int | None = None
    actor_type: str = "system"
    actor_identifier: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanGenerationWalkForwardSlice(BaseModel):
    slice_index: int = 0
    window_label: str = ""
    computed_after: datetime | None = None
    computed_before: datetime | None = None
    evaluated_after: datetime | None = None
    evaluated_before: datetime | None = None
    total_records: int = 0
    resolved_records: int = 0
    baseline_actionable_count: int = 0
    candidate_actionable_count: int = 0
    baseline_win_rate_percent: float | None = None
    candidate_win_rate_percent: float | None = None
    baseline_expected_value: float = 0.0
    candidate_expected_value: float = 0.0
    win_rate_delta: float | None = None
    expected_value_delta: float | None = None
    ambiguous_count: int = 0
    sample_status: str = "thin"


class PlanGenerationWalkForwardSummary(BaseModel):
    total_slices: int = 0
    lookback_days: int = 0
    validation_days: int = 0
    step_days: int = 0
    min_validation_resolved: int = 0
    candidate_label: str = "candidate"
    baseline_label: str = "baseline"
    qualified_slices: int = 0
    candidate_wins: int = 0
    baseline_wins: int = 0
    ties: int = 0
    average_win_rate_delta: float | None = None
    average_expected_value_delta: float | None = None
    promotion_recommended: bool = False
    promotion_rationale: str = ""
    slices: list[PlanGenerationWalkForwardSlice] = Field(default_factory=list)


class PlanGenerationTuningRun(BaseModel):
    id: int | None = None
    status: str = "completed"
    mode: str = "manual"
    objective_name: str = "plan_generation_precision_tuning_v1"
    promotion_mode: str = "dry_run"
    baseline_config_version_id: int | None = None
    winning_candidate_id: int | None = None
    promoted_config_version_id: int | None = None
    eligible_record_count: int = 0
    eligible_tier_a_count: int = 0
    validation_record_count: int = 0
    candidate_count: int = 0
    summary: dict[str, object] = Field(default_factory=dict)
    filters: dict[str, object] = Field(default_factory=dict)
    candidates: list[PlanGenerationTuningCandidate] = Field(default_factory=list)
    error_message: str | None = None
    code_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanGenerationTuningState(BaseModel):
    objective_name: str = "plan_generation_precision_tuning_v1"
    active_config_version_id: int | None = None
    active_config: dict[str, object] = Field(default_factory=dict)
    auto_enabled: bool = False
    auto_promote_enabled: bool = False
    latest_run: PlanGenerationTuningRun | None = None


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


class HistoricalReplayBatch(BaseModel):
    id: int | None = None
    name: str
    status: str = "planned"
    mode: str = "research"
    universe_mode: str = "explicit"
    universe_preset: str | None = None
    tickers_json: str = "[]"
    entry_timing: str = "next_open"
    price_provider: str = "yahoo"
    price_source_tier: str = "research"
    bar_timeframe: str = "1d"
    as_of_start: datetime
    as_of_end: datetime
    cadence: str = "daily"
    config_json: str = "{}"
    summary_json: str = "{}"
    artifact_json: str = "{}"
    error_message: str | None = None
    job_id: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HistoricalReplaySlice(BaseModel):
    id: int | None = None
    replay_batch_id: int
    job_id: int | None = None
    run_id: int | None = None
    as_of: datetime
    status: str = "planned"
    error_message: str | None = None
    input_summary_json: str = "{}"
    output_summary_json: str = "{}"
    timing_json: str = "{}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HistoricalMarketBar(BaseModel):
    id: int | None = None
    ticker: str
    timeframe: str = "1d"
    bar_time: datetime
    available_at: datetime | None = None
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float = 0.0
    adjusted_close: float | None = None
    source: str = ""
    source_tier: str = "tier_a"
    point_in_time_confidence: float = 1.0
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
