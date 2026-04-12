import unittest

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.services.recommendation_quality_summary import RecommendationQualitySummaryService


class RecommendationQualitySummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous_single_user_auth_enabled = settings.single_user_auth_enabled
        settings.single_user_auth_enabled = False
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)

        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        self._override = override_db_session
        app.dependency_overrides[get_db_session] = override_db_session

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_db_session, None)
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        self.engine.dispose()

    def test_service_produces_consolidated_summary(self) -> None:
        session = Session(bind=self.engine)
        try:
            payload = RecommendationQualitySummaryService(session).summarize()
            self.assertIn(payload["summary"]["status"], {"thin", "watch", "needs_attention", "healthy"})
            self.assertIn("next_actions", payload)
            self.assertTrue(payload["next_actions"])
            self.assertIn("calibration", payload)
            self.assertIn("status_reason", payload["summary"])
            self.assertIn("tuning_settings", payload["summary"])
            self.assertIn("baselines", payload)
            self.assertIn("evidence_concentration", payload)
            self.assertIn("windowed_summaries", payload)
            self.assertEqual(["7d", "30d", "90d", "180d", "1y"], [item["window_label"] for item in payload["windowed_summaries"]])
            self.assertEqual("30d", payload["summary"]["window_label"])
        finally:
            session.close()

    def test_api_exposes_consolidated_summary(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async def _run() -> None:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/api/recommendation-quality/summary")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIn("summary", payload)
                self.assertIn("next_actions", payload)
                self.assertIn("calibration", payload)
                self.assertIn("windowed_summaries", payload)

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
