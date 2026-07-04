import unittest

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.db import get_db_session
from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.services.tuning_workflow import TuningWorkflowService


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
