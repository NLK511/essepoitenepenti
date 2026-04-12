"""
Comprehensive test suite for RecommendationQualitySummaryService.

Design principles:
  - Test static quality status gates (thin, healthy, needs_attention, watch) and reasons.
  - Test the integration of windowed summaries (7d, 30d, 90d, 180d, 1y).
  - Test generating next actions based on summary data.
  - Test the final API response shape.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

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


# ─── Pure Unit Tests (Gates and Helpers) ──────────────────────────────────────

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
        resolved_outcomes=resolved,
        calibration_report=report,
    )


def _make_evidence(ready: bool) -> RecommendationEvidenceConcentrationSummary:
    return RecommendationEvidenceConcentrationSummary(
        ready_for_expansion=ready,
    )


class RecommendationQualityStatusGateTests(unittest.TestCase):
    """Unit tests for the static promotion-gate logic in RecommendationQualitySummaryService."""

    def _status(self, resolved: int, brier: float | None, ece: float | None,
                ready: bool = True, wf_recommended: bool = True) -> str:
        calibration = _make_calibration(resolved, brier, ece)
        evidence = _make_evidence(ready)
        walk_forward = {"promotion_recommended": wf_recommended}
        return RecommendationQualitySummaryService._quality_status(calibration, evidence, walk_forward)

    def _reason(self, resolved: int, brier: float | None, ece: float | None,
                ready: bool = True, wf_recommended: bool = True) -> str:
        calibration = _make_calibration(resolved, brier, ece)
        evidence = _make_evidence(ready)
        walk_forward = {"promotion_recommended": wf_recommended}
        return RecommendationQualitySummaryService._quality_status_reason(calibration, evidence, walk_forward)

    # ── thin gate ──

    def test_status_is_thin_when_fewer_than_20_resolved_outcomes(self) -> None:
        self.assertEqual(self._status(resolved=19, brier=0.10, ece=0.05), "thin")

    def test_status_is_not_thin_at_exactly_20_resolved_outcomes(self) -> None:
        result = self._status(resolved=20, brier=0.10, ece=0.05)
        self.assertNotEqual(result, "thin")

    # ── healthy gate ──

    def test_status_is_healthy_when_all_gates_pass(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.15, ece=0.05), "healthy")

    def test_status_is_not_healthy_when_brier_exceeds_0_25(self) -> None:
        self.assertNotEqual(self._status(resolved=100, brier=0.26, ece=0.05), "healthy")

    def test_status_is_not_healthy_when_ece_exceeds_0_15(self) -> None:
        self.assertNotEqual(self._status(resolved=100, brier=0.10, ece=0.16), "healthy")

    def test_status_is_not_healthy_when_evidence_not_ready(self) -> None:
        self.assertNotEqual(self._status(resolved=100, brier=0.10, ece=0.05, ready=False), "healthy")

    def test_status_is_not_healthy_when_walk_forward_not_recommended(self) -> None:
        self.assertNotEqual(self._status(resolved=100, brier=0.10, ece=0.05, wf_recommended=False), "healthy")

    # ── needs_attention gate ──

    def test_status_is_needs_attention_when_brier_exceeds_0_35(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.36, ece=0.05), "needs_attention")

    def test_status_is_needs_attention_when_ece_exceeds_0_20(self) -> None:
        self.assertEqual(self._status(resolved=100, brier=0.10, ece=0.21), "needs_attention")

    # ── watch fallback ──

    def test_status_is_watch_when_signals_are_mixed(self) -> None:
        # Passable but not "healthy" (brier > 0.25)
        self.assertEqual(self._status(resolved=100, brier=0.30, ece=0.05), "watch")

    # ── reason strings ──

    def test_reason_mentions_thin_when_low_sample(self) -> None:
        self.assertIn("Too few", self._reason(resolved=5, brier=0.1, ece=0.05))

    def test_reason_mentions_calibration_error_when_high_error(self) -> None:
        self.assertIn("error is elevated", self._reason(resolved=100, brier=0.40, ece=0.05))

    def test_reason_positive_when_all_aligned(self) -> None:
        self.assertIn("are aligned", self._reason(resolved=100, brier=0.1, ece=0.05))


class RecommendationQualityNextActionsTests(unittest.TestCase):
    """Verify that _next_actions generated helpful advice."""

    svc = RecommendationQualitySummaryService

    def test_advises_increasing_volume_when_thin(self) -> None:
        summary = {"resolved_outcomes": 5}
        actions = self.svc._next_actions(summary)
        self.assertIn("Increase resolved outcome volume", actions[0])

    def test_advises_keeping_evidence_conservative_when_not_ready_for_expansion(self) -> None:
        summary = {"ready_for_expansion": False, "resolved_outcomes": 100}
        actions = self.svc._next_actions(summary)
        self.assertIn("Keep evidence concentration conservative", actions[0])

    def test_advises_tightening_calibration_when_brier_is_high(self) -> None:
        summary = {"calibration_report": {"brier_score": 0.36}, "resolved_outcomes": 100, "ready_for_expansion": True, "walk_forward_promotion_recommended": True}
        actions = self.svc._next_actions(summary)
        self.assertIn("Tighten calibration", actions[0])

    def test_advises_tightening_calibration_when_ece_is_high(self) -> None:
        summary = {"calibration_report": {"expected_calibration_error": 0.21}, "resolved_outcomes": 100, "ready_for_expansion": True, "walk_forward_promotion_recommended": True}
        actions = self.svc._next_actions(summary)
        self.assertIn("Tighten calibration", actions[0])

    def test_advises_maintenance_when_all_good(self) -> None:
        summary = {"resolved_outcomes": 100, "ready_for_expansion": True, "walk_forward_promotion_recommended": True, "calibration_report": {"brier_score": 0.15}}
        actions = self.svc._next_actions(summary)
        self.assertIn("Maintain the current settings", actions[0])


# ─── Integration Tests ────────────────────────────────────────────────────────

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
            self.assertIn("summary", payload)
            self.assertIn("windowed_summaries", payload)
            self.assertIn("calibration", payload)
            self.assertIn("next_actions", payload)
            
            # Verify windowed summary count matches definitions
            self.assertEqual(len(payload["windowed_summaries"]), len(RecommendationQualitySummaryService.WINDOW_DEFINITIONS))
            
            # Default window should be 30d
            self.assertEqual(payload["summary"]["window_label"], "30d")
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
                self.assertIn("windowed_summaries", payload)

        import asyncio
        asyncio.run(_run())


class QualitySummaryWindowIntegrityTests(unittest.TestCase):
    """Verifies that temporal windows use distinct time offsets."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)

    def test_windows_have_different_start_times(self) -> None:
        session = Session(bind=self.engine)
        service = RecommendationQualitySummaryService(session)
        payload = service.summarize()
        
        windows = {w["window_label"]: w for w in payload["windowed_summaries"]}
        
        # 7d window should have later start than 1y window
        self.assertGreater(windows["7d"]["computed_after"], windows["1y"]["computed_after"])
        self.assertGreater(windows["30d"]["computed_after"], windows["180d"]["computed_after"])

class QualitySummaryErrorHandlingTests(unittest.TestCase):
    """Verifies robustness when sub-services fail."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)

    @patch("trade_proposer_app.services.recommendation_quality_summary.PlanGenerationWalkForwardService")
    def test_handles_walk_forward_service_exception_gracefully(self, mock_wf) -> None:
        mock_instance = mock_wf.return_value
        mock_instance.summarize.side_effect = Exception("Walk-forward engine failure")
        
        session = Session(bind=self.engine)
        service = RecommendationQualitySummaryService(session)
        
        payload = service.summarize()
        # Should not crash, and should report the error in the summary
        self.assertEqual(payload["summary"]["walk_forward_error"], "Walk-forward engine failure")

class QualitySummaryAssessmentIntegrationTests(unittest.TestCase):
    """Verifies that performance assessment data is correctly included."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)

    @patch("trade_proposer_app.services.recommendation_quality_summary.PerformanceAssessmentService")
    def test_includes_latest_summary_from_performance_assessment(self, mock_perf) -> None:
        mock_perf.return_value.latest_assessment.return_value = {
            "latest_summary": {"sharpe_ratio": 2.5}
        }
        
        session = Session(bind=self.engine)
        service = RecommendationQualitySummaryService(session)
        payload = service.summarize()
        
        self.assertEqual(payload["summary"]["latest_assessment"]["sharpe_ratio"], 2.5)
