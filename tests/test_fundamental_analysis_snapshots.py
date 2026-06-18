from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import BrokerPosition
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _full_provider_payload() -> dict[str, object]:
    return {
        "info": {
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3_000_000_000_000,
            "currency": "USD",
            "trailingPE": 31.2,
            "forwardPE": 27.4,
            "priceToSalesTrailing12Months": 7.8,
            "priceToBook": 45.0,
            "grossMargins": 0.46,
            "operatingMargins": 0.31,
            "profitMargins": 0.26,
            "returnOnEquity": 1.4,
            "revenueGrowth": 0.06,
            "earningsGrowth": 0.09,
            "debtToEquity": 180.0,
            "currentRatio": 0.95,
            "operatingCashflow": 110_000_000_000,
            "freeCashflow": 95_000_000_000,
            "recommendationMean": 2.1,
            "recommendationKey": "buy",
            "targetMeanPrice": 230.0,
            "currentPrice": 200.0,
            "earningsTimestamp": 1_779_033_600,
            "exDividendDate": 1_775_836_800,
        },
        "calendar": [{"Event": "Annual Meeting", "Date": "2026-05-15"}],
        "recommendations": [
            {"period": "0m", "strongBuy": 10, "buy": 20, "hold": 8, "sell": 1, "strongSell": 0}
        ],
    }


def test_fundamental_snapshot_repository_round_trips_immutable_point_in_time_records() -> None:
    from trade_proposer_app.repositories.fundamental_analysis_snapshots import (
        FundamentalAnalysisSnapshotRepository,
    )

    session = create_session()
    repo = FundamentalAnalysisSnapshotRepository(session)
    jan = datetime(2026, 1, 10, tzinfo=timezone.utc)
    feb = datetime(2026, 2, 10, tzinfo=timezone.utc)

    first = repo.create_snapshot(
        ticker="aapl",
        as_of=jan,
        source_set=["yfinance"],
        coverage_status="ok",
        freshness_status="fresh",
        payload={"feature_buckets": {"valuation": "high"}},
        warnings=[],
        missing_inputs=[],
        job_id=1,
        run_id=2,
    )
    second = repo.create_snapshot(
        ticker="AAPL",
        as_of=feb,
        source_set=["yfinance"],
        coverage_status="degraded",
        freshness_status="fresh",
        payload={"feature_buckets": {"valuation": "medium"}},
        warnings=["price target unavailable"],
        missing_inputs=["targetMeanPrice"],
    )

    assert first["id"] != second["id"]
    assert repo.get_latest_for_ticker("aapl")["id"] == second["id"]
    assert repo.get_latest_at_or_before("AAPL", jan + timedelta(days=1))["id"] == first["id"]
    assert repo.get_latest_at_or_before("AAPL", feb + timedelta(days=1))["id"] == second["id"]
    assert repo.get_latest_at_or_before("AAPL", jan - timedelta(seconds=1)) is None
    assert second["payload"]["feature_buckets"]["valuation"] == "medium"
    assert second["warnings"] == ["price target unavailable"]


def test_monitored_ticker_discovery_merges_watchlists_and_active_broker_exposure() -> None:
    from trade_proposer_app.services.monitored_tickers import MonitoredTickerService

    session = create_session()
    watchlists = WatchlistRepository(session)
    positions = BrokerPositionRepository(session)
    watchlists.create(
        "Core", ["aapl", "MSFT", ""], default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True
    )
    positions.create(
        BrokerPosition(
            ticker="AAPL",
            broker_order_execution_id=1,
            recommendation_plan_id=1,
            action="long",
            side="long",
            status="closing",
            quantity=1,
            current_quantity=1,
            entry_avg_price=100.0,
        )
    )
    positions.create(
        BrokerPosition(
            ticker="NVDA",
            broker_order_execution_id=2,
            recommendation_plan_id=2,
            action="long",
            side="long",
            status="open",
            quantity=1,
            current_quantity=1,
            entry_avg_price=100.0,
        )
    )

    result = MonitoredTickerService(session).list_monitored_tickers_with_provenance()

    assert [item["ticker"] for item in result] == ["AAPL", "MSFT", "NVDA"]
    provenance = {item["ticker"]: set(item["provenance"]) for item in result}
    assert provenance["AAPL"] == {"watchlist", "broker_position"}
    assert provenance["MSFT"] == {"watchlist"}
    assert provenance["NVDA"] == {"broker_position"}


def test_fundamental_analysis_service_normalizes_provider_payload_without_positive_confidence() -> (
    None
):
    from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService

    provider = SimpleNamespace(fetch=lambda ticker, as_of=None: _full_provider_payload())
    service = FundamentalAnalysisService(provider=provider)
    as_of = datetime(2026, 4, 1, tzinfo=timezone.utc)

    snapshot = service.analyze("aapl", as_of=as_of)

    assert snapshot.ticker == "AAPL"
    assert snapshot.as_of == as_of
    assert snapshot.coverage_status == "ok"
    assert snapshot.payload["business_profile"]["sector"] == "Technology"
    assert snapshot.payload["valuation"]["forward_pe"] == 27.4
    assert snapshot.payload["profitability_quality"]["operating_margin"] == 0.31
    assert snapshot.payload["growth"]["revenue_growth"] == 0.06
    assert snapshot.payload["analyst_context"]["recommendation_key"] == "buy"
    assert snapshot.payload["feature_buckets"]["valuation"] in {
        "cheap",
        "medium",
        "expensive",
        "extreme_expensive",
        "unknown",
    }
    valuation_context = snapshot.payload["valuation_context"]
    assert valuation_context["schema_version"] == "fundamental-valuation-v1"
    assert valuation_context["mispricing_signal"] in {
        "undervalued",
        "fairly_valued",
        "overvalued",
        "extreme_overvalued",
        "unclear",
        "unknown",
    }
    assert valuation_context["directional_support"]["long"] in {
        "supportive",
        "neutral",
        "caution",
        "contradictory",
        "unknown",
    }
    assert valuation_context["confidence_contribution"]["positive_boost"] == 0.0
    assert snapshot.payload["feature_buckets"]["event_regime"] in {
        "none_known",
        "pre_event",
        "event_week",
        "post_event",
        "stale_event",
        "unknown",
    }
    assert snapshot.payload.get("confidence_contribution", {}).get("positive_boost", 0.0) == 0.0


def test_fundamental_analysis_service_marks_sparse_payloads_degraded_and_unknown() -> None:
    from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService

    provider = SimpleNamespace(fetch=lambda ticker, as_of=None: {"info": {"marketCap": None}})
    snapshot = FundamentalAnalysisService(provider=provider).analyze(
        "BAE.L", as_of=datetime(2026, 4, 1, tzinfo=timezone.utc)
    )

    assert snapshot.coverage_status != "ok"
    assert snapshot.payload["valuation_context"]["mispricing_signal"] == "unknown"
    assert snapshot.payload["feature_buckets"]["valuation"] == "unknown"
    assert "fundamental provider returned sparse data" in snapshot.warnings


def test_fundamental_analysis_service_classifies_under_and_over_valuation() -> None:
    from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService

    cheap_payload = _full_provider_payload()
    cheap_info = cheap_payload["info"]
    cheap_info["forwardPE"] = 12.0
    cheap_info["revenueGrowth"] = 0.22
    cheap_info["operatingMargins"] = 0.32
    cheap_info["debtToEquity"] = 25.0
    cheap_info["targetMeanPrice"] = 130.0
    cheap_info["currentPrice"] = 100.0

    expensive_payload = _full_provider_payload()
    expensive_info = expensive_payload["info"]
    expensive_info["forwardPE"] = 70.0
    expensive_info["revenueGrowth"] = -0.03
    expensive_info["operatingMargins"] = 0.04
    expensive_info["debtToEquity"] = 250.0
    expensive_info["targetMeanPrice"] = 80.0
    expensive_info["currentPrice"] = 100.0

    cheap_snapshot = FundamentalAnalysisService(
        provider=SimpleNamespace(fetch=lambda ticker, as_of=None: cheap_payload)
    ).analyze("VALUE", as_of=datetime(2026, 4, 1, tzinfo=timezone.utc))
    expensive_snapshot = FundamentalAnalysisService(
        provider=SimpleNamespace(fetch=lambda ticker, as_of=None: expensive_payload)
    ).analyze("HYPE", as_of=datetime(2026, 4, 1, tzinfo=timezone.utc))

    cheap_context = cheap_snapshot.payload["valuation_context"]
    expensive_context = expensive_snapshot.payload["valuation_context"]
    assert cheap_context["mispricing_signal"] == "undervalued"
    assert cheap_context["directional_support"]["long"] == "supportive"
    assert expensive_context["mispricing_signal"] == "extreme_overvalued"
    assert expensive_context["directional_support"]["long"] == "contradictory"


def test_fundamental_analysis_service_classifies_event_windows() -> None:
    from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService

    service = FundamentalAnalysisService(
        provider=SimpleNamespace(fetch=lambda ticker, as_of=None: _full_provider_payload())
    )
    earnings_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
    payload = {"event_calendar": {"next_earnings_at": earnings_at.isoformat()}}

    assert service.event_regime(payload, as_of=earnings_at - timedelta(days=10)) == "pre_event"
    assert service.event_regime(payload, as_of=earnings_at - timedelta(days=2)) == "event_week"
    assert service.event_regime(payload, as_of=earnings_at + timedelta(days=1)) == "event_week"
    assert service.event_regime(payload, as_of=earnings_at + timedelta(days=7)) == "post_event"


def test_fundamental_refresh_job_refreshes_due_and_event_window_tickers_only() -> None:
    from trade_proposer_app.repositories.fundamental_analysis_snapshots import (
        FundamentalAnalysisSnapshotRepository,
    )
    from trade_proposer_app.services.fundamental_analysis_refresh import (
        FundamentalAnalysisRefreshService,
    )

    session = create_session()
    watchlists = WatchlistRepository(session)
    watchlists.create(
        "Core",
        ["AAPL", "MSFT", "NVDA"],
        default_horizon=StrategyHorizon.ONE_WEEK,
        allow_shorts=True,
    )
    repo = FundamentalAnalysisSnapshotRepository(session)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    repo.create_snapshot(
        ticker="MSFT",
        as_of=now - timedelta(days=5),
        source_set=["fake"],
        coverage_status="ok",
        freshness_status="fresh",
        payload={"feature_buckets": {"event_regime": "none_known"}},
        warnings=[],
        missing_inputs=[],
    )
    repo.create_snapshot(
        ticker="NVDA",
        as_of=now - timedelta(days=5),
        source_set=["fake"],
        coverage_status="ok",
        freshness_status="fresh",
        payload={
            "event_calendar": {"next_earnings_at": (now + timedelta(days=2)).isoformat()},
            "feature_buckets": {"event_regime": "event_week"},
        },
        warnings=[],
        missing_inputs=[],
    )

    refreshed: list[str] = []
    analysis_service = SimpleNamespace(
        refresh_ticker=lambda ticker, **kwargs: (
            refreshed.append(ticker) or {"ticker": ticker, "coverage_status": "ok"}
        )
    )
    summary = FundamentalAnalysisRefreshService(
        session, analysis_service=analysis_service
    ).refresh_due_monitored_tickers(as_of=now, max_tickers=10)

    assert refreshed == ["AAPL", "NVDA"]
    assert summary["monitored_count"] == 3
    assert summary["refreshed_count"] == 2
    assert summary["skipped_fresh_count"] == 1


def test_plan_generation_uses_point_in_time_fundamental_snapshot_without_boosting() -> None:
    from trade_proposer_app.repositories.fundamental_analysis_snapshots import (
        FundamentalAnalysisSnapshotRepository,
    )
    from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService

    session = create_session()
    repo = FundamentalAnalysisSnapshotRepository(session)
    plan_time = datetime(2026, 3, 10, tzinfo=timezone.utc)
    prior = repo.create_snapshot(
        ticker="AAPL",
        as_of=plan_time - timedelta(days=1),
        source_set=["fake"],
        coverage_status="ok",
        freshness_status="fresh",
        payload={
            "feature_buckets": {"event_regime": "pre_event", "valuation": "expensive"},
            "valuation_context": {
                "schema_version": "fundamental-valuation-v1",
                "mispricing_signal": "overvalued",
                "directional_support": {"long": "caution", "short": "supportive"},
                "reasons": ["valuation is rich"],
            },
        },
        warnings=["earnings inside holding window"],
        missing_inputs=[],
    )
    future = repo.create_snapshot(
        ticker="AAPL",
        as_of=plan_time + timedelta(days=1),
        source_set=["fake"],
        coverage_status="ok",
        freshness_status="fresh",
        payload={"feature_buckets": {"event_regime": "post_event", "valuation": "medium"}},
        warnings=[],
        missing_inputs=[],
    )

    service = TickerDeepAnalysisService(SimpleNamespace(), fundamental_snapshots=repo)
    context = service._apply_fundamental_snapshot(
        {"confidence": 70.0}, "AAPL", as_of=plan_time, horizon=StrategyHorizon.ONE_WEEK
    )

    assert context["fundamental_snapshot"]["id"] == prior["id"]
    assert context["fundamental_snapshot"]["id"] != future["id"]
    assert context["fundamental_feature_buckets"]["event_regime"] == "pre_event"
    assert context["fundamental_valuation_context"]["mispricing_signal"] == "overvalued"
    assert context["fundamental_valuation_context"]["directional_support"]["long"] == "caution"
    assert "fundamental: earnings inside holding window" in context["problems"]
    assert context["confidence"] == 70.0


def test_fundamental_validation_slices_report_sparse_counts_and_effective_outcomes() -> None:
    from trade_proposer_app.services.fundamental_validation_slices import (
        FundamentalValidationSliceService,
    )

    session = create_session()
    service = FundamentalValidationSliceService(session)

    report = service.summarize(limit=5000)

    expected_slice_names = {
        "event_regime",
        "earnings_window",
        "analyst_action_bucket",
        "valuation_bucket",
        "profitability_quality_bucket",
        "growth_bucket",
        "balance_sheet_risk_bucket",
        "setup_family_event_regime",
        "mispricing_signal",
        "directional_support",
        "setup_family_mispricing_signal",
    }
    assert expected_slice_names.issubset(set(report["slices"].keys()))
    for slice_payload in report["slices"].values():
        assert "resolved_count" in slice_payload
        assert "effective_win_rate_percent" in slice_payload
        assert "sparse_evidence" in slice_payload
        assert slice_payload["uses_effective_outcomes"] is True


def test_fundamental_refresh_job_type_is_schedulable() -> None:
    session = create_session()
    jobs = JobRepository(session)
    runs = RunRepository(session)

    job = jobs.create(
        "Auto: Fundamental Analysis Weekend Batch 1",
        [],
        "15 06 * * SAT",
        job_type=JobType.FUNDAMENTAL_ANALYSIS_REFRESH,
        enabled=True,
    )
    run = runs.enqueue(job.id or 0)

    assert job.job_type == JobType.FUNDAMENTAL_ANALYSIS_REFRESH
    assert run.job_id == job.id


def test_default_fundamental_refresh_jobs_are_spread_across_weekend() -> None:
    from trade_proposer_app.services.default_jobs import ensure_default_fundamental_analysis_job

    session = create_session()

    spec = ensure_default_fundamental_analysis_job(session)
    jobs = JobRepository(session).list_all()
    fundamental_jobs = [job for job in jobs if job.job_type == JobType.FUNDAMENTAL_ANALYSIS_REFRESH]

    assert len(spec["jobs"]) == 8
    assert len(fundamental_jobs) == 8
    assert [job.name for job in fundamental_jobs] == [
        f"Auto: Fundamental Analysis Weekend Batch {index}" for index in range(1, 9)
    ]
    assert [job.cron for job in fundamental_jobs] == [
        "15 06 * * SAT",
        "15 09 * * SAT",
        "15 12 * * SAT",
        "15 15 * * SAT",
        "15 06 * * SUN",
        "15 09 * * SUN",
        "15 12 * * SUN",
        "15 15 * * SUN",
    ]
    assert all(
        "weekend" in str(item["schedule_rationale"]).lower()
        or "batch" in str(item["schedule_rationale"]).lower()
        for item in spec["jobs"]
    )


def test_default_fundamental_refresh_jobs_migrate_legacy_monthly_job() -> None:
    from trade_proposer_app.services.default_jobs import ensure_default_fundamental_analysis_job

    session = create_session()
    legacy = JobRepository(session).create(
        "Auto: Fundamental Analysis Monthly",
        [],
        "15 07 1 * *",
        job_type=JobType.FUNDAMENTAL_ANALYSIS_REFRESH,
        enabled=True,
    )

    ensure_default_fundamental_analysis_job(session)
    jobs = JobRepository(session).list_all()
    fundamental_jobs = [job for job in jobs if job.job_type == JobType.FUNDAMENTAL_ANALYSIS_REFRESH]

    assert len(fundamental_jobs) == 8
    assert fundamental_jobs[0].id == legacy.id
    assert fundamental_jobs[0].name == "Auto: Fundamental Analysis Weekend Batch 1"
    assert fundamental_jobs[0].cron == "15 06 * * SAT"
