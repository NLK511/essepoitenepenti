import unittest

from trade_proposer_app.domain.models import RecommendationPlanOutcome
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from unittest.mock import Mock

class RecommendationPlanCalibrationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.outcomes_repo = Mock(spec=RecommendationOutcomeRepository)
        self.service = RecommendationPlanCalibrationService(self.outcomes_repo)

    def test_brier_score_and_ece_exact_math_without_smoothing(self) -> None:
        # Create perfectly predictable set
        # 10 items at 80% confidence -> exactly 8 wins, 2 losses.
        # Average predicted = 0.8
        # Average actual = 0.8
        # Brier for this bin: sum((0.8 - actual)^2) / 10
        # For wins: (0.8 - 1.0)^2 = 0.04 (8 times) -> 0.32
        # For losses: (0.8 - 0.0)^2 = 0.64 (2 times) -> 1.28
        # Total Brier for bin = (0.32 + 1.28) / 10 = 0.1600
        # ECE: abs(0.8 - 0.8) = 0.0
        
        # 10 items at 25% confidence -> exactly 1 win, 9 losses. (wait, 25% * 10 = 2.5 wins, let's use 4 items: 1 win, 3 losses)
        # 4 items at 25% (0.25). 1 win, 3 losses.
        # Average predicted = 0.25. Actual = 0.25.
        # Wins: (0.25 - 1.0)^2 = 0.5625 (1 time)
        # Losses: (0.25 - 0.0)^2 = 0.0625 (3 times) -> 0.1875
        # Total = 0.75 / 4 = 0.1875
        # ECE: 0.0
        
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
        
        # Total Brier = weighted average of bin briers
        # Bin 1 (80-90) has 10 items, brier 0.16
        # Bin 2 (20-40) has 4 items, brier 0.1875
        # Total Brier = (10 * 0.16 + 4 * 0.1875) / 14 = (1.6 + 0.75) / 14 = 2.35 / 14 = 0.167857...
        self.assertAlmostEqual(report.brier_score, 0.1679, places=4)
        self.assertEqual(report.expected_calibration_error, 0.0)

        # Check bins
        self.assertEqual(len(report.bins), 2)
        bin_80 = next(b for b in report.bins if b.bin_key == "80_90")
        self.assertEqual(bin_80.sample_count, 10)
        self.assertAlmostEqual(bin_80.predicted_probability, 0.8, places=2)
        self.assertAlmostEqual(bin_80.realized_win_rate_percent, 80.0, places=1)
        self.assertAlmostEqual(bin_80.brier_score, 0.16, places=4)

        bin_20 = next(b for b in report.bins if b.bin_key == "20_40")
        self.assertEqual(bin_20.sample_count, 4)
        self.assertAlmostEqual(bin_20.predicted_probability, 0.25, places=2)
        self.assertAlmostEqual(bin_20.realized_win_rate_percent, 25.0, places=1)
        self.assertAlmostEqual(bin_20.brier_score, 0.1875, places=4)

    def test_ece_computes_exact_calibration_error_when_mismatched(self) -> None:
        # 10 items predicted at 90%, but only 5 wins (50% actual)
        # Expected Error for this bin = abs(0.9 - 0.5) = 0.4
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
        # One bin (90_100). Error = 0.4.
        self.assertAlmostEqual(report.expected_calibration_error, 0.4, places=4)

    def test_smoothing_strength_pulls_predictions_toward_global_average(self) -> None:
        # 5 items at 90% in bin A (all wins -> actual 100%)
        # 5 items at 10% in bin B (all losses -> actual 0%)
        # Global win rate = 50%
        outcomes = []
        for _ in range(5):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=1, outcome="win", confidence_percent=90.0))
        for _ in range(5):
            outcomes.append(RecommendationPlanOutcome(recommendation_plan_id=2, outcome="loss", confidence_percent=10.0))

        # First without smoothing
        report_raw = self.service._build_calibration_report(
            outcomes, method="test", version_label="v1", smoothing_strength=0.0
        )
        # Bin 90_100 predicted = 0.9. Bin 0_20 predicted = 0.1.
        
        # With smoothing (strength = 5.0)
        # Bin 90_100 formula: (0.9 * 5 + 0.5 * 5) / (5 + 5) = (4.5 + 2.5) / 10 = 0.7
        # Bin 0_20 formula: (0.1 * 5 + 0.5 * 5) / (5 + 5) = (0.5 + 2.5) / 10 = 0.3
        report_smoothed = self.service._build_calibration_report(
            outcomes, method="test", version_label="v1", smoothing_strength=5.0
        )
        
        self.assertIsNotNone(report_raw)
        self.assertIsNotNone(report_smoothed)
        
        raw_bin_90 = next(b for b in report_raw.bins if b.bin_key == "90_100")
        sm_bin_90 = next(b for b in report_smoothed.bins if b.bin_key == "90_100")
        
        self.assertAlmostEqual(raw_bin_90.predicted_probability, 0.9)
        self.assertAlmostEqual(sm_bin_90.predicted_probability, 0.7)

if __name__ == '__main__':
    unittest.main()
