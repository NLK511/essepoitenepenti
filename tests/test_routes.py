import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import (
    AppPreflightReport,
    EvaluationRunResult,
    IndustryContextSnapshot,
    MacroContextSnapshot,
    PreflightCheck,
    RecommendationPlan,
    RecommendationPlanOutcome,
    Run,
    TickerSignalSnapshot,
)
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository


class StubAppPreflightService:
    def run(self) -> AppPreflightReport:
        return AppPreflightReport(
            status="ok",
            checked_at=datetime.now(timezone.utc),
            engine="internal_price_pipeline",
            checks=[
                PreflightCheck(name="module:pandas", status="ok", message="pandas importable"),
                PreflightCheck(name="module:yfinance", status="ok", message="yfinance importable"),
                PreflightCheck(name="weights_file", status="ok", message="weights file available"),
            ],
        )


class RouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._previous_single_user_auth_enabled = settings.single_user_auth_enabled
        self._previous_single_user_auth_token = settings.single_user_auth_token
        self._previous_single_user_auth_allowlist_paths = settings.single_user_auth_allowlist_paths
        self._previous_single_user_auth_username = settings.single_user_auth_username
        self._previous_single_user_auth_password = settings.single_user_auth_password
        settings.single_user_auth_enabled = False

        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)
        self.prototype_root = tempfile.TemporaryDirectory()
        self.original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = self.prototype_root.name

        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db_session] = override_db_session
        self.health_preflight_patcher = patch(
            "trade_proposer_app.api.routes.health.AppPreflightService",
            StubAppPreflightService,
        )
        self.health_preflight_patcher.start()

    async def asyncTearDown(self) -> None:
        self.health_preflight_patcher.stop()
        app.dependency_overrides.clear()
        settings.prototype_repo_path = self.original_prototype_repo_path
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        settings.single_user_auth_token = self._previous_single_user_auth_token
        settings.single_user_auth_allowlist_paths = self._previous_single_user_auth_allowlist_paths
        settings.single_user_auth_username = self._previous_single_user_auth_username
        settings.single_user_auth_password = self._previous_single_user_auth_password
        self.prototype_root.cleanup()

    def seed_run_with_diagnostics(self) -> int:
        session = Session(bind=self.engine)
        try:
            jobs = JobRepository(session)
            runs = RunRepository(session)
            job = jobs.create("Seeded", ["AAPL"], None)
            run = runs.enqueue(job.id or 0)
            claimed = runs.claim_next_queued_run()
            assert claimed is not None
            runs.update_status(
                run.id or 0,
                "completed_with_warnings",
                timing={
                    "queue_wait_seconds": 0.01,
                    "resolve_tickers_seconds": 0.02,
                    "recommendation_generation_seconds": 0.03,
                    "persistence_seconds": 0.01,
                    "finalize_seconds": 0.01,
                    "total_execution_seconds": 0.08,
                    "ticker_generation": [{"ticker": "AAPL", "duration_seconds": 0.03}],
                },
            )
            RecommendationPlanRepository(session).create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon="1w",
                    action="long",
                    confidence_percent=81.0,
                    entry_price_low=101.0,
                    entry_price_high=102.0,
                    stop_loss=97.0,
                    take_profit=111.0,
                    holding_period_days=5,
                    risk_reward_ratio=1.8,
                    thesis_summary="Sentiment Bullish · Above SMA200 · RSI 58.0",
                    rationale_summary="Seeded run detail plan",
                    warnings=["summary timeout", "feed timeout"],
                    signal_breakdown={"setup_family": "continuation"},
                    evidence_summary={"provider_errors": ["feed timeout"]},
                    run_id=run.id,
                    job_id=job.id,
                )
            )
            return run.id or 0
        finally:
            session.close()

    def seed_failed_run(self) -> int:
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).create("Failed", ["AAPL"], None)
            run = RunRepository(session).enqueue(job.id or 0)
            claimed = RunRepository(session).claim_next_queued_run()
            assert claimed is not None
            RunRepository(session).update_status(
                run.id or 0,
                "failed",
                error_message="prototype dependency missing: No module named 'yfinance'",
                timing={
                    "queue_wait_seconds": 0.0,
                    "resolve_tickers_seconds": 0.01,
                    "recommendation_generation_seconds": 0.05,
                    "persistence_seconds": 0.0,
                    "finalize_seconds": 0.01,
                    "total_execution_seconds": 0.07,
                    "ticker_generation": [],
                },
            )
            return run.id or 0
        finally:
            session.close()

    def seed_context_and_recommendation_plan_data(self, *, run_id: int | None = None) -> None:
        session = Session(bind=self.engine)
        try:
            context_repository = ContextSnapshotRepository(session)
            ticker_signal = context_repository.create_ticker_signal_snapshot(
                TickerSignalSnapshot(
                    ticker="AAPL",
                    horizon="1w",
                    direction="long",
                    swing_probability_percent=66.0,
                    confidence_percent=71.0,
                    attention_score=83.0,
                    diagnostics={"mode": "deep_analysis"},
                    run_id=run_id,
                )
            )
            context_repository.create_macro_context_snapshot(
                MacroContextSnapshot(
                    summary_text="Fed and yields remain the dominant macro themes.",
                    saliency_score=0.81,
                    confidence_percent=75.0,
                    active_themes=[{"key": "fed_policy"}],
                    regime_tags=["rates_sensitive"],
                    run_id=run_id,
                )
            )
            context_repository.create_industry_context_snapshot(
                IndustryContextSnapshot(
                    industry_key="consumer_electronics",
                    industry_label="Consumer Electronics",
                    summary_text="AI device enthusiasm supports the group.",
                    direction="positive",
                    saliency_score=0.73,
                    confidence_percent=69.0,
                    run_id=run_id,
                )
            )
            plan = RecommendationPlanRepository(session).create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon="1w",
                    action="long",
                    confidence_percent=71.0,
                    entry_price_low=201.0,
                    entry_price_high=203.0,
                    stop_loss=196.5,
                    take_profit=210.0,
                    holding_period_days=5,
                    risk_reward_ratio=1.6,
                    thesis_summary="Macro and industry conditions remain supportive.",
                    rationale_summary="Signal stack aligns bullish.",
                    ticker_signal_snapshot_id=ticker_signal.id,
                    signal_breakdown={
                        "technical_setup": 0.77,
                        "setup_family": "continuation",
                        "transmission_summary": {
                            "context_bias": "tailwind",
                            "transmission_tags": ["macro_dominant", "catalyst_active"],
                        },
                    },
                    run_id=run_id,
                )
            )
            RecommendationOutcomeRepository(session).upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    ticker="AAPL",
                    action="long",
                    outcome="win",
                    status="resolved",
                    horizon_return_1d=1.2,
                    horizon_return_3d=2.8,
                    horizon_return_5d=3.4,
                    max_favorable_excursion=4.1,
                    max_adverse_excursion=0.9,
                    confidence_bucket="65_to_79",
                    setup_family="continuation",
                    notes="Take profit reached before stop.",
                    run_id=run_id,
                )
            )
        finally:
            session.close()

    def seed_sentiment_snapshots(self) -> list[int]:
        session = Session(bind=self.engine)
        try:
            repository = SentimentSnapshotRepository(session)
            macro = repository.create_snapshot(
                scope="macro",
                subject_key="global_macro",
                subject_label="Global Macro",
                score=-0.18,
                label="NEGATIVE",
                computed_at=datetime(2026, 3, 22, 6, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
                coverage={"social_count": 4},
                source_breakdown={"social": {"score": -0.18, "item_count": 4}},
                drivers=["rates rising"],
                diagnostics={"warnings": ["snapshot fresh"]},
                summary_text="Global Macro remains negative overall. Compared with the prior snapshot, the backdrop is slightly softer; the main update is rates rising.",
                job_id=1,
                run_id=2,
            )
            industry = repository.create_snapshot(
                scope="industry",
                subject_key="consumer_electronics",
                subject_label="Consumer Electronics",
                score=0.27,
                label="POSITIVE",
                computed_at=datetime(2026, 3, 22, 7, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 3, 22, 15, 0, tzinfo=timezone.utc),
                coverage={"social_count": 6},
                source_breakdown={"social": {"score": 0.27, "item_count": 6}},
                drivers=["iphone demand stable"],
                diagnostics={"warnings": []},
                summary_text="Consumer Electronics remains positive overall. Compared with the prior snapshot, the backdrop is broadly unchanged; the main update is iphone demand stable.",
                job_id=3,
                run_id=4,
            )
            return [macro.id or 0, industry.id or 0]
        finally:
            session.close()

    def seed_prototype_trade_log(self) -> None:
        db_path = Path(self.prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data" / "trade_log.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    ticker TEXT,
                    direction TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    sentiment REAL,
                    rsi REAL,
                    price_above_sma50 INTEGER,
                    price_above_sma200 INTEGER,
                    atr_pct REAL,
                    confidence REAL,
                    status TEXT DEFAULT 'PENDING',
                    close_timestamp TEXT,
                    duration_days REAL,
                    analysis_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO trades (
                    timestamp, ticker, direction, entry_price, stop_loss, take_profit,
                    sentiment, rsi, price_above_sma50, price_above_sma200, atr_pct,
                    confidence, status, close_timestamp, duration_days, analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "2026-03-01 09:30:00",
                        "AAPL",
                        "LONG",
                        100.0,
                        95.0,
                        110.0,
                        0.2,
                        55.0,
                        1,
                        1,
                        2.5,
                        80.0,
                        "WIN",
                        "2026-03-05 10:00:00",
                        4.02,
                        '{"aggregations": {"direction_score": 0.72}}',
                    ),
                    (
                        "2026-03-08 09:30:00",
                        "AAPL",
                        "SHORT",
                        104.0,
                        108.0,
                        96.0,
                        -0.1,
                        48.0,
                        0,
                        1,
                        2.2,
                        62.0,
                        "LOSS",
                        "2026-03-10 11:00:00",
                        2.06,
                        '{"aggregations": {"direction_score": 0.41}}',
                    ),
                    (
                        "2026-03-11 09:30:00",
                        "AAPL",
                        "LONG",
                        102.0,
                        98.0,
                        112.0,
                        0.15,
                        53.0,
                        1,
                        1,
                        2.1,
                        70.0,
                        "PENDING",
                        None,
                        None,
                        '{"aggregations": {"direction_score": 0.65}}',
                    ),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    async def test_health_endpoint(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["preflight"]["status"], "warning")
        self.assertEqual(payload["sentiment_snapshots"]["macro"]["status"], "warning")
        self.assertEqual(payload["sentiment_snapshots"]["industry"]["status"], "warning")

    async def test_preflight_health_endpoint(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/health/preflight")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["engine"], "internal_price_pipeline")
        self.assertTrue(any(check["name"] == "module:pandas" for check in payload["checks"]))
        self.assertTrue(any(check["name"] == "sentiment_snapshot:macro" for check in payload["checks"]))

    async def test_legacy_prototype_health_route(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/health/prototype")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["engine"], "internal_price_pipeline")
        self.assertTrue(any(check["name"] == "weights_file" for check in payload["checks"]))

    async def test_spa_shell_routes_render(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for path in ("/", "/watchlists", "/jobs", "/history", "/debugger", "/settings", "/docs", "/sentiment", "/sentiment/1", "/runs/1", "/recommendation-plans", "/tickers/AAPL"):
                response = await client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("<title>Trade Proposer App</title>", response.text)

            legacy_redirect = await client.get("/recommendations/1", follow_redirects=False)
            self.assertEqual(legacy_redirect.status_code, 307)
            self.assertEqual(legacy_redirect.headers["location"], "/jobs/recommendation-plans")

    async def test_docs_api_lists_markdown_documents(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/docs")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(document["slug"] == "readme" for document in payload["documents"]))
        self.assertTrue(any(document["slug"] == "raw-details-reference" for document in payload["documents"]))
        self.assertTrue(any(document["slug"] == "redesign-readme" for document in payload["documents"]))
        methodology = next(document for document in payload["documents"] if document["slug"] == "recommendation-methodology")
        self.assertTrue(any("Pipeline overview" in section["title"] for section in methodology["sections"]))
        self.assertTrue(any("App-native independence" in section["title"] for section in methodology["sections"]))

    async def test_create_watchlist_and_list_via_api(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/watchlists",
                data={
                    "name": "Core Tech",
                    "tickers": "AAPL,MSFT,AAPL",
                    "description": "US tech swing basket",
                    "region": "US",
                    "exchange": "NASDAQ",
                    "timezone": "America/New_York",
                    "default_horizon": "1d",
                    "allow_shorts": "false",
                    "optimize_evaluation_timing": "true",
                },
            )
            listed = await client.get("/api/watchlists")

        self.assertEqual(created.status_code, 200)
        created_payload = created.json()
        self.assertEqual(created_payload["name"], "Core Tech")
        self.assertEqual(created_payload["description"], "US tech swing basket")
        self.assertEqual(created_payload["region"], "US")
        self.assertEqual(created_payload["exchange"], "NASDAQ")
        self.assertEqual(created_payload["timezone"], "America/New_York")
        self.assertEqual(created_payload["default_horizon"], "1d")
        self.assertFalse(created_payload["allow_shorts"])
        self.assertTrue(created_payload["optimize_evaluation_timing"])
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["tickers"], ["AAPL", "MSFT"])

    async def test_create_watchlist_rejects_ticker_already_used_by_another_watchlist(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = await client.post("/api/watchlists", data={"name": "Core Tech", "tickers": "AAPL,MSFT"})
            duplicate = await client.post("/api/watchlists", data={"name": "More Tech", "tickers": "NVDA,AAPL"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("ticker already assigned to another watchlist", duplicate.text)
        self.assertIn("AAPL", duplicate.text)

    async def test_create_watchlist_rejects_invalid_default_horizon(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/watchlists",
                data={"name": "Core Tech", "tickers": "AAPL,MSFT", "default_horizon": "3d"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("default_horizon must be one of: 1d, 1w, 1m", response.text)

    async def test_get_watchlist_policy_via_api(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/watchlists",
                data={
                    "name": "US Swing",
                    "tickers": "AAPL,MSFT",
                    "timezone": "America/New_York",
                    "default_horizon": "1d",
                    "optimize_evaluation_timing": "true",
                },
            )
            self.assertEqual(created.status_code, 200)
            watchlist_id = created.json()["id"]
            policy = await client.get(f"/api/watchlists/{watchlist_id}/policy")
            policies = await client.get("/api/watchlists/policies")

        self.assertEqual(policy.status_code, 200)
        payload = policy.json()
        self.assertEqual(payload["schedule_source"], "watchlist_optimized")
        self.assertEqual(payload["schedule_timezone"], "America/New_York")
        self.assertEqual(payload["primary_cron"], "20 9 * * MON-FRI")
        self.assertEqual(payload["shortlist_strategy"], "cheap_scan_then_deep_analysis")
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(policies.status_code, 200)
        self.assertEqual(len(policies.json()), 1)
        self.assertEqual(policies.json()[0]["watchlist_id"], watchlist_id)

    async def test_create_job_and_enqueue_run_via_api(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/jobs",
                data={"name": "Morning", "tickers": "NVDA,TSLA", "schedule": ""},
            )
            self.assertEqual(created.status_code, 200)
            job_id = created.json()["id"]

            queued = await client.post(f"/api/jobs/{job_id}/execute")
            duplicate = await client.post(f"/api/jobs/{job_id}/execute")
            runs = await client.get("/api/runs")

        self.assertEqual(queued.status_code, 200)
        self.assertEqual(queued.json()["status"], "queued")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["id"], queued.json()["id"])
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(len(runs.json()), 1)
        self.assertEqual(runs.json()[0]["status"], "queued")

    async def test_create_job_with_empty_watchlist_value_is_valid(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/jobs",
                data={"name": "Manual Only", "tickers": "AAPL,MSFT", "watchlist_id": "", "schedule": ""},
            )

        self.assertEqual(created.status_code, 200)
        payload = created.json()
        self.assertEqual(payload["watchlist_id"], None)
        self.assertEqual(payload["tickers"], ["AAPL", "MSFT"])
        self.assertEqual(payload["job_type"], JobType.PROPOSAL_GENERATION.value)

    async def test_create_non_proposal_jobs_via_api_and_reject_invalid_job_type(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            evaluation = await client.post(
                "/api/jobs",
                data={
                    "name": "Daily Evaluation",
                    "job_type": JobType.RECOMMENDATION_EVALUATION.value,
                    "tickers": "",
                    "watchlist_id": "",
                    "schedule": "0 18 * * *",
                },
            )
            optimization = await client.post(
                "/api/jobs",
                data={
                    "name": "Weekly Optimization",
                    "job_type": JobType.WEIGHT_OPTIMIZATION.value,
                    "tickers": "",
                    "watchlist_id": "",
                    "schedule": "0 2 * * 0",
                },
            )
            invalid = await client.post(
                "/api/jobs",
                data={
                    "name": "Bad Type",
                    "job_type": "bad_type",
                    "tickers": "",
                    "schedule": "",
                },
            )

        self.assertEqual(evaluation.status_code, 200)
        self.assertEqual(evaluation.json()["job_type"], JobType.RECOMMENDATION_EVALUATION.value)
        self.assertEqual(evaluation.json()["tickers"], [])
        self.assertEqual(optimization.status_code, 200)
        self.assertEqual(optimization.json()["job_type"], JobType.WEIGHT_OPTIMIZATION.value)
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("invalid job_type", invalid.text)

    async def test_create_non_proposal_job_rejects_ticker_source_via_api(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            invalid = await client.post(
                "/api/jobs",
                data={
                    "name": "Invalid Evaluation",
                    "job_type": JobType.RECOMMENDATION_EVALUATION.value,
                    "tickers": "AAPL",
                    "schedule": "",
                },
            )

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("must not define tickers or a watchlist source", invalid.text)

    async def test_manual_execute_preserves_non_proposal_job_type_on_run(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/jobs",
                data={
                    "name": "Manual Evaluation",
                    "job_type": JobType.RECOMMENDATION_EVALUATION.value,
                    "tickers": "",
                    "schedule": "",
                },
            )
            self.assertEqual(created.status_code, 200)
            job_id = created.json()["id"]
            queued = await client.post(f"/api/jobs/{job_id}/execute")

        self.assertEqual(queued.status_code, 200)
        self.assertEqual(queued.json()["job_type"], JobType.RECOMMENDATION_EVALUATION.value)
        self.assertEqual(queued.json()["status"], "queued")

    async def test_update_and_delete_scheduled_job_via_api(self) -> None:
        session = Session(bind=self.engine)
        try:
            watchlist = WatchlistRepository(session).create("Core Tech", ["AAPL", "MSFT"])
            job = JobRepository(session).create("Morning Schedule", ["NVDA"], "30 9 * * 1,2,3,4,5")
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            updated = await client.post(
                f"/api/jobs/{job.id}",
                data={
                    "name": "Updated Schedule",
                    "tickers": "",
                    "watchlist_id": str(watchlist.id),
                    "schedule": "0 10 * * 1,2,3,4,5",
                    "enabled": "false",
                },
            )
            listed_after_update = await client.get("/api/jobs")
            deleted = await client.post(f"/api/jobs/{job.id}/delete")
            listed_after_delete = await client.get("/api/jobs")

        self.assertEqual(updated.status_code, 200)
        updated_payload = updated.json()
        self.assertEqual(updated_payload["name"], "Updated Schedule")
        self.assertEqual(updated_payload["watchlist_id"], watchlist.id)
        self.assertEqual(updated_payload["job_type"], JobType.PROPOSAL_GENERATION.value)
        self.assertEqual(updated_payload["cron"], "0 10 * * 1,2,3,4,5")
        self.assertFalse(updated_payload["enabled"])

        self.assertEqual(listed_after_update.status_code, 200)
        self.assertEqual(len(listed_after_update.json()), 1)
        self.assertEqual(listed_after_update.json()[0]["name"], "Updated Schedule")

        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(listed_after_delete.status_code, 200)
        self.assertEqual(listed_after_delete.json(), [])

    async def test_delete_job_with_existing_run_history_via_api(self) -> None:
        session = Session(bind=self.engine)
        try:
            jobs = JobRepository(session)
            runs = RunRepository(session)
            job = jobs.create("Job With History", ["AAPL"], None)
            run = runs.enqueue(job.id or 0)
            claimed = runs.claim_next_queued_run()
            assert claimed is not None
            runs.update_status(run.id or 0, "completed")
            RecommendationPlanRepository(session).create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon="1w",
                    action="long",
                    confidence_percent=80.0,
                    entry_price_low=100.0,
                    entry_price_high=101.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    holding_period_days=5,
                    risk_reward_ratio=2.0,
                    thesis_summary="Seeded historical plan",
                    rationale_summary="Job delete cleanup coverage",
                    run_id=run.id,
                    job_id=job.id,
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            deleted = await client.post(f"/api/jobs/{job.id}/delete")
            jobs_after_delete = await client.get("/api/jobs")
            runs_after_delete = await client.get("/api/runs")
            history_after_delete = await client.get("/api/history")

        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(jobs_after_delete.status_code, 200)
        self.assertEqual(jobs_after_delete.json(), [])
        self.assertEqual(runs_after_delete.status_code, 200)
        self.assertEqual(runs_after_delete.json(), [])
        self.assertEqual(history_after_delete.status_code, 404)

    async def test_create_job_requires_exactly_one_source_and_supports_watchlist(self) -> None:
        session = Session(bind=self.engine)
        try:
            watchlist = WatchlistRepository(session).create("Core Tech", ["AAPL", "MSFT"])
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            invalid = await client.post(
                "/api/jobs",
                data={"name": "Invalid", "tickers": "AAPL", "watchlist_id": str(watchlist.id), "schedule": ""},
            )
            watchlist_based = await client.post(
                "/api/jobs",
                data={"name": "From Watchlist", "tickers": "", "watchlist_id": str(watchlist.id), "schedule": ""},
            )

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("exactly one source", invalid.text)
        self.assertEqual(watchlist_based.status_code, 200)
        self.assertEqual(watchlist_based.json()["watchlist_id"], watchlist.id)

    async def test_create_job_rejects_invalid_schedule_via_api(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            invalid = await client.post(
                "/api/jobs",
                data={"name": "Invalid Schedule", "tickers": "AAPL", "schedule": "0 30 9 * * 1-5"},
            )

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("invalid schedule", invalid.text)

    async def test_create_watchlist_from_existing_job_via_api(self) -> None:
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).create("Manual Job", ["NVDA", "TSLA"], None)
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(f"/api/jobs/{job.id}/watchlist")
            listed = await client.get("/api/watchlists")

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["name"], "Manual Job watchlist")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["tickers"], ["NVDA", "TSLA"])

    async def test_create_watchlist_from_non_proposal_job_is_rejected(self) -> None:
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).create(
                "Evaluation Job",
                [],
                "0 18 * * *",
                job_type=JobType.RECOMMENDATION_EVALUATION,
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(f"/api/jobs/{job.id}/watchlist")

        self.assertEqual(created.status_code, 400)
        self.assertIn("watchlists can only be created from proposal_generation jobs", created.text)

    async def test_dashboard_and_run_detail_render_redesign_data_without_legacy_history_api(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            dashboard = await client.get("/api/dashboard")
            history = await client.get("/api/history")
            run_detail = await client.get(f"/api/runs/{run_id}")

        self.assertEqual(dashboard.status_code, 200)
        dashboard_payload = dashboard.json()
        self.assertEqual(len(dashboard_payload["latest_runs"]), 1)
        self.assertEqual(len(dashboard_payload["recommendation_plans"]), 1)

        self.assertEqual(history.status_code, 404)

        self.assertEqual(run_detail.status_code, 200)
        detail_payload = run_detail.json()
        self.assertEqual(detail_payload["run"]["id"], run_id)
        self.assertNotIn("outputs", detail_payload)
        self.assertEqual(detail_payload["recommendation_plans"][0]["ticker"], "AAPL")
        self.assertEqual(detail_payload["recommendation_plans"][0]["warnings"], ["summary timeout", "feed timeout"])
        self.assertIn("ticker_generation", detail_payload["run"]["timing_json"])
        self.assertEqual(detail_payload["macro_context_snapshots"], [])
        self.assertEqual(detail_payload["industry_context_snapshots"], [])
        self.assertEqual(detail_payload["ticker_signal_snapshots"], [])
        self.assertEqual(len(detail_payload["recommendation_plans"]), 1)

    async def test_delete_run_via_api(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            deleted = await client.delete(f"/api/runs/{run_id}")
            runs_after_delete = await client.get("/api/runs")
            history_after_delete = await client.get("/api/history")
            run_detail = await client.get(f"/api/runs/{run_id}")

        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(runs_after_delete.status_code, 200)
        self.assertEqual(runs_after_delete.json(), [])
        self.assertEqual(history_after_delete.status_code, 404)
        self.assertEqual(run_detail.status_code, 404)
        self.assertEqual(run_detail.json()["detail"], f"Run {run_id} not found")

    async def test_delete_active_run_is_rejected(self) -> None:
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).create("Queued Job", ["AAPL"], None)
            run = RunRepository(session).enqueue(job.id or 0)
            run_id = run.id or 0
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.delete(f"/api/runs/{run_id}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("queued or running", response.text)

    async def test_legacy_recommendation_evaluation_endpoints_are_retired(self) -> None:
        self.seed_run_with_diagnostics()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            global_response = await client.post("/api/recommendations/evaluate")
            scoped_response = await client.post("/api/recommendations/1/evaluate")

        self.assertIn(global_response.status_code, {404, 405})
        self.assertIn(scoped_response.status_code, {404, 405})

    async def test_dashboard_latest_runs_only_include_runs_above_confidence_threshold(self) -> None:
        session = Session(bind=self.engine)
        try:
            settings_repository = SettingsRepository(session)
            settings_repository.set_setting("confidence_threshold", "75")
            jobs = JobRepository(session)
            runs = RunRepository(session)

            plan_repository = RecommendationPlanRepository(session)

            high_job = jobs.create("High Confidence", ["AAPL"], None)
            high_run = runs.enqueue(high_job.id or 0)
            claimed_high = runs.claim_next_queued_run()
            assert claimed_high is not None
            runs.update_status(high_run.id or 0, "completed")
            plan_repository.create_plan(
                RecommendationPlan(
                    ticker="AAPL",
                    horizon="1w",
                    action="long",
                    confidence_percent=81.0,
                    entry_price_low=101.0,
                    entry_price_high=102.0,
                    stop_loss=97.0,
                    take_profit=111.0,
                    holding_period_days=5,
                    risk_reward_ratio=1.8,
                    thesis_summary="High-confidence seeded plan",
                    rationale_summary="Dashboard filter test",
                    run_id=high_run.id,
                    job_id=high_job.id,
                )
            )

            low_job = jobs.create("Low Confidence", ["MSFT"], None)
            low_run = runs.enqueue(low_job.id or 0)
            claimed_low = runs.claim_next_queued_run()
            assert claimed_low is not None
            runs.update_status(low_run.id or 0, "completed")
            plan_repository.create_plan(
                RecommendationPlan(
                    ticker="MSFT",
                    horizon="1w",
                    action="long",
                    confidence_percent=62.0,
                    entry_price_low=201.0,
                    entry_price_high=202.0,
                    stop_loss=197.0,
                    take_profit=211.0,
                    holding_period_days=5,
                    risk_reward_ratio=1.8,
                    thesis_summary="Lower-confidence seeded plan",
                    rationale_summary="Dashboard filter test",
                    run_id=low_run.id,
                    job_id=low_job.id,
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            dashboard = await client.get("/api/dashboard")

        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.json()
        self.assertEqual(len(payload["latest_runs"]), 1)
        self.assertEqual(payload["latest_runs"][0]["id"], high_run.id)
        self.assertEqual(len(payload["recommendation_plans"]), 2)

    async def test_ticker_api_aggregates_plan_history_and_prototype_trade_log(self) -> None:
        self.seed_run_with_diagnostics()
        self.seed_context_and_recommendation_plan_data()
        self.seed_prototype_trade_log()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/tickers/AAPL")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ticker"], "AAPL")
        self.assertEqual(payload["performance"]["app_plan_count"], 2)
        self.assertEqual(payload["performance"]["actionable_plan_count"], 2)
        self.assertEqual(payload["performance"]["win_plan_count"], 1)
        self.assertEqual(payload["performance"]["open_plan_count"], 1)
        self.assertEqual(payload["performance"]["prototype_trade_count"], 3)
        self.assertEqual(payload["performance"]["resolved_trade_count"], 2)
        self.assertEqual(payload["performance"]["win_count"], 1)
        self.assertEqual(payload["performance"]["loss_count"], 1)
        self.assertEqual(payload["performance"]["pending_trade_count"], 1)
        self.assertEqual(payload["performance"]["win_rate_percent"], 50.0)
        self.assertTrue(payload["performance"]["prototype_trade_log_available"])
        self.assertEqual(len(payload["recommendation_plans"]), 2)
        self.assertEqual(payload["recommendation_plans"][0]["latest_outcome"]["outcome"], "win")
        self.assertEqual(len(payload["prototype_trades"]), 3)
        self.assertEqual(payload["prototype_trades"][0]["status"], "PENDING")

    async def test_failed_run_is_apparent_in_api(self) -> None:
        run_id = self.seed_failed_run()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            api_response = await client.get(f"/api/runs/{run_id}")
            dashboard = await client.get("/api/dashboard")

        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertEqual(payload["run"]["status"], "failed")
        self.assertIn("yfinance", payload["run"]["error_message"])
        self.assertNotIn("outputs", payload)
        self.assertIn("recommendation_generation_seconds", payload["run"]["timing_json"])

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["latest_runs"], [])

    async def test_settings_api_round_trip(self) -> None:
        weights_path = Path(self.prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data" / "weights.json"
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path.write_text('{"alpha": 1}')

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            app_setting = await client.post(
                "/api/settings/app",
                data={"key": "confidence_threshold", "value": "75"},
            )
            optimization_response = await client.post(
                "/api/settings/optimization",
                data={"minimum_resolved_trades": "80"},
            )
            summary_response = await client.post(
                "/api/settings/summary",
                data={
                    "backend": "pi_agent",
                    "model": "anthropic/claude-sonnet-4-5",
                    "timeout_seconds": "65",
                    "max_tokens": "240",
                    "pi_command": "pi",
                    "pi_agent_dir": "/tmp/pi-agent",
                    "prompt": "very short custom summary prompt",
                },
            )
            social_response = await client.post(
                "/api/settings/social",
                data={
                    "sentiment_enabled": "true",
                    "nitter_enabled": "true",
                    "nitter_base_url": "http://127.0.0.1:8080",
                    "nitter_timeout_seconds": "7",
                    "nitter_max_items_per_query": "14",
                    "nitter_query_window_hours": "18",
                    "nitter_include_replies": "true",
                    "nitter_enable_ticker": "true",
                },
            )
            provider_response = await client.post(
                "/api/settings/providers",
                data={"provider": "openai", "api_key": "sk-test", "api_secret": ""},
            )
            listed = await client.get("/api/settings")

        self.assertEqual(app_setting.status_code, 200)
        self.assertEqual(optimization_response.status_code, 200)
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(social_response.status_code, 200)
        self.assertEqual(provider_response.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        payload = listed.json()
        setting_map = {item["key"]: item["value"] for item in payload["settings"]}
        self.assertEqual(setting_map["confidence_threshold"], "75")
        self.assertEqual(setting_map["optimization_minimum_resolved_trades"], "80")
        self.assertEqual(setting_map["summary_model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(setting_map["summary_prompt"], "very short custom summary prompt")
        self.assertEqual(setting_map["social_nitter_enable_ticker"], "true")
        self.assertEqual(payload["providers"][0]["provider"], "openai")
        self.assertEqual(payload["providers"][0]["api_key"], "sk-test")
        self.assertEqual(payload["optimization"]["minimum_resolved_trades"], 80)
        self.assertEqual(payload["optimization"]["weights_path"], str(weights_path))

    async def test_sentiment_snapshot_routes_list_and_detail(self) -> None:
        snapshot_ids = self.seed_sentiment_snapshots()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            listed = await client.get("/api/sentiment-snapshots")
            macro = await client.get("/api/sentiment-snapshots/macro")
            industry = await client.get("/api/sentiment-snapshots/industry")
            detail = await client.get(f"/api/sentiment-snapshots/{snapshot_ids[1]}")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        listed_payload = listed.json()
        macro_payload = macro.json()
        industry_payload = industry.json()
        detail_payload = detail.json()
        self.assertEqual(len(listed_payload["snapshots"]), 2)
        self.assertEqual(macro_payload["scope"], "macro")
        self.assertEqual(len(macro_payload["snapshots"]), 1)
        self.assertEqual(macro_payload["snapshots"][0]["subject_key"], "global_macro")
        self.assertEqual(industry_payload["scope"], "industry")
        self.assertEqual(len(industry_payload["snapshots"]), 1)
        self.assertEqual(detail_payload["id"], snapshot_ids[1])
        self.assertEqual(detail_payload["subject_key"], "consumer_electronics")
        self.assertEqual(detail_payload["coverage"]["social_count"], 6)
        self.assertEqual(detail_payload["drivers"], ["iphone demand stable"])
        self.assertIn("summary_text", detail_payload)
        self.assertTrue(detail_payload["summary_text"])

    async def test_context_and_recommendation_plan_routes_list_new_redesign_models(self) -> None:
        self.seed_context_and_recommendation_plan_data()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            macro = await client.get("/api/context/macro")
            industry = await client.get("/api/context/industry", params={"industry_key": "consumer_electronics"})
            ticker_signals = await client.get("/api/context/ticker-signals", params={"ticker": "AAPL"})
            plans = await client.get("/api/recommendation-plans", params={"ticker": "AAPL", "action": "long"})

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(ticker_signals.status_code, 200)
        self.assertEqual(plans.status_code, 200)
        self.assertEqual(macro.json()[0]["active_themes"][0]["key"], "fed_policy")
        self.assertEqual(industry.json()[0]["industry_key"], "consumer_electronics")
        self.assertEqual(ticker_signals.json()[0]["ticker"], "AAPL")
        self.assertEqual(ticker_signals.json()[0]["diagnostics"]["mode"], "deep_analysis")
        self.assertEqual(plans.json()[0]["action"], "long")
        self.assertEqual(plans.json()[0]["signal_breakdown"]["technical_setup"], 0.77)
        self.assertEqual(plans.json()[0]["latest_outcome"]["outcome"], "win")
        self.assertEqual(plans.json()[0]["latest_outcome"]["setup_family"], "continuation")

    async def test_run_detail_and_filtered_redesign_routes_expose_orchestration_results(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        self.seed_context_and_recommendation_plan_data(run_id=run_id)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            run_detail = await client.get(f"/api/runs/{run_id}")
            macro = await client.get("/api/context/macro", params={"run_id": run_id})
            industry = await client.get("/api/context/industry", params={"run_id": run_id})
            ticker_signals = await client.get("/api/context/ticker-signals", params={"run_id": run_id})
            plans = await client.get("/api/recommendation-plans", params={"run_id": run_id})

        self.assertEqual(run_detail.status_code, 200)
        detail_payload = run_detail.json()
        self.assertEqual(len(detail_payload["macro_context_snapshots"]), 1)
        self.assertEqual(len(detail_payload["industry_context_snapshots"]), 1)
        self.assertEqual(len(detail_payload["ticker_signal_snapshots"]), 1)
        self.assertEqual(len(detail_payload["recommendation_plans"]), 2)
        self.assertEqual(detail_payload["ticker_signal_snapshots"][0]["diagnostics"]["mode"], "deep_analysis")
        self.assertEqual(detail_payload["recommendation_plans"][0]["action"], "long")
        self.assertEqual(detail_payload["recommendation_plans"][0]["latest_outcome"]["outcome"], "win")
        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(ticker_signals.status_code, 200)
        self.assertEqual(plans.status_code, 200)
        self.assertEqual(len(macro.json()), 1)
        self.assertEqual(len(industry.json()), 1)
        self.assertEqual(len(ticker_signals.json()), 1)
        self.assertEqual(len(plans.json()), 2)

    async def test_recommendation_outcome_routes_and_plan_evaluation_queue_runs(self) -> None:
        self.seed_context_and_recommendation_plan_data()
        session = Session(bind=self.engine)
        try:
            plan = RecommendationPlanRepository(session).create_plan(
                RecommendationPlan(
                    ticker="TSLA",
                    horizon="1w",
                    action="long",
                    confidence_percent=52.0,
                    thesis_summary="Weaker continuation setup.",
                    signal_breakdown={
                        "setup_family": "breakout",
                        "transmission_summary": {
                            "context_bias": "headwind",
                            "transmission_tags": ["industry_dominant"],
                        },
                    },
                )
            )
            RecommendationOutcomeRepository(session).upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    ticker="TSLA",
                    action="long",
                    outcome="loss",
                    status="resolved",
                    horizon_return_5d=-2.4,
                    confidence_bucket="50_to_64",
                    setup_family="breakout",
                    notes="Stopped out.",
                )
            )
        finally:
            session.close()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = await client.get("/api/recommendation-plans", params={"ticker": "AAPL"})
            plan_id = plans.json()[0]["id"]
            outcomes = await client.get("/api/recommendation-outcomes", params={"ticker": "AAPL"})
            summary = await client.get("/api/recommendation-outcomes/summary")
            family_filtered_summary = await client.get("/api/recommendation-outcomes/summary", params={"setup_family": "continuation"})
            setup_family_review = await client.get("/api/recommendation-outcomes/setup-family-review")
            evidence_concentration = await client.get("/api/recommendation-outcomes/evidence-concentration")
            baselines = await client.get("/api/recommendation-plans/baselines")
            filtered_plans = await client.get("/api/recommendation-plans", params={"setup_family": "continuation"})
            queued = await client.post("/api/recommendation-plans/evaluate", data={})
            scoped = await client.post(f"/api/recommendation-plans/{plan_id}/evaluate", data={})

        self.assertEqual(outcomes.status_code, 200)
        self.assertEqual(outcomes.json()[0]["outcome"], "win")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["total_outcomes"], 2)
        self.assertEqual(summary.json()["resolved_outcomes"], 2)
        self.assertEqual(summary.json()["overall_win_rate_percent"], 50.0)
        self.assertEqual(family_filtered_summary.status_code, 200)
        self.assertEqual(family_filtered_summary.json()["total_outcomes"], 1)
        self.assertEqual(family_filtered_summary.json()["overall_win_rate_percent"], 100.0)
        bucket_map = {item["key"]: item for item in summary.json()["by_confidence_bucket"]}
        self.assertEqual(bucket_map["65_to_79"]["win_count"], 1)
        self.assertEqual(bucket_map["65_to_79"]["sample_status"], "insufficient")
        self.assertEqual(bucket_map["50_to_64"]["loss_count"], 1)
        setup_map = {item["key"]: item for item in summary.json()["by_setup_family"]}
        self.assertEqual(setup_map["continuation"]["win_count"], 1)
        self.assertEqual(setup_map["breakout"]["loss_count"], 1)
        horizon_map = {item["key"]: item for item in summary.json()["by_horizon"]}
        self.assertEqual(horizon_map["1w"]["resolved_count"], 2)
        transmission_map = {item["key"]: item for item in summary.json()["by_transmission_bias"]}
        self.assertEqual(transmission_map["tailwind"]["win_count"], 1)
        self.assertEqual(transmission_map["headwind"]["loss_count"], 1)
        regime_map = {item["key"]: item for item in summary.json()["by_context_regime"]}
        self.assertEqual(regime_map["context_plus_catalyst"]["win_count"], 1)
        self.assertEqual(regime_map["industry_dominant"]["loss_count"], 1)
        horizon_setup_map = {item["key"]: item for item in summary.json()["by_horizon_setup_family"]}
        self.assertEqual(horizon_setup_map["1w__continuation"]["win_count"], 1)
        self.assertEqual(horizon_setup_map["1w__breakout"]["loss_count"], 1)
        self.assertEqual(setup_family_review.status_code, 200)
        family_review_map = {item["family"]: item for item in setup_family_review.json()["families"]}
        self.assertEqual(family_review_map["continuation"]["win_outcomes"], 1)
        self.assertEqual(family_review_map["continuation"]["by_horizon"][0]["key"], "1w")
        self.assertEqual(family_review_map["breakout"]["loss_outcomes"], 1)
        self.assertEqual(evidence_concentration.status_code, 200)
        self.assertEqual(evidence_concentration.json()["resolved_outcomes_reviewed"], 2)
        self.assertIn("strongest_positive_cohorts", evidence_concentration.json())
        self.assertEqual(filtered_plans.status_code, 200)
        self.assertEqual(len(filtered_plans.json()), 1)
        self.assertEqual(filtered_plans.json()[0]["ticker"], "AAPL")
        self.assertEqual(baselines.status_code, 200)
        self.assertEqual(baselines.json()["total_trade_plans_reviewed"], 2)
        baseline_map = {item["key"]: item for item in baselines.json()["comparisons"]}
        self.assertEqual(baseline_map["actual_actionable"]["resolved_trade_count"], 2)
        self.assertEqual(baseline_map["actual_actionable"]["win_rate_percent"], 50.0)
        self.assertEqual(baseline_map["momentum_setup_lane"]["resolved_trade_count"], 2)
        family_baseline_map = {item["key"]: item for item in baselines.json()["family_cohorts"]}
        self.assertEqual(family_baseline_map["family__continuation"]["win_count"], 1)
        self.assertEqual(family_baseline_map["family__breakout"]["loss_count"], 1)
        self.assertEqual(family_baseline_map["family__mean_reversion"]["trade_plan_count"], 0)
        self.assertEqual(queued.status_code, 200)
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(queued.json()["job_type"], JobType.RECOMMENDATION_EVALUATION.value)
        self.assertEqual(scoped.json()["job_type"], JobType.RECOMMENDATION_EVALUATION.value)

    async def test_sentiment_snapshot_detail_returns_404_for_missing_snapshot(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/sentiment-snapshots/9999")

        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.text.lower())

    async def test_sentiment_snapshot_manual_refresh_routes_queue_runs(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            macro = await client.post("/api/sentiment-snapshots/refresh/macro", data={})
            industry = await client.post("/api/sentiment-snapshots/refresh/industry", data={})
            runs = await client.get("/api/runs")

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(macro.json()["job_type"], JobType.MACRO_SENTIMENT_REFRESH.value)
        self.assertEqual(industry.json()["job_type"], JobType.INDUSTRY_SENTIMENT_REFRESH.value)
        run_job_types = [item["job_type"] for item in runs.json()]
        self.assertIn(JobType.MACRO_SENTIMENT_REFRESH.value, run_job_types)
        self.assertIn(JobType.INDUSTRY_SENTIMENT_REFRESH.value, run_job_types)

    async def test_sentiment_snapshot_run_now_routes_execute_synchronously(self) -> None:
        class StubSnapshotExecutionService:
            def __init__(self, session: Session) -> None:
                self.jobs = JobRepository(session)
                self.runs = RunRepository(session)

            def enqueue_job(self, job_id: int, scheduled_for=None) -> Run:
                return self.runs.enqueue(job_id, scheduled_for=scheduled_for, job_type=self.jobs.get(job_id).job_type)

            def execute_claimed_run(self, run: Run) -> tuple[Run, list[object]]:
                artifact = {"snapshot_id": 99, "scope": "macro", "subject_key": "global_macro"}
                summary = {"status": "completed", "snapshot_count": 1}
                self.runs.set_artifact(run.id or 0, artifact)
                self.runs.set_summary(run.id or 0, summary)
                self.runs.update_status(run.id or 0, "completed")
                return self.runs.get_run(run.id or 0), []

        transport = httpx.ASGITransport(app=app)
        with patch(
            "trade_proposer_app.api.routes.sentiment_snapshots._create_job_execution_service",
            side_effect=lambda session: StubSnapshotExecutionService(session),
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                macro = await client.post("/api/sentiment-snapshots/refresh/macro/run-now", data={})
                industry = await client.post("/api/sentiment-snapshots/refresh/industry/run-now", data={})

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertTrue(macro.json()["executed"])
        self.assertTrue(industry.json()["executed"])
        self.assertEqual(macro.json()["run"]["status"], "completed")
        self.assertEqual(industry.json()["run"]["status"], "completed")
        self.assertEqual(macro.json()["artifact"]["snapshot_id"], 99)

    async def test_settings_rollback_restores_latest_weights_backup(self) -> None:
        data_dir = Path(self.prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        weights_path = data_dir / "weights.json"
        weights_path.write_text('{"alpha": 9}')
        backup_dir = data_dir / "weight_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "weights.20260314T120000000000Z.json.bak"
        backup_path.write_text('{"alpha": 1}')

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/settings/optimization/rollback", data={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rollback"]["status"], "rolled_back")
        self.assertEqual(payload["rollback"]["restored_from"], str(backup_path))
        self.assertEqual(weights_path.read_text(), '{"alpha": 1}')

    async def test_settings_rollback_can_restore_selected_backup_path(self) -> None:
        data_dir = Path(self.prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        weights_path = data_dir / "weights.json"
        weights_path.write_text('{"alpha": 9}')
        backup_dir = data_dir / "weight_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        older_backup = backup_dir / "weights.20260314T110000000000Z.json.bak"
        newer_backup = backup_dir / "weights.20260314T120000000000Z.json.bak"
        older_backup.write_text('{"alpha": 1}')
        newer_backup.write_text('{"alpha": 2}')

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/settings/optimization/rollback",
                data={"backup_path": str(older_backup)},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rollback"]["restored_from"], str(older_backup))
        self.assertEqual(weights_path.read_text(), '{"alpha": 1}')

    async def test_single_user_auth_guarding(self) -> None:
        prev_enabled = settings.single_user_auth_enabled
        prev_token = settings.single_user_auth_token
        prev_allowlist = settings.single_user_auth_allowlist_paths
        settings.single_user_auth_enabled = True
        settings.single_user_auth_token = "test-token"
        settings.single_user_auth_allowlist_paths = None
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/api/watchlists")
                self.assertEqual(response.status_code, 401)

                auth_response = await client.get(
                    "/api/watchlists",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(auth_response.status_code, 200)

                health = await client.get("/api/health")
                self.assertEqual(health.status_code, 200)
        finally:
            settings.single_user_auth_enabled = prev_enabled
            settings.single_user_auth_token = prev_token
            settings.single_user_auth_allowlist_paths = prev_allowlist

    async def test_login_route_returns_token(self) -> None:
        prev_enabled = settings.single_user_auth_enabled
        prev_token = settings.single_user_auth_token
        prev_username = settings.single_user_auth_username
        prev_password = settings.single_user_auth_password
        settings.single_user_auth_enabled = True
        settings.single_user_auth_username = "login-user"
        settings.single_user_auth_password = "lets-login"
        settings.single_user_auth_token = "returned-token"
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                success = await client.post(
                    "/api/login",
                    data={"username": "login-user", "password": "lets-login"},
                )
                self.assertEqual(success.status_code, 200)
                self.assertEqual(success.json()["token"], "returned-token")

                failure = await client.post(
                    "/api/login",
                    data={"username": "login-user", "password": "wrong"},
                )
                self.assertEqual(failure.status_code, 401)
        finally:
            settings.single_user_auth_enabled = prev_enabled
            settings.single_user_auth_token = prev_token
            settings.single_user_auth_username = prev_username
            settings.single_user_auth_password = prev_password


if __name__ == "__main__":
    unittest.main()
