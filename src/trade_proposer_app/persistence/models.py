from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
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
    watchlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlists.id"), nullable=True, index=True
    )
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    watchlist: Mapped[WatchlistRecord | None] = relationship(back_populates="jobs")
    runs: Mapped[list["RunRecord"]] = relationship(back_populates="job")


class RunRecord(Base, TimestampMixin):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("job_id", "scheduled_for", name="uq_runs_job_id_scheduled_for"),
    )

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
    worker_id: Mapped[str | None] = mapped_column(
        String(120), ForeignKey("worker_heartbeats.worker_id"), nullable=True, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    timing_json: Mapped[str] = mapped_column(Text, default="")
    job: Mapped[JobRecord] = relationship(back_populates="runs")


class ObservabilityEventRecord(Base):
    __tablename__ = "observability_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info", index=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="app", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class DashboardTrendSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "dashboard_trend_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_dashboard_trend_snapshots_snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")


class BrokerAccountRecord(Base, TimestampMixin):
    __tablename__ = "broker_accounts"

    broker_account_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    broker: Mapped[str] = mapped_column(String(64), default="alpaca", index=True)
    account_mode: Mapped[str] = mapped_column(String(32), default="paper", index=True)
    account_label: Mapped[str] = mapped_column(String(120), default="", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    autonomous_execution_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    manual_actions_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    credential_reference: Mapped[str] = mapped_column(String(180), default="")
    symbol_allowlist_json: Mapped[str] = mapped_column(Text, default="[]")
    symbol_denylist_json: Mapped[str] = mapped_column(Text, default="[]")
    supported_actions_json: Mapped[str] = mapped_column(Text, default="[]")
    supported_instruments_json: Mapped[str] = mapped_column(Text, default="[]")
    supported_order_types_json: Mapped[str] = mapped_column(Text, default="[]")
    notional_cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_open_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_open_notional_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_position_notional_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_same_ticker_open_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    halt_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    halt_reason: Mapped[str] = mapped_column(Text, default="")
    validation_status: Mapped[str] = mapped_column(String(64), default="not_validated", index=True)
    validation_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_settings_json: Mapped[str] = mapped_column(Text, default="{}")


class BrokerAccountCredentialRecord(Base, TimestampMixin):
    __tablename__ = "broker_account_credentials"

    broker_account_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("broker_accounts.broker_account_id"), primary_key=True
    )
    encrypted_credentials_json: Mapped[str] = mapped_column(Text, default="{}")


class BrokerCircuitBreakerRecord(Base, TimestampMixin):
    __tablename__ = "broker_circuit_breakers"

    broker_account_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("broker_accounts.broker_account_id"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    clear_reason: Mapped[str] = mapped_column(Text, default="")


class BrokerDrawdownStateRecord(Base, TimestampMixin):
    __tablename__ = "broker_drawdown_states"

    broker_account_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("broker_accounts.broker_account_id"), primary_key=True
    )
    current_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_high_water_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_high_water_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    broker_timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    daily_boundary: Mapped[str] = mapped_column(String(32), default="")
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    baseline_source: Mapped[str] = mapped_column(String(120), default="")


class BrokerOrderExecutionRecord(Base, TimestampMixin):
    __tablename__ = "broker_order_executions"
    __table_args__ = (
        UniqueConstraint(
            "broker", "client_order_id", name="uq_broker_order_executions_broker_client_order_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker_account_id: Mapped[str] = mapped_column(
        String(120), default="alpaca-paper-default", index=True
    )
    broker: Mapped[str] = mapped_column(String(64), default="alpaca", index=True)
    account_mode: Mapped[str] = mapped_column(String(32), default="paper", index=True)
    recommendation_plan_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_plans.id"), index=True
    )
    recommendation_plan_ticker: Mapped[str] = mapped_column(String(32), default="", index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    order_type: Mapped[str] = mapped_column(String(32), default="limit", index=True)
    time_in_force: Mapped[str] = mapped_column(String(16), default="gtc", index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    notional_amount: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(120), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    request_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    response_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")


class RiskHaltEventRecord(Base):
    __tablename__ = "risk_halt_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    previous_halt_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    new_halt_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    actor: Mapped[str] = mapped_column(String(64), default="operator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class BrokerReconciliationSnapshotRecord(Base):
    __tablename__ = "broker_reconciliation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker_account_id: Mapped[str] = mapped_column(
        String(120), default="alpaca-paper-default", index=True
    )
    broker: Mapped[str] = mapped_column(String(64), default="alpaca", index=True)
    account_mode: Mapped[str] = mapped_column(String(32), default="paper", index=True)
    snapshot_type: Mapped[str] = mapped_column(String(64), default="pre_submit", index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    broker_order_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_order_executions.id"), nullable=True, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), default="", index=True)
    account_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    open_orders_payload_json: Mapped[str] = mapped_column(Text, default="[]")
    open_positions_payload_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    drift_severity: Mapped[str] = mapped_column(String(32), default="not_evaluated", index=True)
    drift_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class BrokerPositionRecord(Base, TimestampMixin):
    __tablename__ = "broker_positions"
    __table_args__ = (
        UniqueConstraint(
            "broker_order_execution_id", name="uq_broker_positions_broker_order_execution_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker_order_execution_id: Mapped[int] = mapped_column(
        ForeignKey("broker_order_executions.id"), index=True
    )
    broker_account_id: Mapped[str] = mapped_column(
        String(120), default="alpaca-paper-default", index=True
    )
    broker: Mapped[str] = mapped_column(String(64), default="alpaca", index=True)
    account_mode: Mapped[str] = mapped_column(String(32), default="paper", index=True)
    recommendation_plan_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_plans.id"), index=True
    )
    recommendation_plan_ticker: Mapped[str] = mapped_column(String(32), default="", index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    current_quantity: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    entry_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    entry_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    exit_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    exit_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    stop_loss_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    stop_loss_order_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    stop_loss_order_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    take_profit_order_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    take_profit_order_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    protective_orders_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    protective_orders_source: Mapped[str] = mapped_column(String(64), default="")
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_broker_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")


class BrokerSteeringDecisionRecord(Base, TimestampMixin):
    __tablename__ = "broker_steering_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker_account_id: Mapped[str] = mapped_column(
        String(120), default="alpaca-paper-default", index=True
    )
    recommendation_plan_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_plans.id"), index=True
    )
    broker_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_order_executions.id"), nullable=True, index=True
    )
    broker_position_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_positions.id"), nullable=True, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(64), index=True)
    execute_allowed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    execution_status: Mapped[str] = mapped_column(String(32), default="dry_run", index=True)
    reason_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    proposed_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_delta_json: Mapped[str] = mapped_column(Text, default="{}")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")


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
    __table_args__ = (
        UniqueConstraint("replay_batch_id", "as_of", name="uq_historical_replay_slice_batch_as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replay_batch_id: Mapped[int] = mapped_column(
        ForeignKey("historical_replay_batches.id"), index=True
    )
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
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "timeframe",
            "bar_time",
            name="uq_historical_market_bars_ticker_timeframe_bar_time",
        ),
    )

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


class HistoricalNewsRecord(Base, TimestampMixin):
    __tablename__ = "historical_news_items"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "link",
            "published_at",
            name="uq_historical_news_items_ticker_link_published_at",
        ),
        Index("idx_historical_news_ticker_published", "ticker", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(120), index=True)  # ticker or topic
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(Text, index=True)
    publisher: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(64), index=True)


class AppSettingRecord(Base, TimestampMixin):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ProviderCredentialRecord(Base, TimestampMixin):
    __tablename__ = "provider_credentials"

    provider: Mapped[str] = mapped_column(String(120), primary_key=True)
    api_key: Mapped[str] = mapped_column(Text, default="")
    api_secret: Mapped[str] = mapped_column(Text, default="")


class MacroContextSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "macro_context_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
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
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
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
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
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
    trade_policy_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    trade_policy_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    watchlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlists.id"), nullable=True, index=True
    )
    ticker_signal_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("ticker_signal_snapshots.id"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class FundamentalAnalysisSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "fundamental_analysis_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_set_json: Mapped[str] = mapped_column(Text, default="[]")
    coverage_status: Mapped[str] = mapped_column(String(32), default="degraded", index=True)
    freshness_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_inputs_json: Mapped[str] = mapped_column(Text, default="[]")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)


class RecommendationOutcomeRecord(Base, TimestampMixin):
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint("recommendation_plan_id", name="uq_recommendation_outcomes_plan_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_plan_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_plans.id"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(32), default="open", index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    entry_touched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stop_loss_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    take_profit_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    horizon_return_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_return_3d: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_return_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_miss_distance_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    near_entry_miss: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    direction_worked_without_entry: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
    __table_args__ = (
        UniqueConstraint(
            "recommendation_plan_id", name="uq_recommendation_decision_samples_plan_id"
        ),
        UniqueConstraint(
            "ticker_signal_snapshot_id", name="uq_recommendation_decision_samples_signal_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_plans.id"), nullable=True, index=True
    )
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
    benchmark_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    benchmark_status: Mapped[str] = mapped_column(String(32), default="pending")
    benchmark_target_1d_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    benchmark_target_5d_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    benchmark_max_favorable_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    watchlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlists.id"), nullable=True, index=True
    )
    ticker_signal_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("ticker_signal_snapshots.id"), nullable=True, index=True
    )


class RecommendationSignalGatingTuningRunRecord(Base, TimestampMixin):
    __tablename__ = "signal_gating_tuning_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    objective_name: Mapped[str] = mapped_column(
        String(120), default="signal_gating_tuning_raw_grid", index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    benchmark_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    scoreable_sample_count: Mapped[int] = mapped_column(Integer, default=0)
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


class PlanGenerationTuningRunRecord(Base, TimestampMixin):
    __tablename__ = "plan_generation_tuning_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    mode: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    objective_name: Mapped[str] = mapped_column(
        String(120), default="plan_generation_precision_tuning_v1", index=True
    )
    promotion_mode: Mapped[str] = mapped_column(String(32), default="dry_run")
    baseline_config_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_config_versions.id"), nullable=True, index=True
    )
    winning_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_candidates.id"), nullable=True, index=True
    )
    promoted_config_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_config_versions.id"), nullable=True, index=True
    )
    eligible_record_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_tier_a_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_record_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlanGenerationTuningCandidateRecord(Base, TimestampMixin):
    __tablename__ = "plan_generation_tuning_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("plan_generation_tuning_runs.id"), index=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="evaluated", index=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    promotion_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    changed_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    score_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    metric_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    sample_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    rejection_reasons_json: Mapped[str] = mapped_column(Text, default="[]")


class PlanGenerationTuningEligibleRecordRecord(Base, TimestampMixin):
    __tablename__ = "plan_generation_tuning_eligible_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_plans.id"), unique=True, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    setup_family: Mapped[str] = mapped_column(String(64), default="", index=True)
    context_bias: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    confidence_percent: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_return_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_version: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class PlanGenerationTuningConfigVersionRecord(Base, TimestampMixin):
    __tablename__ = "plan_generation_tuning_config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_label: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    parent_config_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_config_versions.id"), nullable=True, index=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_runs.id"), nullable=True, index=True
    )
    source_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_candidates.id"), nullable=True, index=True
    )
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    parameter_schema_version: Mapped[str] = mapped_column(String(32), default="v1")


class PlanGenerationTuningEventRecord(Base, TimestampMixin):
    __tablename__ = "plan_generation_tuning_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_runs.id"), nullable=True, index=True
    )
    config_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_config_versions.id"), nullable=True, index=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_generation_tuning_candidates.id"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), default="system")
    actor_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
