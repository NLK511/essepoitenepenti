from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    timing_json: Mapped[str] = mapped_column(Text, default="")
    job: Mapped[JobRecord] = relationship(back_populates="runs")
    recommendations: Mapped[list["RecommendationRecord"]] = relationship(back_populates="run")


class RecommendationRecord(Base, TimestampMixin):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    indicator_summary: Mapped[str] = mapped_column(Text, default="")
    evaluation_state: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="")
    provider_errors_json: Mapped[str] = mapped_column(Text, default="")
    problems_json: Mapped[str] = mapped_column(Text, default="")
    news_feed_errors_json: Mapped[str] = mapped_column(Text, default="")
    summary_error: Mapped[str] = mapped_column(Text, default="")
    llm_error: Mapped[str] = mapped_column(Text, default="")
    analysis_json: Mapped[str] = mapped_column(Text, default="")
    raw_output: Mapped[str] = mapped_column(Text, default="")
    feature_vector_json: Mapped[str] = mapped_column(Text, default="")
    normalized_feature_vector_json: Mapped[str] = mapped_column(Text, default="")
    aggregations_json: Mapped[str] = mapped_column(Text, default="")
    confidence_weights_json: Mapped[str] = mapped_column(Text, default="")
    summary_method: Mapped[str] = mapped_column(String(64), default="")
    run: Mapped[RunRecord] = relationship(back_populates="recommendations")


class AppSettingRecord(Base, TimestampMixin):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ProviderCredentialRecord(Base, TimestampMixin):
    __tablename__ = "provider_credentials"

    provider: Mapped[str] = mapped_column(String(120), primary_key=True)
    api_key: Mapped[str] = mapped_column(Text, default="")
    api_secret: Mapped[str] = mapped_column(Text, default="")
