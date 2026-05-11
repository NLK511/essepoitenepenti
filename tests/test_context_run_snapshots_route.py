import unittest
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository


class ContextRunSnapshotsRouteTests(unittest.IsolatedAsyncioTestCase):
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

        app.dependency_overrides[get_db_session] = override_db_session

    async def asyncTearDown(self) -> None:
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        app.dependency_overrides.clear()

    async def test_run_snapshots_returns_latest_macro_and_industry_by_run(self) -> None:
        now = datetime.now(timezone.utc)
        session = Session(bind=self.engine)
        try:
            repository = ContextSnapshotRepository(session)
            repository.create_macro_context_snapshot(
                MacroContextSnapshot(run_id=101, computed_at=now - timedelta(minutes=10), summary_text="old macro")
            )
            repository.create_macro_context_snapshot(
                MacroContextSnapshot(run_id=101, computed_at=now, summary_text="new macro")
            )
            repository.create_macro_context_snapshot(
                MacroContextSnapshot(run_id=202, computed_at=now, summary_text="other macro")
            )
            repository.create_industry_context_snapshot(
                IndustryContextSnapshot(run_id=101, industry_key="software", industry_label="Software", computed_at=now, summary_text="software")
            )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/context/run-snapshots", params={"run_ids": "101,202,303"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["macro_context_by_run"]["101"]["summary_text"], "new macro")
        self.assertEqual(payload["macro_context_by_run"]["202"]["summary_text"], "other macro")
        self.assertNotIn("303", payload["macro_context_by_run"])
        self.assertEqual(payload["industry_context_by_run"]["101"]["industry_key"], "software")
        self.assertNotIn("202", payload["industry_context_by_run"])

    async def test_run_snapshots_rejects_invalid_run_ids(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/context/run-snapshots", params={"run_ids": "101,nope"})

        self.assertEqual(response.status_code, 400)
