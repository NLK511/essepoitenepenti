from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WatchlistRecord(Base, TimestampMixin):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    region: Mapped[str] = mapped_column(String(64), default="")
    exchange: Mapped[str] = mapped_column(String(64), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    default_horizon: Mapped[str] = mapped_column(String(8), default="1w")
    allow_shorts: Mapped[bool] = mapped_column(Boolean, default=True)
    optimize_evaluation_timing: Mapped[bool] = mapped_column(Boolean, default=False)
    tickers_csv: Mapped[str] = mapped_column(Text)
    jobs: Mapped[list["JobRecord"]] = relationship(back_populates="watchlist")


class JobRecord(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), default="proposal_generation", index=True)
    tickers_csv: Mapped[str] = mapped_column(Text)
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlists.id"), nullable=True, index=True)
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    watchlist: Mapped[WatchlistRecord | None] = relationship(back_populates="jobs")
    runs: Mapped[list["RunRecord"]] = relationship(back_populates="job")


class RunRecord(Base, TimestampMixin):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("job_id", "scheduled_for", name="uq_runs_job_id_scheduled_for"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(64), default="proposal_generation", index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="")
    artifact_json: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("worker_heartbeats.worker_id"), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    timing_json: Mapped[str] = mapped_column(Text, default="")
    job: Mapped[JobRecord] = relationship(back_populates="runs")


class WorkerHeartbeatRecord(Base, TimestampMixin):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("runs.id"), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<WorkerHeartbeat(worker_id={self.worker_id}, status={self.status})>"


class HistoricalReplayBatchRecord(Base, TimestampMixin):
    __tablename__ = "historical_replay_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    mode: Mapped[str] = mapped_column(String(32), default="research", index=True)
    universe_mode: Mapped[str] = mapped_column(String(32), default="explicit")
    universe_preset: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    tickers_json: Mapped[str] = mapped_column(Text, default="[]")
    entry_timing: Mapped[str] = mapped_column(String(32), default="next_open")
    price_provider: Mapped[str] = mapped_column(String(64), default="yahoo")
    price_source_tier: Mapped[str] = mapped_column(String(32), default="research")
    bar_timeframe: Mapped[str] = mapped_column(String(16), default="1d")
    as_of_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    as_of_end: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    cadence: Mapped[str] = mapped_column(String(32), default="daily")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    artifact_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class HistoricalReplaySliceRecord(Base, TimestampMixin):
    __tablename__ = "historical_replay_slices"
    __table_args__ = (UniqueConstraint("replay_batch_id", "as_of", name="uq_historical_replay_slice_batch_as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replay_batch_id: Mapped[int] = mapped_column(ForeignKey("historical_replay_batches.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    input_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    output_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    timing_json: Mapped[str] = mapped_column(Text, default="{}")


class HistoricalMarketBarRecord(Base, TimestampMixin):
    __tablename__ = "historical_market_bars"
    __table_args__ = (UniqueConstraint("ticker", "timeframe", "bar_time", name="uq_historical_market_bars_ticker_timeframe_bar_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="1d", index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    open_price: Mapped[float] = mapped_column(Float, default=0.0)
    high_price: Mapped[float] = mapped_column(Float, default=0.0)
    low_price: Mapped[float] = mapped_column(Float, default=0.0)
    close_price: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    source_tier: Mapped[str] = mapped_column(String(32), default="tier_a")
    point_in_time_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class AppSettingRecord(Base, TimestampMixin):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ProviderCredentialRecord(Base, TimestampMixin):
    __tablename__ = "provider_credentials"

    provider: Mapped[str] = mapped_column(String(120), primary_key=True)
    api_key: Mapped[str] = mapped_column(Text, default="")
    api_secret: Mapped[str] = mapped_column(Text, default="")


class SupportSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "sentiment_snapshots"
    __table_args__ = (
        Index("ix_sentiment_snapshots_scope", "scope"),
        Index("ix_sentiment_snapshots_subject_key", "subject_key"),
        Index("ix_sentiment_snapshots_computed_at", "computed_at"),
        Index("ix_sentiment_snapshots_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(32))
    subject_key: Mapped[str] = mapped_column(String(120))
    subject_label: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(32), default="completed")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    label: Mapped[str] = mapped_column(String(32), default="NEUTRAL")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    coverage_json: Mapped[str] = mapped_column(Text, default="")
    source_breakdown_json: Mapped[str] = mapped_column(Text, default="")
    drivers_json: Mapped[str] = mapped_column(Text, default="")
    signals_json: Mapped[str] = mapped_column(Text, default="")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="")
    summary_text: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


SupportSnapshotRecord = SupportSnapshotRecord


class MacroContextSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "macro_context_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    saliency_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_percent: Mapped[float] = mapped_column(Float, default=0.0)
    active_themes_json: Mapped[str] = mapped_column(Text, default="")
    regime_tags_json: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[str] = mapped_column(Text, default="")
    missing_inputs_json: Mapped[str] = mapped_column(Text, default="")
    source_breakdown_json: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class IndustryContextSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "industry_context_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry_key: Mapped[str] = mapped_column(String(120), index=True)
    industry_label: Mapped[str] = mapped_column(String(120), default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(32), default="neutral")
    saliency_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_percent: Mapped[float] = mapped_column(Float, default=0.0)
    active_drivers_json: Mapped[str] = mapped_column(Text, default="")
    linked_macro_themes_json: Mapped[str] = mapped_column(Text, default="")
    linked_industry_themes_json: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[str] = mapped_column(Text, default="")
    missing_inputs_json: Mapped[str] = mapped_column(Text, default="")
    source_breakdown_json: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class TickerSignalSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "ticker_signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    horizon: Mapped[str] = mapped_column(String(8), default="1w", index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    direction: Mapped[str] = mapped_column(String(32), default="neutral")
    swing_probability_percent: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_percent: Mapped[float] = mapped_column(Float, default=0.0)
    attention_score: Mapped[float] = mapped_column(Float, default=0.0)
    macro_exposure_score: Mapped[float] = mapped_column(Float, default=0.0)
    industry_alignment_score: Mapped[float] = mapped_column(Float, default=0.0)
    ticker_sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    technical_setup_score: Mapped[float] = mapped_column(Float, default=0.0)
    catalyst_score: Mapped[float] = mapped_column(Float, default=0.0)
    expected_move_score: Mapped[float] = mapped_column(Float, default=0.0)
    execution_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    warnings_json: Mapped[str] = mapped_column(Text, default="")
    missing_inputs_json: Mapped[str] = mapped_column(Text, default="")
    source_breakdown_json: Mapped[str] = mapped_column(Text, default="")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class RecommendationPlanRecord(Base, TimestampMixin):
    __tablename__ = "recommendation_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    horizon: Mapped[str] = mapped_column(String(8), default="1w", index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    confidence_percent: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    thesis_summary: Mapped[str] = mapped_column(Text, default="")
    rationale_summary: Mapped[str] = mapped_column(Text, default="")
    risks_json: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[str] = mapped_column(Text, default="")
    missing_inputs_json: Mapped[str] = mapped_column(Text, default="")
    evidence_summary_json: Mapped[str] = mapped_column(Text, default="")
    signal_breakdown_json: Mapped[str] = mapped_column(Text, default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlists.id"), nullable=True, index=True)
    ticker_signal_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("ticker_signal_snapshots.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class RecommendationOutcomeRecord(Base, TimestampMixin):
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (UniqueConstraint("recommendation_plan_id", name="uq_recommendation_outcomes_plan_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_plan_id: Mapped[int] = mapped_column(ForeignKey("recommendation_plans.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(32), default="open", index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    entry_touched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stop_loss_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    take_profit_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    horizon_return_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_return_3d: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_return_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_holding_period_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence_bucket: Mapped[str] = mapped_column(String(32), default="")
    setup_family: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class RecommendationDecisionSampleRecord(Base, TimestampMixin):
    __tablename__ = "recommendation_decision_samples"
    __table_args__ = (UniqueConstraint("recommendation_plan_id", name="uq_recommendation_decision_samples_plan_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_plan_id: Mapped[int] = mapped_column(ForeignKey("recommendation_plans.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    horizon: Mapped[str] = mapped_column(String(8), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    decision_type: Mapped[str] = mapped_column(String(32), default="no_action", index=True)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    shortlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    shortlist_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shortlist_decision_json: Mapped[str] = mapped_column(Text, default="{}")
    confidence_percent: Mapped[float] = mapped_column(Float, default=0.0)
    calibrated_confidence_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_threshold_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_gap_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_family: Mapped[str] = mapped_column(String(64), default="")
    transmission_bias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    context_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_priority: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    review_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    decision_context_json: Mapped[str] = mapped_column(Text, default="{}")
    signal_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlists.id"), nullable=True, index=True)
    ticker_signal_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("ticker_signal_snapshots.id"), nullable=True, index=True)


class RecommendationAutotuneRunRecord(Base, TimestampMixin):
    __tablename__ = "recommendation_autotune_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    objective_name: Mapped[str] = mapped_column(String(120), default="confidence_threshold_raw_grid", index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    winning_config_json: Mapped[str] = mapped_column(Text, default="{}")
    candidate_results_json: Mapped[str] = mapped_column(Text, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    artifact_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
