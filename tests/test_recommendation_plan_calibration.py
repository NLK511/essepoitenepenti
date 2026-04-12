"""
Comprehensive test suite for RecommendationPlanCalibrationService.

Design principles:
  - Verify exact Brier score and Expected Calibration Error (ECE) math.
  - Verify smoothing logic pulls predictions toward the global average.
  - Verify grouping and bucketization by all dimensions.
  - Verify sample status transitions (insufficient -> limited -> usable -> strong).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from trade_proposer_app.domain.models import RecommendationPlanOutcome
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService


class RecommendationPlanCalibrationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.outcomes_repo = Mock(spec=RecommendationOutcomeRepository)
        self.service = RecommendationPlanCalibrationService(self.outcomes_repo)

    # ─── Brier and ECE Math ───────────────────────────────────────────────────

    def test_brier_score_and_ece_exact_math_without_smoothing(self) -> None:
        """
        Verify hand-computed Brier and ECE for a two-bin scenario.

        Bin 1 (80_90): 10 items @ 80% confidence. 8 wins, 2 losses.
          avg_predicted = 0.8, avg_actual = 0.8
          bin_brier = (8 * (0.8-1.0)^2 + 2 * (0.8-0.0)^2) / 10 = (8 * 0.04 + 2 * 0.64) / 10 = (0.32 + 1.28) / 10 = 0.16
          bin_ece = abs(0.8 - 0.8) = 0.0

        Bin 2 (20_40): 4 items @ 25% confidence. 1 win, 3 losses.
          avg_predicted = 0.25, avg_actual = 0.25
          bin_brier = (1 * (0.25-1.0)^2 + 3 * (0.25-0.0)^2) / 4 = (1 * 0.5625 + 3 * 0.0625) / 4 = (0.5625 + 0.1875) / 4 = 0.1875
          bin_ece = abs(0.25 - 0.25) = 0.0

        Total:
          brier = (10 * 0.16 + 4 * 0.1875) / 14 = (1.6 + 0.75) / 14 = 2.35 / 14 = 0.167857...
          ece = (10 * 0.0 + 4 * 0.0) / 14 = 0.0
        """
        outcomes = []
        for _ in range(8):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", confidence_percent=80.0))
        for _ in range(2):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=2, outcome="loss", confidence_percent=80.0))
        for _ in range(1):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=3, outcome="win", confidence_percent=25.0))
        for _ in range(3):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=4, outcome="loss", confidence_percent=25.0))

        report = self.service._build_calibration_report(
            outcomes, method="test", version_label="v1", smoothing_strength=0.0
        )
        
        self.assertIsNotNone(report)
        self.assertEqual(report.sample_count, 14)
        self.assertAlmostEqual(report.brier_score, 0.1679, places=4)
        self.assertAlmostEqual(report.expected_calibration_error, 0.0, places=4)

    def test_ece_computes_exact_calibration_error_when_mismatched(self) -> None:
        """
        10 items predicted at 90% confidence, but only 5 wins (50% actual).
        ECE for this bin = abs(0.9 - 0.5) = 0.4.
        """
        outcomes = []
        for _ in range(5):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", confidence_percent=90.0))
        for _ in range(5):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=2, outcome="loss", confidence_percent=90.0))

        report = self.service._build_calibration_report(
            outcomes, method="test", version_label="v1", smoothing_strength=0.0
        )
        
        self.assertIsNotNone(report)
        self.assertEqual(report.sample_count, 10)
        self.assertAlmostEqual(report.expected_calibration_error, 0.4, places=4)

    def test_smoothing_strength_pulls_predictions_toward_global_average(self) -> None:
        """
        Formula: smoothed_predicted = ((avg_predicted * n) + (overall_prob * strength)) / (n + strength)

        Bin 90_100: 5 items @ 90% (all wins → avg_actual = 1.0).
        Bin 0_20: 5 items @ 10% (all losses → avg_actual = 0.0).
        Global win rate = 5 / 10 = 0.5.

        With strength = 5.0:
          Bin 90_100: ((0.9 * 5) + (0.5 * 5)) / (5 + 5) = (4.5 + 2.5) / 10 = 0.7
          Bin 0_20: ((0.1 * 5) + (0.5 * 5)) / (5 + 5) = (0.5 + 2.5) / 10 = 0.3
        """
        outcomes = []
        for _ in range(5):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", confidence_percent=90.0))
        for _ in range(5):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=2, outcome="loss", confidence_percent=10.0))

        report = self.service._build_calibration_report(
            outcomes, method="test", version_label="v1", smoothing_strength=5.0
        )
        
        self.assertIsNotNone(report)
        bin_90 = next(b for b in report.bins if b.bin_key == "90_100")
        bin_0 = next(b for b in report.bins if b.bin_key == "0_20")
        
        self.assertAlmostEqual(bin_90.predicted_probability, 0.7, places=4)
        self.assertAlmostEqual(bin_0.predicted_probability, 0.3, places=4)

    # ─── Grouping and Bucketization ───────────────────────────────────────────

    def test_summarize_groups_by_all_supported_dimensions(self) -> None:
        """Verify summarize() populates groups for setup family, action, etc."""
        outcomes = [
            RecommendationPlanOutcome(
                recommendation_plan_id=1, ticker="AAPL", action="long", outcome="win",
                confidence_percent=80.0, confidence_bucket="80_plus",
                setup_family="breakout", horizon="1w", transmission_bias="bullish",
                context_regime="risk_on"
            ),
            RecommendationPlanOutcome(
                recommendation_plan_id=2, ticker="TSLA", action="short", outcome="loss",
                confidence_percent=60.0, confidence_bucket="50_to_64",
                setup_family="continuation", horizon="1d", transmission_bias="bearish",
                context_regime="risk_off"
            ),
        ]
        self.outcomes_repo.list_outcomes.return_value = outcomes
        
        summary = self.service.summarize()
        
        # Total counts
        self.assertEqual(summary.total_outcomes, 2)
        self.assertEqual(summary.resolved_outcomes, 2)
        self.assertEqual(summary.win_outcomes, 1)
        self.assertEqual(summary.loss_outcomes, 1)

        # Dimension checks
        self.assertEqual(len(summary.by_confidence_bucket), 2)
        self.assertEqual(len(summary.by_setup_family), 2)
        self.assertEqual(len(summary.by_action), 2)
        self.assertEqual(len(summary.by_horizon), 2)
        self.assertEqual(len(summary.by_transmission_bias), 2)
        self.assertEqual(len(summary.by_context_regime), 2)
        self.assertEqual(len(summary.by_horizon_setup_family), 2)

    def test_combined_summary_uses_double_underscore_separator(self) -> None:
        """Horizon + Setup Family should be grouped as '1w__breakout'."""
        outcomes = [
            RecommendationPlanOutcome(recommendation_plan_id=1, horizon="1w", setup_family="breakout", outcome="win"),
            RecommendationPlanOutcome(recommendation_plan_id=2, horizon="1w", setup_family="breakout", outcome="loss"),
        ]
        summary = self.service._combined_summary(outcomes, "horizon", "setup_family", default_left="h", default_right="s")
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0].key, "1w__breakout")

    def test_averages_returns_across_items_in_bucket(self) -> None:
        outcomes = [
            RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", horizon_return_5d=10.0),
            RecommendationPlanOutcome(recommendation_plan_id=2, outcome="loss", horizon_return_5d=-5.0),
        ]
        bucket = self.service._build_bucket_list({"all": outcomes}, min_required_resolved_count=0, group_by="action")[0]
        # (10.0 - 5.0) / 2 = 2.5
        self.assertAlmostEqual(bucket.average_return_5d, 2.5)

    # ─── Sample Status Thresholds ─────────────────────────────────────────────

    def test_sample_status_insufficient_when_far_below_min(self) -> None:
        # min = 10, actual = 4. 4 < (10+1)//2 = 5 → insufficient
        self.assertEqual(self.service._sample_status(4, 10), "insufficient")

    def test_sample_status_limited_when_just_below_min(self) -> None:
        # min = 10, actual = 6. 6 >= 5 → limited
        self.assertEqual(self.service._sample_status(6, 10), "limited")

    def test_sample_status_usable_when_at_min(self) -> None:
        self.assertEqual(self.service._sample_status(10, 10), "usable")

    def test_sample_status_strong_when_double_min_and_bonus(self) -> None:
        # Strong requires actual >= max(min*2, min+8)
        # For min=10: max(20, 18) = 20.
        self.assertEqual(self.service._sample_status(19, 10), "usable")
        self.assertEqual(self.service._sample_status(20, 10), "strong")

    def test_sample_status_strong_for_low_min(self) -> None:
        # For min=4: max(8, 12) = 12.
        self.assertEqual(self.service._sample_status(11, 4), "usable")
        self.assertEqual(self.service._sample_status(12, 4), "strong")

    # ─── Corner Cases ─────────────────────────────────────────────────────────

    def test_summarize_handles_empty_outcomes_gracefully(self) -> None:
        self.outcomes_repo.list_outcomes.return_value = []
        summary = self.service.summarize()
        self.assertEqual(summary.total_outcomes, 0)
        self.assertIsNone(summary.calibration_report)
        self.assertEqual(len(summary.by_action), 0)

    def test_calibration_report_skips_outcomes_with_missing_confidence(self) -> None:
        outcomes = [
            RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", confidence_percent=None),
        ]
        report = self.service._build_calibration_report(outcomes, method="m", version_label="v", smoothing_strength=0)
        self.assertIsNone(report)

    def test_win_rate_returns_none_when_no_resolved_items(self) -> None:
        self.assertIsNone(self.service._win_rate([]))

    def test_average_returns_none_when_no_numeric_values(self) -> None:
        self.assertIsNone(self.service._average([None, "not_a_number"]))


class CalibrationDimensionThresholdTests(unittest.TestCase):
    """Verifies that different dimensions use their specific MIN_RESOLVED_COUNTS."""

    def setUp(self) -> None:
        self.outcomes_repo = Mock(spec=RecommendationOutcomeRepository)
        self.service = RecommendationPlanCalibrationService(self.outcomes_repo)

    def test_horizon_dimension_requires_12_for_usable_status(self) -> None:
        # Horizon min is 12. 
        # 11 items -> limited
        outcomes = [RecommendationPlanOutcome(recommendation_plan_id=i, outcome="win", horizon="1w") for i in range(11)]
        self.outcomes_repo.list_outcomes.return_value = outcomes
        summary = self.service.summarize()
        horizon_bucket = summary.by_horizon[0]
        self.assertEqual(horizon_bucket.sample_status, "limited")
        
        # 12 items -> usable
        outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=12, outcome="win", horizon="1w"))
        self.outcomes_repo.list_outcomes.return_value = outcomes
        summary = self.service.summarize()
        horizon_bucket = summary.by_horizon[0]
        self.assertEqual(horizon_bucket.sample_status, "usable")

    def test_action_dimension_requires_10_for_usable_status(self) -> None:
        # Action min is 10.
        # 9 items -> limited
        outcomes = [RecommendationPlanOutcome(recommendation_plan_id=i, outcome="win", action="long") for i in range(9)]
        self.outcomes_repo.list_outcomes.return_value = outcomes
        summary = self.service.summarize()
        action_bucket = summary.by_action[0]
        self.assertEqual(action_bucket.sample_status, "limited")

        # 10 items -> usable
        outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=10, outcome="win", action="long"))
        self.outcomes_repo.list_outcomes.return_value = outcomes
        summary = self.service.summarize()
        action_bucket = summary.by_action[0]
        self.assertEqual(action_bucket.sample_status, "usable")

class CalibrationKeyDefaultingTests(unittest.TestCase):
    """Verifies string formatting for missing dimension values."""

    def setUp(self) -> None:
        self.outcomes_repo = Mock(spec=RecommendationOutcomeRepository)
        self.service = RecommendationPlanCalibrationService(self.outcomes_repo)

    def test_combined_key_defaults_to_unknown_and_uncategorized(self) -> None:
        # Pydantic RecommendationPlanOutcome requires strings for setup_family/action
        outcomes = [RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", horizon=None, setup_family="")]
        self.outcomes_repo.list_outcomes.return_value = outcomes
        summary = self.service.summarize()
        bucket = summary.by_horizon_setup_family[0]
        self.assertEqual(bucket.key, "unknown_horizon__uncategorized")

class CalibrationSmoothingConstantTests(unittest.TestCase):
    """Verifies that production calls use the specified constants."""

    def test_smoothed_report_uses_strength_of_8_point_0(self) -> None:
        outcomes_repo = Mock(spec=RecommendationOutcomeRepository)
        service = RecommendationPlanCalibrationService(outcomes_repo)
        
        outcomes = [RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", confidence_percent=80.0)]
        outcomes_repo.list_outcomes.return_value = outcomes
        
        with patch.object(service, "_build_calibration_report", return_value=None) as mock_build:
            service.summarize(ticker="X")
            # First call is raw (0.0), second is smoothed (8.0)
            self.assertEqual(mock_build.call_args_list[0].kwargs["smoothing_strength"], 0.0)
            self.assertEqual(mock_build.call_args_list[1].kwargs["smoothing_strength"], 8.0)
