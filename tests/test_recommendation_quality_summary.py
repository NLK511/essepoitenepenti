import unittest

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from unittest.mock import Mock, patch
from trade_proposer_app.domain.models import RecommendationEvidenceConcentrationSummary, RecommendationCalibrationBucket, RecommendationCalibrationReport, RecommendationCalibrationSummary, RecommendationBaselineSummary
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.services.recommendation_quality_summary import RecommendationQualitySummaryService


import unittest

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import (
    RecommendationCalibrationReport,
    RecommendationCalibrationSummary,
    RecommendationEvidenceConcentrationSummary,
)
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.services.recommendation_quality_summary import RecommendationQualitySummaryService


def _make_calibration(resolved: int, brier: float | None, ece: float | None) -> RecommendationCalibrationSummary:
    report = None
    if brier is not None or ece is not None:
        report = RecommendationCalibrationReport(
            version_label="v1",
            sample_count=resolved,
            bins=[],
            brier_score=brier,
            expected_calibration_error=ece,
        )
    return RecommendationCalibrationSummary(
        total_outcomes=resolved,
        open_outcomes=0,
        resolved_outcomes=resolved,
        win_outcomes=0,
        loss_outcomes=0,
        no_action_outcomes=0,
        watchlist_outcomes=0,
        by_action=[],
        by_setup_family=[],
        by_transmission_bias=[],
        by_context_regime=[],
        calibration_report=report,
    )


def _make_evidence(ready: bool) -> RecommendationEvidenceConcentrationSummary:
    return RecommendationEvidenceConcentrationSummary(
        total_outcomes=100,
        open_outcomes=0,
        resolved_outcomes=100,
        win_outcomes=60,
        loss_outcomes=40,
        no_action_outcomes=0,
        watchlist_outcomes=0,
        cohorts=[],
        status="healthy" if ready else "thin",
        status_reason="ok",
        ready_for_expansion=ready,
    )


class RecommendationQualityStatusGateTests(unittest.TestCase):
    """Unit tests for the static promotion-gate logic in RecommendationQualitySummaryService.

    These tests call _quality_status and _quality_status_reason directly so
    they are independent of the full summarize() pipeline and are not affected
    by empty-DB outcomes in windowed queries.
    """

    def _status(self, resolved: int, brier: float | None, ece: float | None,
                ready: bool = True, wf_recommended: bool = True) -> str:
        calibration = _make_calibration(resolved, brier, ece)
        evidence = _make_evidence(ready)
        walk_forward: dict | None = {"promotion_recommended": wf_recommended} if wf_recommended else {"promotion_recommended": False}
        return RecommendationQualitySummaryService._quality_status(calibration, evidence, walk_forward)

    def _reason(self, resolved: int, brier: float | None, ece: float | None,
                ready: bool = True, wf_recommended: bool = True) -> str:
        calibration = _make_calibration(resolved, brier, ece)
        evidence = _make_evidence(ready)
        walk_forward: dict | None = {"promotion_recommended": wf_recommended}
        return RecommendationQualitySummaryService._quality_status_reason(calibration, evidence, walk_forward)

    # ── thin gate ─────────────────────────────────────────────────────────────

    def test_status_is_thin_when_fewer_than_20_resolved_outcomes(self) -> None:
        self.assertEqual(self._status(resolved=19, brier=0.10, ece=0.05), "thin")

    def test_status_is_thin_at_zero_outcomes(self) -> None:
        self.assertEqual(self._status(resolved=0, brier=None, ece=None), "thin")

    def test_status_is_not_thin_at_exactly_20_resolved_outcomes(self) -> None:
        result = self._status(resolved=20, brier=0.10, ece=0.05)
        self.assertNotEqual(result, "thin")

    # ── healthy gate ──────────────────────────────────────────────────────────

    def test_status_is_healthy_when_all_gates_pass(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.15, ece=0.05), "healthy")

    def test_status_is_healthy_when_brier_is_exactly_0_25(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.25, ece=0.05), "healthy")

    def test_status_is_healthy_when_ece_is_exactly_0_15(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.10, ece=0.15), "healthy")

    def test_status_is_healthy_when_calibration_report_is_missing(self) -> None:
        # None brier/ece means no calibration data yet; gates treat None as passing
        self.assertEqual(self._status(resolved=100, brier=None, ece=None), "healthy")

    def test_status_is_not_healthy_when_brier_just_exceeds_threshold(self) -> None:
        result = self._status(resolved=100, brier=0.26, ece=0.05)
        self.assertNotEqual(result, "healthy")

    def test_status_is_not_healthy_when_ece_just_exceeds_threshold(self) -> None:
        result = self._status(resolved=100, brier=0.10, ece=0.16)
        self.assertNotEqual(result, "healthy")

    def test_status_is_not_healthy_when_evidence_not_ready(self) -> None:
        result = self._status(resolved=100, brier=0.10, ece=0.05, ready=False)
        self.assertNotEqual(result, "healthy")

    def test_status_is_not_healthy_when_walk_forward_not_recommended(self) -> None:
        result = self._status(resolved=100, brier=0.10, ece=0.05, wf_recommended=False)
        self.assertNotEqual(result, "healthy")

    def test_status_is_not_healthy_when_walk_forward_is_none(self) -> None:
        calibration = _make_calibration(100, 0.10, 0.05)
        evidence = _make_evidence(True)
        result = RecommendationQualitySummaryService._quality_status(calibration, evidence, None)
        self.assertNotEqual(result, "healthy")

    # ── needs_attention gate ──────────────────────────────────────────────────

    def test_status_is_needs_attention_when_brier_exceeds_0_35(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.36, ece=0.05), "needs_attention")

    def test_status_is_needs_attention_when_brier_is_exactly_0_35_boundary(self) -> None:
        # 0.35 itself does NOT trigger needs_attention (strict >)
        result = self._status(resolved=100, brier=0.35, ece=0.05)
        self.assertNotEqual(result, "needs_attention")

    def test_status_is_needs_attention_when_ece_exceeds_0_20(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.10, ece=0.21), "needs_attention")

    def test_status_is_needs_attention_when_ece_is_exactly_0_20_boundary(self) -> None:
        # 0.20 itself does NOT trigger needs_attention (strict >)
        result = self._status(resolved=100, brier=0.10, ece=0.20)
        self.assertNotEqual(result, "needs_attention")

    def test_status_is_needs_attention_when_both_brier_and_ece_are_bad(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.40, ece=0.25), "needs_attention")

    # ── watch fallback ────────────────────────────────────────────────────────

    def test_status_is_watch_when_brier_between_thresholds_and_evidence_not_ready(self) -> None:
        # brier 0.30 is > 0.25 (so not healthy) but <= 0.35 (so not needs_attention)
        self.assertEqual(self._status(resolved=100, brier=0.30, ece=0.05, ready=False), "watch")

    def test_status_is_watch_when_walk_forward_not_recommended_and_calibration_acceptable(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.20, ece=0.10, wf_recommended=False), "watch")

    # ── reason strings ────────────────────────────────────────────────────────

    def test_reason_mentions_thin_when_not_enough_outcomes(self) -> None:
        reason = self._reason(resolved=5, brier=0.10, ece=0.05)
        self.assertIn("few resolved", reason.lower())

    def test_reason_mentions_calibration_error_when_brier_high(self) -> None:
        reason = self._reason(resolved=100, brier=0.40, ece=0.05)
        self.assertIn("calibration error", reason.lower())

    def test_reason_mentions_evidence_when_not_ready(self) -> None:
        reason = self._reason(resolved=100, brier=0.10, ece=0.05, ready=False)
        self.assertIn("evidence", reason.lower())

    def test_reason_mentions_walk_forward_when_not_recommended(self) -> None:
        reason = self._reason(resolved=100, brier=0.10, ece=0.05, wf_recommended=False)
        self.assertIn("walk-forward", reason.lower())

    def test_reason_positive_when_all_gates_pass(self) -> None:
        reason = self._reason(resolved=100, brier=0.10, ece=0.05)
        # Should mention alignment of calibration, evidence, walk-forward
        self.assertIn("aligned", reason.lower())


class RecommendationQualitySummaryIntegrationTests(unittest.TestCase):
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
