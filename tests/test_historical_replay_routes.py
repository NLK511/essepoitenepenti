import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.persistence.models import Base


class HistoricalReplayRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._previous_single_user_auth_enabled = settings.single_user_auth_enabled
        self._previous_weights_file_path = settings.weights_file_path
        settings.single_user_auth_enabled = False

        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)
        self.weights_root = TemporaryDirectory()
        settings.weights_file_path = str(Path(self.weights_root.name) / "weights.json")

        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db_session] = override_db_session

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        settings.weights_file_path = self._previous_weights_file_path
        self.weights_root.cleanup()

    async def test_create_hydrate_and_execute_historical_replay_batch(self) -> None:
        provider_payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1704067200, 1704153600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, 101.0],
                                    "high": [101.0, 102.0],
                                    "low": [99.0, 100.0],
                                    "close": [100.5, 101.5],
                                    "volume": [1000, 1200],
                                }
                            ],
                            "adjclose": [{"adjclose": [100.25, 101.25]}],
                        },
                    }
                ]
            }
        }
        response = unittest.mock.MagicMock()
        response.status_code = 200
        response.json.return_value = provider_payload

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            presets_response = await client.get("/api/historical-replay/universe-presets")
            self.assertEqual(200, presets_response.status_code)
            self.assertGreaterEqual(len(presets_response.json()), 2)

            create_response = await client.post(
                "/api/historical-replay/batches",
                data={
                    "name": "API replay",
                    "mode": "research",
                    "as_of_start": "2024-01-01",
                    "as_of_end": "2024-01-02",
                    "cadence": "daily",
                    "universe_preset": "us_large_cap_top20_v1",
                    "entry_timing": "next_open",
                    "price_provider": "yahoo",
                },
            )
            self.assertEqual(200, create_response.status_code)
            batch = create_response.json()
            self.assertEqual("planned", batch["status"])
            self.assertEqual("us_large_cap_top20_v1", batch["universe_preset"])

            list_response = await client.get("/api/historical-replay/batches")
            self.assertEqual(200, list_response.status_code)
            self.assertEqual(1, len(list_response.json()))

            detail_response = await client.get(f"/api/historical-replay/batches/{batch['id']}")
            self.assertEqual(200, detail_response.status_code)
            detail_payload = detail_response.json()
            self.assertEqual(2, len(detail_payload["slices"]))
            self.assertEqual(2, detail_payload["summary"]["slice_count"])
            self.assertEqual(20, len(detail_payload["resolved_tickers"]))

            with patch("trade_proposer_app.services.historical_market_data.httpx.get", return_value=response):
                hydrate_response = await client.post(f"/api/historical-replay/batches/{batch['id']}/hydrate-market-data")
            self.assertEqual(200, hydrate_response.status_code)
            hydration_payload = hydrate_response.json()
            self.assertEqual("yahoo", hydration_payload["provider"])
            self.assertEqual(20, hydration_payload["ticker_count"])

            execute_response = await client.post(f"/api/historical-replay/batches/{batch['id']}/execute")
            self.assertEqual(200, execute_response.status_code)
            execution_payload = execute_response.json()
            self.assertEqual(2, execution_payload["queued_run_count"])
            self.assertEqual(2, len(execution_payload["run_ids"]))
