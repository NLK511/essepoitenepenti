import unittest
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.db import get_db_session
from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import Base, HistoricalMarketBarRecord, HistoricalReplayBatchRecord, HistoricalReplaySliceRecord, RecommendationPlanRecord, ReplayEligibilityRecord, ReplayPlanOutcomeRecord, WatchlistRecord
from trade_proposer_app.services.tuning_workflow import TuningWorkflowService


class FakeReplayBatch:
    def __init__(self, batch_id: int, status: str = "planned") -> None:
        self.id = batch_id
        self.status = status


class FakeReplayService:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.next_id = 100

    def create_batch(self, **kwargs):
        self.created.append(kwargs)
        batch = FakeReplayBatch(self.next_id)
        self.next_id += 1
        return batch

    def enqueue_batch(self, batch_id: int):
        return [object(), object()]


class TuningWorkflowServiceTests(unittest.TestCase):
    def create_session(self) -> Session:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=engine)
        return Session(bind=engine)

    def test_create_experiment_defaults_and_lifecycle(self) -> None:
        session = self.create_session()
        try:
            service = TuningWorkflowService(session)
            detail = service.create_experiment({"name": "July replay tuning"})

            self.assertEqual("setup_incomplete", detail["current_stage"])
            self.assertIn("universe", detail["blockers"])
            self.assertTrue(detail["replay_settings"]["cache_only"])
            self.assertEqual(1, detail["replay_settings"]["max_concurrency"])
            self.assertEqual("paper_config", detail["promotion_target"])
            self.assertEqual("discovery-only evidence; not promotion evidence", detail["computation_labels"]["discovery"])
        finally:
            session.close()

    def test_watchlist_universe_resolves_tickers_for_readiness(self) -> None:
        session = self.create_session()
        try:
            watchlist = WatchlistRecord(name="Core growth", tickers_csv="AAPL, MSFT", default_horizon="1w")
            session.add(watchlist)
            session.commit()
            session.add_all([
                HistoricalMarketBarRecord(ticker="AAPL", timeframe="1d", bar_time=datetime(2026, 2, 2, tzinfo=timezone.utc), open_price=1, high_price=1, low_price=1, close_price=1, volume=1),
                HistoricalMarketBarRecord(ticker="MSFT", timeframe="1d", bar_time=datetime(2026, 2, 2, tzinfo=timezone.utc), open_price=1, high_price=1, low_price=1, close_price=1, volume=1),
            ])
            session.commit()
            service = TuningWorkflowService(session)
            detail = service.create_experiment(
                {
                    "name": "Watchlist universe",
                    "universe": {"watchlist_id": watchlist.id, "watchlist_name": watchlist.name},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-02-02",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-03-03",
                    },
                    "baseline": {"source": "current_active_config"},
                }
            )
            detail = service.run_readiness_audit(int(detail["id"]))
            self.assertEqual(2, detail["sections"]["evidence_readiness"]["ticker_count"])
            self.assertEqual("candidate_discovery_needed", detail["current_stage"])
        finally:
            session.close()

    def test_refresh_replay_summaries_adds_progress_and_comparison(self) -> None:
        session = self.create_session()
        try:
            service = TuningWorkflowService(session)
            detail = service.create_experiment({"name": "Replay summaries"})
            experiment_id = int(detail["id"])
            baseline_batch = HistoricalReplayBatchRecord(name="baseline-progress", status="completed", as_of_start=datetime(2026, 2, 2, tzinfo=timezone.utc), as_of_end=datetime(2026, 2, 3, tzinfo=timezone.utc))
            candidate_batch = HistoricalReplayBatchRecord(name="candidate-progress", status="completed", as_of_start=datetime(2026, 2, 2, tzinfo=timezone.utc), as_of_end=datetime(2026, 2, 3, tzinfo=timezone.utc))
            session.add_all([baseline_batch, candidate_batch])
            session.commit()
            session.add_all([
                HistoricalReplaySliceRecord(replay_batch_id=baseline_batch.id or 0, as_of=datetime(2026, 2, 2, tzinfo=timezone.utc), status="completed"),
                HistoricalReplaySliceRecord(replay_batch_id=baseline_batch.id or 0, as_of=datetime(2026, 2, 3, tzinfo=timezone.utc), status="failed"),
                HistoricalReplaySliceRecord(replay_batch_id=candidate_batch.id or 0, as_of=datetime(2026, 2, 2, tzinfo=timezone.utc), status="completed"),
            ])
            for batch_id, outcome in ((baseline_batch.id or 0, "loss"), (candidate_batch.id or 0, "win")):
                session.add(ReplayEligibilityRecord(replay_batch_id=batch_id, replay_slice_id=1, recommendation_plan_id=batch_id, ticker="AAPL", tier="tier_a", eligible_for_tuning=True, resolution_source="intraday", outcome=outcome, diagnostics_json="{}"))
                session.add(ReplayPlanOutcomeRecord(replay_batch_id=batch_id, replay_slice_id=1, recommendation_plan_id=batch_id, resolution_source="intraday", outcome=outcome, status="resolved", evaluated_at=datetime(2026, 2, 5, tzinfo=timezone.utc), outcome_json="{}"))
            session.commit()
            detail = service.generate_candidate_pool(experiment_id)
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]
            service.update_shortlist(experiment_id, [candidate_id])
            service.bind_baseline_replay_batch(experiment_id, baseline_batch.id or 0)
            service.record_candidate_replay_validation(experiment_id, {candidate_id: candidate_batch.id or 0})

            detail = service.refresh_replay_summaries(experiment_id)

            baseline = detail["sections"]["baseline_replay"]
            validation = detail["sections"]["candidate_replay_validation"]
            self.assertEqual(2, baseline["progress"]["slice_count"])
            self.assertTrue(baseline["progress"]["has_failures_or_stale"])
            self.assertEqual(100.0, validation["comparisons"][candidate_id]["candidate_win_rate_percent"])
            self.assertEqual(100.0, validation["comparisons"][candidate_id]["win_rate_delta_percent"])
        finally:
            session.close()

    def test_manual_candidate_can_be_rejected_and_removed_from_shortlist(self) -> None:
        session = self.create_session()
        try:
            service = TuningWorkflowService(session)
            detail = service.create_experiment({"name": "Manual candidates"})
            experiment_id = int(detail["id"])
            detail = service.add_manual_candidate(
                experiment_id,
                label="manual floor",
                config={"global.actionable_confidence_floor_percent": 66.0},
            )
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]
            detail = service.update_shortlist(experiment_id, [candidate_id])
            self.assertEqual([candidate_id], detail["sections"]["shortlist"]["candidate_ids"])
            detail = service.reject_candidate(experiment_id, candidate_id, reason="too similar")
            self.assertEqual([], detail["sections"]["shortlist"]["candidate_ids"])
            self.assertEqual("rejected", detail["sections"]["candidate_pool"]["candidates"][0]["status"])
        finally:
            session.close()

    def test_create_holdout_replay_batches_and_gate_table(self) -> None:
        session = self.create_session()
        try:
            fake_replay = FakeReplayService()
            service = TuningWorkflowService(session, historical_replay_service=fake_replay)
            detail = service.create_experiment(
                {
                    "name": "Holdout workflow",
                    "universe": {"tickers": ["AAPL"]},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-02-03",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-03-03",
                    },
                    "baseline": {"source": "current_active_config"},
                }
            )
            experiment_id = int(detail["id"])
            detail = service.generate_candidate_pool(experiment_id)
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]

            detail = service.create_holdout_replay_batches(experiment_id, candidate_id)
            self.assertEqual("queued", detail["sections"]["stability_validation"]["status"])
            self.assertEqual("tuning_workflow_holdout_baseline_replay", fake_replay.created[0]["config"]["source"])
            self.assertEqual("tuning_workflow_holdout_candidate_replay", fake_replay.created[1]["config"]["source"])
        finally:
            session.close()

    def test_create_replay_batches_uses_cache_only_scoped_configs(self) -> None:
        session = self.create_session()
        try:
            fake_replay = FakeReplayService()
            service = TuningWorkflowService(session, historical_replay_service=fake_replay)
            detail = service.create_experiment(
                {
                    "name": "Replay creation workflow",
                    "universe": {"tickers": ["AAPL", "MSFT"]},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-02-03",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-04-01",
                    },
                    "baseline": {"source": "rerun_baseline_replay"},
                }
            )
            experiment_id = int(detail["id"])
            detail = service.run_readiness_audit(experiment_id)
            detail = service.generate_candidate_pool(experiment_id)
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]
            service.update_shortlist(experiment_id, [candidate_id])

            detail = service.create_baseline_replay_batch(experiment_id)
            self.assertEqual("candidate_replay_needed", detail["current_stage"])
            metadata_record = service.get_experiment(experiment_id)
            metadata = __import__("json").loads(metadata_record.metadata_json)
            metadata["candidate_pool"]["candidates"][0]["validation_depth"] = "full_orchestration_replay"
            metadata_record.metadata_json = __import__("json").dumps(metadata)
            session.commit()
            detail = service.create_candidate_replay_batches(experiment_id)

            self.assertEqual("queued", detail["sections"]["candidate_replay_validation"]["status"])
            self.assertEqual(2, len(fake_replay.created))
            self.assertTrue(fake_replay.created[0]["config"]["cache_only"])
            self.assertEqual("tuning_workflow_candidate_replay", fake_replay.created[1]["config"]["source"])
            self.assertIn("plan_generation_tuning_config_override", fake_replay.created[1]["config"])
        finally:
            session.close()

    def test_lightweight_candidate_validation_reuses_baseline_without_replay_job(self) -> None:
        session = self.create_session()
        try:
            fake_replay = FakeReplayService()
            service = TuningWorkflowService(session, historical_replay_service=fake_replay)
            detail = service.create_experiment(
                {
                    "name": "Lightweight validation",
                    "universe": {"tickers": ["AAPL"]},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-02-03",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-04-01",
                    },
                    "baseline": {"source": "existing_replay_batch"},
                }
            )
            experiment_id = int(detail["id"])
            baseline_batch = HistoricalReplayBatchRecord(name="baseline-lightweight", status="completed", as_of_start=datetime(2026, 2, 2, tzinfo=timezone.utc), as_of_end=datetime(2026, 2, 3, tzinfo=timezone.utc))
            session.add(baseline_batch)
            session.commit()
            slice_record = HistoricalReplaySliceRecord(replay_batch_id=baseline_batch.id or 0, as_of=datetime(2026, 2, 2, tzinfo=timezone.utc), status="completed")
            plan = RecommendationPlanRecord(ticker="AAPL", action="long", confidence_percent=70, entry_price_low=99, entry_price_high=101, stop_loss=95, take_profit=110, evidence_summary_json='{"setup_family":"breakout"}', signal_breakdown_json="{}")
            session.add_all([slice_record, plan])
            session.commit()
            outcome = ReplayPlanOutcomeRecord(replay_batch_id=baseline_batch.id or 0, replay_slice_id=slice_record.id or 0, recommendation_plan_id=plan.id or 0, resolution_source="intraday", outcome="win", status="resolved", outcome_json="{}")
            session.add(outcome)
            session.commit()
            eligibility = ReplayEligibilityRecord(replay_batch_id=baseline_batch.id or 0, replay_slice_id=slice_record.id or 0, replay_plan_outcome_id=outcome.id, recommendation_plan_id=plan.id or 0, ticker="AAPL", tier="tier_a", eligible_for_tuning=True, resolution_source="intraday", outcome="win", diagnostics_json='{"setup_family":"breakout"}')
            session.add(eligibility)
            session.commit()

            service.bind_baseline_replay_batch(experiment_id, baseline_batch.id or 0)
            detail = service.generate_candidate_pool(experiment_id)
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]
            service.update_shortlist(experiment_id, [candidate_id])
            detail = service.create_candidate_replay_batches(experiment_id)

            payload = detail["sections"]["candidate_replay_validation"]["candidate_batches"][candidate_id]
            self.assertEqual("rescore_only", payload["validation_depth"])
            self.assertEqual(0, payload["queued_run_count"])
            self.assertTrue(payload["source_frozen_inputs_reused"])
            self.assertEqual(0, len(fake_replay.created))
            self.assertEqual(1, payload["summary"]["tier_a_count"])
        finally:
            session.close()

    def test_candidate_replay_is_blocked_by_hard_readiness_failure(self) -> None:
        session = self.create_session()
        try:
            service = TuningWorkflowService(session, historical_replay_service=FakeReplayService())
            detail = service.create_experiment(
                {
                    "name": "Blocked replay",
                    "universe": {"tickers": ["AAPL"]},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-02-03",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-04-01",
                    },
                    "baseline": {"source": "current_active_config"},
                }
            )
            experiment_id = int(detail["id"])
            service.run_readiness_audit(experiment_id)
            detail = service.generate_candidate_pool(experiment_id)
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]
            service.update_shortlist(experiment_id, [candidate_id])
            metadata_record = service.get_experiment(experiment_id)
            metadata_record.metadata_json = metadata_record.metadata_json.replace('"status":"warning"', '"status":"blocked"')
            session.commit()
            with self.assertRaisesRegex(Exception, "readiness audit"):
                service.create_candidate_replay_batches(experiment_id)
        finally:
            session.close()

    def test_workflow_actions_move_to_blocked_promotion_proposal(self) -> None:
        session = self.create_session()
        try:
            service = TuningWorkflowService(session)
            detail = service.create_experiment(
                {
                    "name": "End to end tuning setup",
                    "universe": {"tickers": ["AAPL"]},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-02-03",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-04-01",
                    },
                    "baseline": {"source": "current_active_config"},
                }
            )
            experiment_id = int(detail["id"])
            for day in (2, 3):
                session.add(HistoricalMarketBarRecord(ticker="AAPL", timeframe="1d", bar_time=datetime(2026, 2, day, tzinfo=timezone.utc), open_price=1, high_price=1, low_price=1, close_price=1))
            baseline_batch = HistoricalReplayBatchRecord(name="baseline", status="completed", as_of_start=datetime(2026, 2, 2, tzinfo=timezone.utc), as_of_end=datetime(2026, 2, 3, tzinfo=timezone.utc))
            candidate_batch = HistoricalReplayBatchRecord(name="candidate", status="completed", as_of_start=datetime(2026, 2, 2, tzinfo=timezone.utc), as_of_end=datetime(2026, 2, 3, tzinfo=timezone.utc))
            session.add_all([baseline_batch, candidate_batch])
            session.commit()

            detail = service.run_readiness_audit(experiment_id)
            self.assertEqual("candidate_discovery_needed", detail["current_stage"])
            detail = service.generate_candidate_pool(experiment_id)
            candidate_id = detail["sections"]["candidate_pool"]["candidates"][0]["id"]
            detail = service.update_shortlist(experiment_id, [candidate_id])
            self.assertEqual("baseline_needed", detail["current_stage"])
            detail = service.bind_baseline_replay_batch(experiment_id, baseline_batch.id or 0)
            self.assertEqual("candidate_replay_needed", detail["current_stage"])
            detail = service.record_candidate_replay_validation(experiment_id, {candidate_id: candidate_batch.id or 0})
            self.assertEqual("stability_validation_needed", detail["current_stage"])
            detail = service.record_stability_validation(experiment_id, candidate_id, status="warning", notes="needs holdout")
            detail = service.create_promotion_proposal(experiment_id, candidate_id)
            self.assertEqual("blocked", detail["current_stage"])
            self.assertIn("holdout/stability validation has not passed", detail["blockers"])
            self.assertTrue(any(gate["gate"] == "holdout_stability" and gate["status"] == "block" for gate in detail["sections"]["promotion_proposal"]["gate_table"]))
            detail = service.record_stability_validation(experiment_id, candidate_id, status="pass", notes="holdout passed")
            detail = service.create_promotion_proposal(experiment_id, candidate_id)
            self.assertEqual("recommended_for_paper", detail["current_stage"])
            detail = service.execute_paper_promotion(experiment_id, reason="test promotion")
            self.assertEqual("paper_promoted", detail["current_stage"])
            self.assertEqual("paper_config_created", detail["sections"]["promotion_execution"]["status"])
            self.assertEqual("pending_paper_trial", detail["sections"]["post_promotion_monitoring"]["status"])
            detail = service.extend_paper_trial(experiment_id, days=14, reason="more evidence")
            self.assertEqual("paper_trial_extended", detail["sections"]["post_promotion_monitoring"]["status"])
            detail = service.rollback_paper_promotion(experiment_id, reason="failed paper trial")
            self.assertEqual("rolled_back", detail["current_stage"])
            self.assertEqual("rolled_back", detail["sections"]["rollback"]["status"])
        finally:
            session.close()

    def test_complete_setup_moves_to_readiness_needed(self) -> None:
        session = self.create_session()
        try:
            service = TuningWorkflowService(session)
            detail = service.create_experiment(
                {
                    "name": "Complete tuning setup",
                    "universe": {"tickers": ["AAPL", "MSFT"]},
                    "windows": {
                        "discovery_start": "2026-01-01",
                        "discovery_end": "2026-02-01",
                        "replay_start": "2026-02-02",
                        "replay_end": "2026-03-01",
                        "holdout_start": "2026-03-02",
                        "holdout_end": "2026-04-01",
                    },
                    "baseline": {"source": "current_active_config"},
                    "objective": "tier_a_win_rate",
                }
            )

            self.assertEqual("readiness_needed", detail["current_stage"])
            self.assertEqual([], detail["blockers"])
            self.assertTrue(detail["setup_completeness"]["complete"])
        finally:
            session.close()


class TuningWorkflowRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)
        self.original_auth_enabled = settings.single_user_auth_enabled
        settings.single_user_auth_enabled = False

        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db_session] = override_db_session

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    async def test_create_get_list_update_archive_experiment(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_response = await client.post("/api/tuning-workflow/experiments", json={"name": "Workflow v1"})
            self.assertEqual(200, create_response.status_code)
            created = create_response.json()["experiment"]
            experiment_id = created["id"]

            list_response = await client.get("/api/tuning-workflow/experiments")
            self.assertEqual(200, list_response.status_code)
            self.assertEqual(1, list_response.json()["count"])

            patch_response = await client.patch(
                f"/api/tuning-workflow/experiments/{experiment_id}",
                json={"notes": "updated", "objective": "expected_value"},
            )
            self.assertEqual(200, patch_response.status_code)
            self.assertEqual("expected_value", patch_response.json()["experiment"]["objective"])

            get_response = await client.get(f"/api/tuning-workflow/experiments/{experiment_id}")
            self.assertEqual(200, get_response.status_code)
            self.assertEqual("updated", get_response.json()["experiment"]["notes"])

            archive_response = await client.post(f"/api/tuning-workflow/experiments/{experiment_id}/archive")
            self.assertEqual(200, archive_response.status_code)
            self.assertEqual("archived", archive_response.json()["experiment"]["current_stage"])

            active_list_response = await client.get("/api/tuning-workflow/experiments")
            self.assertEqual(0, active_list_response.json()["count"])

            all_list_response = await client.get("/api/tuning-workflow/experiments?include_archived=true")
            self.assertEqual(1, all_list_response.json()["count"])

    async def test_route_rejects_unsupported_objective(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/tuning-workflow/experiments", json={"name": "bad", "objective": "profit_always"})
        self.assertEqual(400, response.status_code)
        self.assertIn("unsupported objective", response.text)
