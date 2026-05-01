import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import (
    AppPreflightReport,
    BrokerOrderExecution,
    BrokerPosition,
    EvaluationRunResult,
    HistoricalMarketBar,
    NewsArticle,
    IndustryContextSnapshot,
    MacroContextSnapshot,
    PreflightCheck,
    RecommendationDecisionSample,
    RecommendationPlan,
    RecommendationPlanOutcome,
    Run,
    TickerSignalSnapshot,
    WorkerHeartbeat,
)
from trade_proposer_app.persistence.models import Base, RecommendationPlanRecord, RunRecord, TickerSignalSnapshotRecord
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClientError


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


class StubAlpacaPaperClient:
    def __init__(self, *args, **kwargs) -> None:
        self.submitted_requests: list[dict[str, object]] = []
        self.canceled_order_ids: list[str] = []
        self.get_requests: list[str] = []
        self.order_payloads: dict[str, dict[str, object]] = {
            "alpaca-order-2": {"id": "alpaca-order-2", "status": "filled", "filled_at": "2026-04-22T15:00:00Z", "submitted_at": "2026-04-22T14:30:00Z"},
            "alpaca-order-3": {"id": "alpaca-order-3", "status": "canceled", "canceled_at": "2026-04-22T15:05:00Z", "submitted_at": "2026-04-22T14:40:00Z"},
        }

    def submit_order(self, payload: dict[str, object]):
        self.submitted_requests.append(payload)
        return type(
            "SubmissionResult",
            (),
            {"broker_order_id": "alpaca-order-99", "broker_status": "accepted", "payload": {"id": "alpaca-order-99", "status": "accepted"}},
        )()

    def get_order(self, order_id: str):
        self.get_requests.append(order_id)
        payload = self.order_payloads.get(order_id, {"id": order_id, "status": "accepted"})
        return type(
            "GetResult",
            (),
            {"broker_order_id": order_id, "broker_status": str(payload.get("status", "accepted")), "payload": payload},
        )()

    def cancel_order(self, order_id: str):
        self.canceled_order_ids.append(order_id)
        return type(
            "CancelResult",
            (),
            {"broker_order_id": order_id, "broker_status": "canceled", "payload": {"id": order_id, "status": "canceled"}},
        )()


class StubOrderActionService:
    def resubmit_execution(self, execution_id: int):
        raise ValueError("only failed or canceled broker orders can be resubmitted")

    def cancel_execution(self, execution_id: int):
        raise AlpacaPaperClientError("alpaca request failed with status 502")

    def refresh_execution(self, execution_id: int):
        return BrokerOrderExecution(id=execution_id, broker="alpaca", account_mode="paper", recommendation_plan_id=1, recommendation_plan_ticker="AAPL", ticker="AAPL", action="long", side="buy", order_type="limit", time_in_force="gtc", quantity=1, notional_amount=100.0, status="filled", broker_order_id="alpaca-order-1", client_order_id="tp", request_payload={}, response_payload={"id": "alpaca-order-1", "status": "filled"}, error_message="", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))

    def sync_open_executions(self):
        return type("SyncOutcome", (), {"summary": {"requested_count": 1, "synced_count": 1, "skipped_count": 0, "failed_count": 0, "warnings_found": False, "warnings": [], "orders": []}})()


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
        self.weights_root = tempfile.TemporaryDirectory()
        self.original_weights_file_path = settings.weights_file_path
        settings.weights_file_path = str(Path(self.weights_root.name) / "weights.json")

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
        settings.weights_file_path = self.original_weights_file_path
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        settings.single_user_auth_token = self._previous_single_user_auth_token
        settings.single_user_auth_allowlist_paths = self._previous_single_user_auth_allowlist_paths
        settings.single_user_auth_username = self._previous_single_user_auth_username
        settings.single_user_auth_password = self._previous_single_user_auth_password
        self.weights_root.cleanup()

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
            plan = RecommendationPlanRepository(session).create_plan(
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
            RecommendationDecisionSampleRepository(session).upsert_sample(
                RecommendationDecisionSample(
                    recommendation_plan_id=plan.id or 0,
                    ticker="AAPL",
                    horizon="1w",
                    action="long",
                    decision_type="actionable",
                    confidence_percent=81.0,
                    calibrated_confidence_percent=81.0,
                    setup_family="continuation",
                    reviewed_at=datetime(2026, 3, 24, tzinfo=timezone.utc),
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
                error_message="dependency missing: No module named 'yfinance'",
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
                    diagnostics={"mode": "deep_analysis", "transmission_bias": "tailwind"},
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
                        "news_item_count": 3,
                        "social_item_count": 4,
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

    async def test_health_endpoint(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["preflight"]["status"], "warning")
        self.assertEqual(payload["context_snapshots"]["macro"]["status"], "warning")
        self.assertEqual(payload["context_snapshots"]["industry"]["status"], "warning")

    async def test_preflight_health_endpoint(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/health/preflight")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["engine"], "internal_price_pipeline")
        self.assertTrue(any(check["name"] == "module:pandas" for check in payload["checks"]))
        self.assertTrue(any(check["name"] == "context_snapshot:macro" for check in payload["checks"]))

    async def test_active_workers_endpoint_lists_worker_heartbeats(self) -> None:
        session = Session(bind=self.engine)
        try:
            RunRepository(session).upsert_heartbeat(
                WorkerHeartbeat(
                    worker_id="worker-test",
                    hostname="worker-host",
                    pid=1234,
                    status="running",
                    last_heartbeat_at=datetime.now(timezone.utc),
                    started_at=datetime.now(timezone.utc),
                    active_run_id=99,
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/workers/active")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["workers"][0]["worker_id"], "worker-test")
        self.assertEqual(payload["workers"][0]["active_run_id"], 99)

    async def test_worker_logs_endpoint_returns_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / ".dev-run" / "workers"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "worker-test.log"
            log_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

            with patch("trade_proposer_app.api.routes.workers.WORKER_LOG_DIRECTORIES", (log_dir,)):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    response = await client.get("/api/workers/worker-test/logs?tail=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["worker_id"], "worker-test")
        self.assertEqual(payload["line_count"], 3)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["lines"], ["line three"])

    async def test_spa_shell_routes_render(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for path in ("/", "/login", "/watchlists", "/jobs", "/history", "/debugger", "/settings", "/docs", "/context", "/context/sentiment/1", "/context/macro/1", "/sentiment", "/sentiment/1", "/runs/1", "/workers/worker-test", "/recommendation-plans", "/tickers/AAPL", "/research", "/research/signal-gating/gating-job", "/recommendation-quality"):
                response = await client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("<title>Aurelio</title>", response.text)

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
        self.assertTrue(any("Price levels and risk" in section["title"] for section in methodology["sections"]))

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
                    "name": "Weekly Plan Generation Tuning",
                    "job_type": JobType.PLAN_GENERATION_TUNING.value,
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
        self.assertEqual(optimization.json()["job_type"], JobType.PLAN_GENERATION_TUNING.value)
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
            plan = RecommendationPlanRepository(session).create_plan(
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
            RecommendationDecisionSampleRepository(session).upsert_sample(
                RecommendationDecisionSample(
                    recommendation_plan_id=plan.id or 0,
                    ticker="AAPL",
                    horizon="1w",
                    action="long",
                    decision_type="actionable",
                    confidence_percent=80.0,
                    calibrated_confidence_percent=80.0,
                    setup_family="continuation",
                    reviewed_at=datetime(2026, 3, 24, tzinfo=timezone.utc),
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
        self.assertEqual(detail_payload["broker_order_executions"], [])
        self.assertEqual(len(detail_payload["recommendation_plans"]), 1)

    async def test_dashboard_filters_by_window_and_keeps_only_proper_failures(self) -> None:
        winning_run_id = self.seed_run_with_diagnostics()
        recent_failed_run_id = self.seed_failed_run()
        self.seed_context_and_recommendation_plan_data(run_id=winning_run_id)

        old_timestamp = datetime.now(timezone.utc) - timedelta(days=45)
        now = datetime.now(timezone.utc)
        session = Session(bind=self.engine)
        try:
            jobs = JobRepository(session)
            runs = RunRepository(session)
            old_job = jobs.create("Failed Old", ["AAPL"], None)
            old_run = runs.enqueue(old_job.id or 0)
            claimed = runs.claim_next_queued_run()
            assert claimed is not None
            runs.update_status(old_run.id or 0, "failed", error_message="dependency missing: older failure")

            context_repository = ContextSnapshotRepository(session)
            old_signal = context_repository.create_ticker_signal_snapshot(
                TickerSignalSnapshot(
                    ticker="MSFT",
                    horizon="1w",
                    direction="long",
                    swing_probability_percent=55.0,
                    confidence_percent=58.0,
                    attention_score=61.0,
                    diagnostics={"mode": "deep_analysis"},
                    run_id=winning_run_id,
                )
            )
            old_plan = RecommendationPlanRepository(session).create_plan(
                RecommendationPlan(
                    ticker="MSFT",
                    horizon="1w",
                    action="long",
                    confidence_percent=58.0,
                    entry_price_low=301.0,
                    entry_price_high=303.0,
                    stop_loss=297.0,
                    take_profit=309.0,
                    holding_period_days=5,
                    risk_reward_ratio=1.7,
                    thesis_summary="Old plan outside the 1d window",
                    rationale_summary="Window filter test",
                    signal_breakdown={"setup_family": "continuation"},
                    run_id=winning_run_id,
                )
            )
            HistoricalNewsRepository(session).save_news(
                "AAPL",
                "Reuters",
                [
                    NewsArticle(title="AAPL earnings headline", summary="News item 1", publisher="Reuters", link="https://example.com/news-1", published_at=now),
                    NewsArticle(title="AAPL product update", summary="News item 2", publisher="Reuters", link="https://example.com/news-2", published_at=now),
                ],
            )
            HistoricalMarketDataRepository(session).upsert_bars(
                [
                    HistoricalMarketBar(ticker="AAPL", timeframe="1d", bar_time=now - timedelta(hours=2), open_price=100.0, high_price=101.0, low_price=99.0, close_price=100.5, volume=1000, source="test", source_tier="tier_a"),
                    HistoricalMarketBar(ticker="AAPL", timeframe="1d", bar_time=now - timedelta(hours=1), open_price=100.5, high_price=102.0, low_price=100.0, close_price=101.5, volume=1500, source="test", source_tier="tier_a"),
                    HistoricalMarketBar(ticker="AAPL", timeframe="1d", bar_time=now, open_price=101.5, high_price=103.0, low_price=101.0, close_price=102.5, volume=2000, source="test", source_tier="tier_a"),
                ]
            )
            BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=old_plan.id or 0,
                    recommendation_plan_ticker="MSFT",
                    run_id=winning_run_id,
                    job_id=old_job.id,
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=1,
                    notional_amount=100.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="queued",
                    client_order_id="tp-dashboard-technical-1",
                    request_payload={"symbol": "AAPL", "qty": 1},
                    response_payload={},
                )
            )
            session.execute(
                update(RunRecord)
                .where(RunRecord.id == old_run.id)
                .values(created_at=old_timestamp, updated_at=old_timestamp)
            )
            session.execute(
                update(TickerSignalSnapshotRecord)
                .where(TickerSignalSnapshotRecord.id == old_signal.id)
                .values(computed_at=old_timestamp, created_at=old_timestamp, updated_at=old_timestamp)
            )
            session.execute(
                update(RecommendationPlanRecord)
                .where(RecommendationPlanRecord.id == old_plan.id)
                .values(computed_at=old_timestamp, created_at=old_timestamp, updated_at=old_timestamp)
            )
            session.commit()
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            dashboard_all = await client.get("/api/dashboard", params={"window": "all"})
            dashboard_1d = await client.get("/api/dashboard", params={"window": "1d"})

        self.assertEqual(dashboard_all.status_code, 200)
        self.assertEqual(dashboard_1d.status_code, 200)

        all_payload = dashboard_all.json()
        one_day_payload = dashboard_1d.json()
        self.assertEqual(all_payload["dashboard_window"], "all")
        self.assertEqual(one_day_payload["dashboard_window"], "1d")
        self.assertGreater(all_payload["dashboard_summary"]["plan_amount"], one_day_payload["dashboard_summary"]["plan_amount"])
        self.assertGreater(all_payload["dashboard_summary"]["signals_amount"], one_day_payload["dashboard_summary"]["signals_amount"])
        self.assertEqual(
            one_day_payload["dashboard_summary"]["shortlist_rate_percent"],
            round((one_day_payload["dashboard_summary"]["plan_amount"] / one_day_payload["dashboard_summary"]["signals_amount"]) * 100.0, 1),
        )
        self.assertEqual(
            all_payload["dashboard_summary"]["shortlist_rate_percent"],
            round((all_payload["dashboard_summary"]["plan_amount"] / all_payload["dashboard_summary"]["signals_amount"]) * 100.0, 1),
        )
        self.assertEqual(one_day_payload["technical_summary"]["news_processed"], 2)
        self.assertEqual(one_day_payload["technical_summary"]["tweets_processed"], 4)
        self.assertEqual(one_day_payload["technical_summary"]["bars_stored"], 3)
        self.assertEqual(one_day_payload["technical_summary"]["orders_placed"], 1)
        self.assertTrue(all(item["status"] == "failed" for item in one_day_payload["major_failures"]))
        self.assertFalse(any(item["status"] == "completed_with_warnings" for item in all_payload["major_failures"]))
        self.assertTrue(any(item["label"] == "summary timeout" for item in one_day_payload["distinct_warnings"]))

    async def test_run_detail_includes_broker_orders_and_manual_actions_work(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        session = Session(bind=self.engine)
        try:
            settings_repo = SettingsRepository(session)
            settings_repo.upsert_provider_credential("alpaca", "paper-key", "paper-secret")
            settings_repo.set_risk_management_config(
                enabled=True,
                max_daily_realized_loss_usd=50.0,
                max_open_positions=3,
                max_open_notional_usd=3000.0,
                max_position_notional_usd=2000.0,
                max_same_ticker_open_positions=1,
                max_consecutive_losses=3,
            )
            job = JobRepository(session).list_all()[0]
            plan = RecommendationPlanRepository(session).list_plans(run_id=run_id, limit=10)[0]
            broker_orders = BrokerOrderExecutionRepository(session)
            failed_order = broker_orders.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1010.0,
                    entry_price=101.0,
                    stop_loss=97.0,
                    take_profit=111.0,
                    status="failed",
                    client_order_id="tp-run-1-plan-1-aapl",
                    request_payload={"symbol": "AAPL", "qty": 10, "limit_price": 101.0, "client_order_id": "tp-run-1-plan-1-aapl"},
                    response_payload={"id": "alpaca-order-1", "status": "rejected"},
                    error_message="alpaca order submission failed",
                )
            )
            open_order = broker_orders.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1010.0,
                    entry_price=101.0,
                    stop_loss=97.0,
                    take_profit=111.0,
                    status="submitted",
                    broker_order_id="alpaca-order-2",
                    client_order_id="tp-run-1-plan-1-aapl-live",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={"symbol": "AAPL", "qty": 10, "limit_price": 101.0, "client_order_id": "tp-run-1-plan-1-aapl-live"},
                    response_payload={"id": "alpaca-order-2", "status": "accepted"},
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        with patch("trade_proposer_app.services.builders.AlpacaPaperClient", StubAlpacaPaperClient):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                run_detail = await client.get(f"/api/runs/{run_id}")
                resubmit = await client.post(f"/api/broker-orders/{failed_order.id}/resubmit")
                cancel = await client.post(f"/api/broker-orders/{open_order.id}/cancel")
                run_detail_after = await client.get(f"/api/runs/{run_id}")

        self.assertEqual(run_detail.status_code, 200)
        self.assertEqual(len(run_detail.json()["broker_order_executions"]), 2)
        self.assertEqual(resubmit.status_code, 200)
        self.assertEqual(resubmit.json()["status"], "accepted")
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json()["status"], "canceled")
        self.assertTrue(any(order["status"] == "canceled" for order in run_detail_after.json()["broker_order_executions"]))

    async def test_risk_routes_assess_halt_and_resume(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        session = Session(bind=self.engine)
        try:
            plan = RecommendationPlanRepository(session).list_plans(run_id=run_id, limit=10)[0]
            BrokerPositionRepository(session).create(
                BrokerPosition(
                    broker_order_execution_id=1,
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    quantity=10,
                    current_quantity=0,
                    status="loss",
                    realized_pnl=-10.0,
                    exit_filled_at=datetime.now(timezone.utc),
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            risk = await client.get("/api/risk")
            halted = await client.post("/api/risk/halt", data={"reason": "test halt"})
            resumed = await client.post("/api/risk/resume")
            halt_events = await client.get("/api/risk/halt-events")

        self.assertEqual(risk.status_code, 200)
        self.assertEqual(risk.json()["metrics"]["today_loss_count"], 1)
        self.assertEqual(halted.status_code, 200)
        self.assertFalse(halted.json()["allowed"])
        self.assertIn("manual_halt_active", halted.json()["reasons"])
        self.assertEqual(resumed.status_code, 200)
        self.assertFalse(resumed.json()["halt_enabled"])
        self.assertEqual(halt_events.status_code, 200)
        self.assertEqual([event["action"] for event in halt_events.json()], ["resume", "halt"])
        self.assertEqual(halt_events.json()[1]["reason"], "test halt")

    async def test_broker_position_routes_list_and_fetch_positions(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).list_all()[0]
            plan = RecommendationPlanRepository(session).list_plans(run_id=run_id, limit=10)[0]
            order = BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=10,
                    notional_amount=1000.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="win",
                    broker_order_id="alpaca-order-position",
                    client_order_id="tp-run-1-plan-1-position",
                    request_payload={"symbol": "AAPL"},
                    response_payload={"id": "alpaca-order-position", "status": "filled"},
                )
            )
            position = BrokerPositionRepository(session).create(
                BrokerPosition(
                    broker_order_execution_id=order.id or 0,
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    quantity=10,
                    current_quantity=0,
                    status="win",
                    entry_order_id="alpaca-order-position",
                    entry_avg_price=100.0,
                    exit_order_id="take-profit-leg",
                    exit_reason="take_profit",
                    exit_avg_price=110.0,
                    realized_pnl=100.0,
                    realized_return_pct=10.0,
                    realized_r_multiple=2.0,
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            listed = await client.get(f"/api/broker-positions?run_id={run_id}")
            fetched = await client.get(f"/api/broker-positions/{position.id}")
            missing = await client.get("/api/broker-positions/999999")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["status"], "win")
        self.assertEqual(listed.json()[0]["realized_pnl"], 100.0)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["exit_reason"], "take_profit")
        self.assertEqual(missing.status_code, 404)

    async def test_research_performance_workbench_returns_canonical_summaries(self) -> None:
        self.seed_run_with_diagnostics()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/research/performance-workbench")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("latest_assessment", payload)
        self.assertIn("broker_summary", payload)
        self.assertIn("effective_summary", payload)
        self.assertIn("calibration_summary", payload)
        self.assertIn("entry_miss_diagnostics", payload)
        self.assertIn("closed_positions", payload["broker_summary"])
        self.assertIn("resolved_outcomes", payload["effective_summary"])

    async def test_broker_workbench_returns_orders_positions_and_risk(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).list_all()[0]
            plan = RecommendationPlanRepository(session).list_plans(run_id=run_id, limit=10)[0]
            order = BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=1,
                    notional_amount=100.0,
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    status="open",
                    client_order_id="tp-workbench",
                    request_payload={"symbol": plan.ticker},
                    response_payload={},
                )
            )
            BrokerPositionRepository(session).create(
                BrokerPosition(
                    broker_order_execution_id=order.id or 0,
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    quantity=1,
                    current_quantity=1,
                    status="open",
                    entry_avg_price=100.0,
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/broker-workbench?run_id={run_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["broker_orders"], 1)
        self.assertEqual(payload["counts"]["broker_positions"], 1)
        self.assertEqual(payload["broker_orders"][0]["client_order_id"], "tp-workbench")
        self.assertEqual(payload["broker_positions"][0]["status"], "open")
        self.assertIn("allowed", payload["risk"])
        self.assertIn("risk_halt_events", payload)

    async def test_broker_order_routes_return_expected_errors(self) -> None:
        run_id = self.seed_run_with_diagnostics()
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).list_all()[0]
            plan = RecommendationPlanRepository(session).list_plans(run_id=run_id, limit=10)[0]
            broker_orders = BrokerOrderExecutionRepository(session)
            submitted_order = broker_orders.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1010.0,
                    entry_price=101.0,
                    stop_loss=97.0,
                    take_profit=111.0,
                    status="submitted",
                    broker_order_id="alpaca-order-3",
                    client_order_id="tp-run-1-plan-1-aapl-open",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={"symbol": "AAPL", "qty": 10, "limit_price": 101.0, "client_order_id": "tp-run-1-plan-1-aapl-open"},
                    response_payload={"id": "alpaca-order-3", "status": "accepted"},
                )
            )
            missing_broker_id = broker_orders.create(
                BrokerOrderExecution(
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=plan.id or 0,
                    recommendation_plan_ticker=plan.ticker,
                    run_id=run_id,
                    job_id=job.id,
                    ticker=plan.ticker,
                    action="long",
                    side="buy",
                    order_type="limit",
                    time_in_force="gtc",
                    quantity=10,
                    notional_amount=1010.0,
                    entry_price=101.0,
                    stop_loss=97.0,
                    take_profit=111.0,
                    status="submitted",
                    client_order_id="tp-run-1-plan-1-aapl-open-2",
                    submitted_at=datetime.now(timezone.utc),
                    request_payload={"symbol": "AAPL", "qty": 10, "limit_price": 101.0, "client_order_id": "tp-run-1-plan-1-aapl-open-2"},
                    response_payload={"id": "alpaca-order-4", "status": "accepted"},
                )
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            not_found = await client.get("/api/broker-orders/999999")
            resubmit_error = await client.post(f"/api/broker-orders/{submitted_order.id}/resubmit")
            cancel_error = await client.post(f"/api/broker-orders/{missing_broker_id.id}/cancel")

        with patch("trade_proposer_app.api.routes.broker_orders.create_order_execution_service", return_value=StubOrderActionService()):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                cancel_gateway_error = await client.post(f"/api/broker-orders/{submitted_order.id}/cancel")
                refresh_result = await client.post(f"/api/broker-orders/{submitted_order.id}/refresh")
                sync_result = await client.post("/api/broker-orders/sync")

        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(resubmit_error.status_code, 400)
        self.assertEqual(cancel_error.status_code, 400)
        self.assertEqual(cancel_gateway_error.status_code, 502)
        self.assertEqual(refresh_result.status_code, 200)
        self.assertEqual(refresh_result.json()["status"], "filled")
        self.assertEqual(sync_result.status_code, 200)
        self.assertEqual(sync_result.json()["synced_count"], 1)

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

    async def test_delete_stale_running_run_is_recovered_then_deleted(self) -> None:
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).create("Stale Running", ["AAPL"], None)
            run = RunRepository(session).enqueue(job.id or 0)
            session.execute(
                update(RunRecord)
                .where(RunRecord.id == run.id)
                .values(status="running", started_at=datetime(2026, 3, 24, 11, 0, tzinfo=timezone.utc))
            )
            session.commit()
            run_id = run.id or 0
        finally:
            session.close()

        previous_timeout = settings.run_stale_after_seconds
        settings.run_stale_after_seconds = 60
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                deleted = await client.delete(f"/api/runs/{run_id}")
                run_detail = await client.get(f"/api/runs/{run_id}")
        finally:
            settings.run_stale_after_seconds = previous_timeout

        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(run_detail.status_code, 404)

    async def test_force_delete_active_run(self) -> None:
        session = Session(bind=self.engine)
        try:
            job = JobRepository(session).create("Force Delete Job", ["AAPL"], None)
            run = RunRepository(session).enqueue(job.id or 0)
            run_id = run.id or 0
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            deleted = await client.delete(f"/api/runs/{run_id}?force=true")
            run_detail = await client.get(f"/api/runs/{run_id}")

        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertTrue(deleted.json()["force"])
        self.assertEqual(run_detail.status_code, 404)

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

    async def test_ticker_api_aggregates_recommendation_plan_history(self) -> None:
        self.seed_run_with_diagnostics()
        self.seed_context_and_recommendation_plan_data()
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
        self.assertEqual(len(payload["recommendation_plans"]), 2)
        self.assertEqual(payload["recommendation_plans"][0]["latest_outcome"]["outcome"], "win")
        self.assertNotIn("prototype_trades", payload)
        self.assertNotIn("legacy_trades", payload)

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
        weights_path = Path(settings.weights_file_path)
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path.write_text('{"alpha": 1}')

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            app_setting = await client.post(
                "/api/settings/app",
                data={"key": "confidence_threshold", "value": "75"},
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
            signal_gating_tuning_response = await client.post(
                "/api/settings/signal-gating-tuning",
                data={
                    "threshold_offset": "-2.5",
                    "confidence_adjustment": "1.5",
                    "near_miss_gap_cutoff": "2.0",
                    "shortlist_aggressiveness": "1.0",
                    "degraded_penalty": "0.5",
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
            plan_generation_tuning_response = await client.post(
                "/api/settings/plan-generation-tuning",
                data={
                    "auto_enabled": "true",
                    "auto_promote_enabled": "true",
                    "min_actionable_resolved": "31",
                    "min_validation_resolved": "12",
                },
            )
            realism_response = await client.post(
                "/api/settings/evaluation-realism",
                data={
                    "stop_buffer_pct": "0.06",
                    "take_profit_buffer_pct": "0.07",
                    "friction_pct": "0.15",
                },
            )
            newsapi_response = await client.post(
                "/api/settings/providers",
                data={"provider": "newsapi", "api_key": "news-key", "api_secret": ""},
            )
            provider_response = await client.post(
                "/api/settings/providers",
                data={"provider": "openai", "api_key": "sk-test", "api_secret": "secret-test"},
            )
            listed = await client.get("/api/settings")

        self.assertEqual(app_setting.status_code, 200)
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(signal_gating_tuning_response.status_code, 200)
        self.assertEqual(social_response.status_code, 200)
        self.assertEqual(plan_generation_tuning_response.status_code, 200)
        self.assertEqual(realism_response.status_code, 200)
        self.assertEqual(provider_response.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        payload = listed.json()
        setting_map = {item["key"]: item["value"] for item in payload["settings"]}
        self.assertEqual(setting_map["confidence_threshold"], "75")
        self.assertEqual(setting_map["signal_gating_tuning_threshold_offset"], "-2.5")
        self.assertEqual(setting_map["evaluation_realism_stop_buffer_pct"], "0.06")
        self.assertEqual(payload["evaluation_realism"]["friction_pct"], 0.15)
        self.assertEqual(setting_map["signal_gating_tuning_confidence_adjustment"], "1.5")
        self.assertEqual(setting_map["signal_gating_tuning_near_miss_gap_cutoff"], "2")
        self.assertEqual(setting_map["signal_gating_tuning_shortlist_aggressiveness"], "1")
        self.assertEqual(setting_map["signal_gating_tuning_degraded_penalty"], "0.5")
        self.assertEqual(payload["signal_gating_tuning"]["threshold_offset"], -2.5)
        self.assertEqual(payload["signal_gating_tuning"]["confidence_adjustment"], 1.5)
        self.assertEqual(payload["signal_gating_tuning"]["near_miss_gap_cutoff"], 2.0)
        self.assertEqual(payload["signal_gating_tuning"]["shortlist_aggressiveness"], 1.0)
        self.assertEqual(payload["signal_gating_tuning"]["degraded_penalty"], 0.5)
        self.assertEqual(setting_map["summary_model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(setting_map["summary_prompt"], "very short custom summary prompt")
        self.assertEqual(setting_map["social_nitter_enable_ticker"], "true")
        self.assertEqual(setting_map["plan_generation_tuning_auto_enabled"], "true")
        self.assertEqual(setting_map["plan_generation_tuning_auto_promote_enabled"], "true")
        self.assertEqual(setting_map["plan_generation_tuning_min_actionable_resolved"], "31")
        self.assertEqual(setting_map["plan_generation_tuning_min_validation_resolved"], "12")
        self.assertEqual(payload["plan_generation_tuning"]["settings"]["auto_enabled"], True)
        self.assertEqual(payload["plan_generation_tuning"]["settings"]["auto_promote_enabled"], True)
        self.assertEqual(payload["plan_generation_tuning"]["settings"]["min_actionable_resolved"], 31)
        self.assertEqual(payload["plan_generation_tuning"]["settings"]["min_validation_resolved"], 12)
        providers = {item["provider"]: item for item in payload["providers"]}
        self.assertEqual(providers["newsapi"]["api_key"], "news-key")
        self.assertEqual(providers["openai"]["api_key"], "sk-test")
        self.assertNotIn("api_secret", providers["newsapi"])
        self.assertNotIn("api_secret", provider_response.json())
        self.assertNotIn("api_secret", newsapi_response.json())
    async def test_context_routes_list_and_detail(self) -> None:
        self.seed_context_and_recommendation_plan_data()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            macro = await client.get("/api/context/macro")
            industry = await client.get("/api/context/industry", params={"industry_key": "consumer_electronics"})
            macro_detail = await client.get(f"/api/context/macro/{macro.json()[0]['id']}")
            industry_detail = await client.get(f"/api/context/industry/{industry.json()[0]['id']}")

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(macro_detail.status_code, 200)
        self.assertEqual(industry_detail.status_code, 200)
        self.assertEqual(macro.json()[0]["active_themes"][0]["key"], "fed_policy")
        self.assertEqual(industry.json()[0]["industry_key"], "consumer_electronics")
        self.assertEqual(macro_detail.json()["summary_text"], "Fed and yields remain the dominant macro themes.")
        self.assertEqual(industry_detail.json()["industry_key"], "consumer_electronics")

    async def test_context_and_recommendation_plan_routes_list_new_redesign_models(self) -> None:
        self.seed_context_and_recommendation_plan_data()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            macro = await client.get("/api/context/macro")
            industry = await client.get("/api/context/industry", params={"industry_key": "consumer_electronics"})
            ticker_signals = await client.get("/api/context/ticker-signals", params={"ticker": "AAPL"})
            signal_id = ticker_signals.json()[0]["id"]
            ticker_signal_by_id = await client.get("/api/context/ticker-signals", params={"snapshot_id": signal_id})
            plans = await client.get("/api/recommendation-plans", params={"ticker": "AAPL", "action": "long"})
            macro_detail = await client.get(f"/api/context/macro/{macro.json()[0]['id']}")
            industry_detail = await client.get(f"/api/context/industry/{industry.json()[0]['id']}")

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(ticker_signals.status_code, 200)
        self.assertEqual(ticker_signal_by_id.status_code, 200)
        self.assertEqual(plans.status_code, 200)
        self.assertEqual(macro.json()[0]["active_themes"][0]["key"], "fed_policy")
        self.assertEqual(industry.json()[0]["industry_key"], "consumer_electronics")
        self.assertEqual(ticker_signals.json()[0]["ticker"], "AAPL")
        self.assertEqual(len(ticker_signal_by_id.json()), 1)
        self.assertEqual(ticker_signal_by_id.json()[0]["id"], signal_id)
        self.assertEqual(macro_detail.status_code, 200)
        self.assertEqual(industry_detail.status_code, 200)
        self.assertEqual(macro_detail.json()["summary_text"], "Fed and yields remain the dominant macro themes.")
        self.assertEqual(industry_detail.json()["industry_key"], "consumer_electronics")
        self.assertEqual(ticker_signals.json()[0]["diagnostics"]["mode"], "deep_analysis")
        self.assertEqual(plans.json()["items"][0]["action"], "long")
        self.assertEqual(plans.json()["items"][0]["signal_breakdown"]["technical_setup"], 0.77)
        self.assertEqual(plans.json()["items"][0]["latest_outcome"]["outcome"], "win")
        self.assertEqual(plans.json()["items"][0]["latest_outcome"]["setup_family"], "continuation")
        self.assertEqual(plans.json()["items"][0]["latest_outcome"]["transmission_bias_label"], "tailwind")
        self.assertEqual(plans.json()["items"][0]["latest_outcome"]["transmission_bias_detail"]["label"], "tailwind")
        self.assertEqual(plans.json()["items"][0]["latest_outcome"]["context_regime_label"], "context + catalyst")
        self.assertEqual(plans.json()["items"][0]["latest_outcome"]["context_regime_detail"]["label"], "context + catalyst")
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
        self.assertEqual(detail_payload["recommendation_plans"][0]["latest_outcome"]["transmission_bias_detail"]["label"], "tailwind")
        self.assertEqual(detail_payload["recommendation_plans"][0]["latest_outcome"]["context_regime_label"], "context + catalyst")
        self.assertEqual(detail_payload["recommendation_plans"][0]["latest_outcome"]["context_regime_detail"]["label"], "context + catalyst")
        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(ticker_signals.status_code, 200)
        self.assertEqual(plans.status_code, 200)
        self.assertEqual(len(macro.json()), 1)
        self.assertEqual(len(industry.json()), 1)
        self.assertEqual(len(ticker_signals.json()), 1)
        self.assertEqual(len(plans.json()["items"]), 2)

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
            expired_plan = RecommendationPlanRepository(session).create_plan(
                RecommendationPlan(
                    ticker="NVDA",
                    horizon="1w",
                    action="long",
                    confidence_percent=58.0,
                    thesis_summary="Timing window passed without confirmation.",
                    signal_breakdown={"setup_family": "breakout"},
                )
            )
            RecommendationOutcomeRepository(session).upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=expired_plan.id or 0,
                    ticker="NVDA",
                    action="long",
                    outcome="expired",
                    status="resolved",
                    entry_touched=False,
                    entry_miss_distance_percent=0.12,
                    near_entry_miss=True,
                    direction_worked_without_entry=True,
                    confidence_bucket="50_to_64",
                    setup_family="breakout",
                    notes="Horizon elapsed.",
                )
            )
        finally:
            session.close()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plans = await client.get("/api/recommendation-plans", params={"ticker": "AAPL"})
            plan_id = plans.json()["items"][0]["id"]
            outcomes = await client.get("/api/recommendation-outcomes", params={"ticker": "AAPL"})
            summary = await client.get("/api/recommendation-outcomes/summary")
            effective_outcomes = await client.get("/api/effective-plan-outcomes", params={"ticker": "AAPL"})
            effective_summary = await client.get("/api/effective-plan-outcomes/summary")
            effective_report = await client.get("/api/effective-plan-outcomes/calibration-report")
            stats = await client.get("/api/recommendation-plans/stats")
            expired_stats = await client.get("/api/recommendation-plans/stats", params={"outcome": "expired"})
            family_filtered_summary = await client.get("/api/recommendation-outcomes/summary", params={"setup_family": "continuation"})
            setup_family_review = await client.get("/api/recommendation-outcomes/setup-family-review")
            evidence_concentration = await client.get("/api/recommendation-outcomes/evidence-concentration")
            baselines = await client.get("/api/recommendation-plans/baselines")
            filtered_plans = await client.get("/api/recommendation-plans", params={"setup_family": "continuation"})
            resolved_plans = await client.get("/api/recommendation-plans", params={"resolved": "resolved"})
            unresolved_plans = await client.get("/api/recommendation-plans", params={"resolved": "unresolved"})
            expired_plans = await client.get("/api/recommendation-plans", params={"outcome": "expired"})
            shortlisted_plans = await client.get("/api/recommendation-plans", params={"shortlisted": "true"})
            near_miss_plans = await client.get("/api/recommendation-plans", params={"entry_touched": "false", "near_entry_miss": "true", "direction_worked_without_entry": "true"})
            near_miss_outcomes = await client.get("/api/recommendation-outcomes", params={"entry_touched": "false", "near_entry_miss": "true", "direction_worked_without_entry": "true"})
            resolved_summary = await client.get("/api/recommendation-outcomes/summary", params={"resolved": "resolved"})
            expired_summary = await client.get("/api/recommendation-outcomes/summary", params={"outcome": "expired"})
            queued = await client.post("/api/recommendation-plans/evaluate", data={})
            scoped = await client.post(f"/api/recommendation-plans/{plan_id}/evaluate", data={})

        self.assertEqual(outcomes.status_code, 200)
        self.assertEqual(outcomes.json()[0]["outcome"], "win")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(effective_outcomes.status_code, 200)
        self.assertEqual(effective_outcomes.json()[0]["outcome_source"], "simulation")
        self.assertEqual(effective_summary.status_code, 200)
        self.assertEqual(effective_summary.json()["resolved_outcomes"], 2)
        self.assertEqual(effective_report.status_code, 200)
        self.assertIn("calibration_report", effective_report.json())
        self.assertEqual(summary.json()["total_outcomes"], 3)
        self.assertEqual(summary.json()["resolved_outcomes"], 2)
        self.assertEqual(summary.json()["overall_win_rate_percent"], 50.0)
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["total_plans"], 3)
        self.assertEqual(stats.json()["open_plans"], 0)
        self.assertEqual(stats.json()["expired_plans"], 1)
        self.assertEqual(stats.json()["win_rate_percent"], 50.0)
        self.assertEqual(stats.json()["win_outcomes"], 1)
        self.assertEqual(stats.json()["loss_outcomes"], 1)
        self.assertEqual(expired_stats.json()["total_plans"], 1)
        self.assertEqual(expired_stats.json()["expired_plans"], 1)
        self.assertIsNone(expired_stats.json()["win_rate_percent"])
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
        self.assertEqual(transmission_map["tailwind"]["label"], "tailwind")
        self.assertEqual(transmission_map["tailwind"]["slice_label"], "transmission bias")
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
        self.assertIn("slice_label", evidence_concentration.json()["strongest_positive_cohorts"][0])
        self.assertEqual(filtered_plans.status_code, 200)
        self.assertEqual(len(filtered_plans.json()["items"]), 1)
        self.assertEqual(filtered_plans.json()["items"][0]["ticker"], "AAPL")
        self.assertEqual(resolved_plans.status_code, 200)
        self.assertEqual(len(resolved_plans.json()["items"]), 3)
        self.assertEqual(unresolved_plans.status_code, 200)
        self.assertEqual(len(unresolved_plans.json()["items"]), 0)
        self.assertEqual(expired_plans.status_code, 200)
        self.assertEqual(len(expired_plans.json()["items"]), 1)
        self.assertEqual(expired_plans.json()["items"][0]["ticker"], "NVDA")
        self.assertEqual(shortlisted_plans.status_code, 200)
        self.assertTrue(all(item["signal_breakdown"].get("shortlisted", True) for item in shortlisted_plans.json()["items"]))
        self.assertEqual(near_miss_plans.status_code, 200)
        self.assertEqual(len(near_miss_plans.json()["items"]), 1)
        self.assertEqual(near_miss_plans.json()["items"][0]["ticker"], "NVDA")
        self.assertEqual(near_miss_outcomes.status_code, 200)
        self.assertEqual(len(near_miss_outcomes.json()), 1)
        self.assertTrue(near_miss_outcomes.json()[0]["near_entry_miss"])
        self.assertTrue(near_miss_outcomes.json()[0]["direction_worked_without_entry"])
        self.assertEqual(resolved_summary.status_code, 200)
        self.assertEqual(resolved_summary.json()["total_outcomes"], 3)
        self.assertEqual(resolved_summary.json()["resolved_outcomes"], 2)
        self.assertEqual(expired_summary.status_code, 200)
        self.assertEqual(expired_summary.json()["total_outcomes"], 1)
        self.assertEqual(expired_summary.json()["resolved_outcomes"], 0)
        self.assertEqual(baselines.status_code, 200)
        self.assertEqual(baselines.json()["total_trade_plans_reviewed"], 3)
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

    async def test_context_manual_refresh_routes_queue_runs(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            macro = await client.post("/api/context/refresh/macro", data={})
            industry = await client.post("/api/context/refresh/industry", data={})
            runs = await client.get("/api/runs")

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertEqual(macro.json()["job_type"], JobType.MACRO_CONTEXT_REFRESH.value)
        self.assertEqual(industry.json()["job_type"], JobType.INDUSTRY_CONTEXT_REFRESH.value)
        run_job_types = [item["job_type"] for item in runs.json()]
        self.assertIn(JobType.MACRO_CONTEXT_REFRESH.value, run_job_types)
        self.assertIn(JobType.INDUSTRY_CONTEXT_REFRESH.value, run_job_types)

    async def test_context_run_now_routes_execute_synchronously(self) -> None:
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
            "trade_proposer_app.api.routes.context._create_job_execution_service",
            side_effect=lambda session: StubSnapshotExecutionService(session),
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                macro = await client.post("/api/context/refresh/macro/run-now", data={})
                industry = await client.post("/api/context/refresh/industry/run-now", data={})

        self.assertEqual(macro.status_code, 200)
        self.assertEqual(industry.status_code, 200)
        self.assertTrue(macro.json()["executed"])
        self.assertTrue(industry.json()["executed"])
        self.assertEqual(macro.json()["run"]["status"], "completed")
        self.assertEqual(industry.json()["run"]["status"], "completed")
        self.assertEqual(macro.json()["artifact"]["snapshot_id"], 99)

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
