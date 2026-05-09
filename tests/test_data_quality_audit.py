from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import unittest

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.persistence.models import (
    Base,
    BrokerOrderExecutionRecord,
    HistoricalMarketBarRecord,
    HistoricalNewsRecord,
    WatchlistRecord,
)
from trade_proposer_app.services.data_quality_audit import DataQualityAuditService


class DataQualityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous_single_user_auth_enabled = settings.single_user_auth_enabled
        settings.single_user_auth_enabled = False
        self.engine = create_engine("sqlite:///:memory:", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.session = Session(bind=self.engine)
        self.session.add(WatchlistRecord(name="Audit List", tickers_csv="GOOD,NOBARS,REJECT", description="", region="US"))
        self.session.add(
            HistoricalMarketBarRecord(
                ticker="GOOD",
                timeframe="1d",
                bar_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
                open_price=10,
                high_price=11,
                low_price=9,
                close_price=10.5,
            )
        )
        self.session.add(
            HistoricalNewsRecord(
                ticker="GOOD",
                published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                title="Good ticker news",
                link="https://example.test/good",
                provider="test",
            )
        )
        self.session.add(
            HistoricalMarketBarRecord(
                ticker="REJECT",
                timeframe="1d",
                bar_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
                open_price=10,
                high_price=11,
                low_price=9,
                close_price=10.5,
            )
        )
        self.session.add(
            HistoricalNewsRecord(
                ticker="REJECT",
                published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                title="Rejected ticker news",
                link="https://example.test/reject",
                provider="test",
            )
        )
        self.session.add(
            BrokerOrderExecutionRecord(
                broker="alpaca",
                account_mode="paper",
                recommendation_plan_id=1,
                recommendation_plan_ticker="REJECT",
                ticker="REJECT",
                action="long",
                side="buy",
                order_type="limit",
                quantity=1,
                status="failed",
                client_order_id="reject-1",
                error_message='asset "REJECT" not found',
            )
        )
        self.session.commit()

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_db_session, None)
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        self.session.close()
        self.engine.dispose()

    def test_service_separates_missing_coverage_from_broker_rejects(self) -> None:
        payload = DataQualityAuditService(self.session).summarize(now=datetime(2026, 5, 3, tzinfo=timezone.utc))
        by_ticker = {item["ticker"]: item for item in payload["items"]}

        self.assertNotIn("GOOD", by_ticker)
        self.assertIn("NOBARS", by_ticker)
        self.assertIn("no_bars", by_ticker["NOBARS"]["issues"])
        self.assertIn("no_news", by_ticker["NOBARS"]["issues"])
        self.assertIn("REJECT", by_ticker)
        self.assertEqual(by_ticker["REJECT"]["issues"], ["broker_rejected"])
        self.assertEqual(payload["issue_counts"]["broker_rejected"], 1)

    def test_route_exposes_audit(self) -> None:
        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db_session] = override_db_session

        async def _run() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/api/data-quality/audit?ticker=REJECT")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["ticker"], "REJECT")
            self.assertEqual(payload["items"][0]["ticker"], "REJECT")
            self.assertIn("broker_rejected", payload["items"][0]["issues"])

        asyncio.run(_run())
