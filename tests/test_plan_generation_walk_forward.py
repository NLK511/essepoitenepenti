"""
Comprehensive test suite for PlanGenerationWalkForwardService.

Design principles:
  - Verify mathematical correctness of Win Rate and EV delta averages.
  - Verify boundary conditions for promotion gates (3 slices, severe regressions).
  - Verify slicing logic (lookback, validation window, step size).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService


class _Record:
    def __init__(self, computed_at: datetime):
        self.plan = RecommendationPlan(ticker="TEST", action="long", computed_at=computed_at)
        self.outcome = RecommendationPlanOutcome(recommendation_plan_id=0, outcome="win")

class PlanGenerationWalkForwardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning_service = Mock()
        self.service = PlanGenerationWalkForwardService(self.tuning_service)

    def _make_records(self, count: int, start_date: datetime, interval_days: int = 1) -> list:
        records = []
        for i in range(count):
            records.append(_Record(start_date + timedelta(days=i * interval_days)))
        return records

    def test_slices_dataset_according_to_window_and_step(self) -> None:
        """
        Verify that lookback, validation_days, and step_days produce the correct number of slices.
        """
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = self._make_records(101, start) # 101 records to ensure Day 100 exists
        self.tuning_service._eligible_records.return_value = records
        self.tuning_service._score_records.return_value = (10, 5, 0.5, 0)

        summary = self.service.summarize(
            candidate_config={},
            baseline_config={},
            lookback_days=100,
            validation_days=30,
            step_days=10,
            min_validation_resolved=1
        )
        
        self.assertEqual(summary.total_slices, 8)

    def test_promotion_rejected_when_fewer_than_three_qualified_slices(self) -> None:
        """Promotion gate: qualified_slices < 3 -> False."""
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = self._make_records(30, start)
        self.tuning_service._eligible_records.return_value = records
        # Force all slices to be 'thin' by returning actionable_count < min_validation_resolved
        self.tuning_service._score_records.return_value = (5, 3, 0.3, 0)

        summary = self.service.summarize(
            candidate_config={}, baseline_config={},
            validation_days=5, step_days=5, min_validation_resolved=10
        )
        
        self.assertFalse(summary.promotion_recommended)
        self.assertIn("Not enough qualified slices", summary.promotion_rationale)

    def test_promotion_rejected_when_average_win_rate_delta_is_negative(self) -> None:
        """Promotion gate: average_win_rate_delta <= 0 -> False."""
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = self._make_records(100, start)
        self.tuning_service._eligible_records.return_value = records
        
        # Candidate win rate (40%) < Baseline win rate (50%)
        def score_side_effect(records, config):
            if config.get("name") == "candidate": return (20, 8, 0.4, 0)
            return (20, 10, 0.5, 0)
        self.tuning_service._score_records.side_effect = score_side_effect

        summary = self.service.summarize(
            candidate_config={"name": "candidate"}, 
            baseline_config={"name": "baseline"},
            min_validation_resolved=10
        )
        
        self.assertFalse(summary.promotion_recommended)
        self.assertLess(summary.average_win_rate_delta, 0)

    def test_promotion_rejected_with_more_than_one_severe_regression(self) -> None:
        """
        Promotion gate: > 1 severe regression -> False.
        Severe regression = Win Rate Delta < -5% or EV Delta < -0.05.
        """
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = self._make_records(120, start)
        self.tuning_service._eligible_records.return_value = records
        
        # Mock 5 slices
        # Slice 0-2: Candidate beats Baseline (+2%)
        # Slice 3: Severe regression (-6%)
        # Slice 4: Severe regression (-10%)
        calls = 0
        def score_side_effect(recs, config):
            nonlocal calls
            is_cand = config.get("name") == "candidate"
            idx = (calls // 2)
            calls += 1
            if idx < 3: return (20, 12 if is_cand else 10, 0.6 if is_cand else 0.5, 0)
            if idx == 3: return (20, 8 if is_cand else 10, 0.4 if is_cand else 0.5, 0)
            return (20, 6 if is_cand else 10, 0.3 if is_cand else 0.5, 0)
            
        self.tuning_service._score_records.side_effect = score_side_effect

        summary = self.service.summarize(
            candidate_config={"name": "candidate"}, 
            baseline_config={"name": "baseline"},
            validation_days=20, step_days=20,
            min_validation_resolved=10
        )
        
        # Qualified slices = 5. Candidate wins = 3. Baseline wins = 2.
        # Average delta = (2+2+2-10-20)/5 = -4.8 (roughly, calculation depends on exact indices)
        # But even if average was positive, 2 severe regressions reject.
        self.assertFalse(summary.promotion_recommended)
        self.assertIn("not stable enough", summary.promotion_rationale)

    def test_promotion_approved_when_all_gates_pass(self) -> None:
        """
        Final verification of a 'perfect' candidate.
        """
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = self._make_records(120, start)
        self.tuning_service._eligible_records.return_value = records
        
        # 5 slices, Candidate wins 4, ties 1. No regressions.
        def score_side_effect(recs, config):
            is_cand = config.get("name") == "candidate"
            return (20, 12 if is_cand else 10, 0.6 if is_cand else 0.5, 0)
            
        self.tuning_service._score_records.side_effect = score_side_effect

        summary = self.service.summarize(
            candidate_config={"name": "candidate"}, 
            baseline_config={"name": "baseline"},
            validation_days=20, step_days=20,
            min_validation_resolved=10
        )
        
        self.assertTrue(summary.promotion_recommended)
        self.assertEqual(summary.candidate_wins, 5)
        self.assertGreater(summary.average_win_rate_delta, 0)
        self.assertGreater(summary.average_expected_value_delta, 0)

    def test_calculates_exact_average_deltas(self) -> None:
        """
        Verify the arithmetic for average deltas across 3 qualified slices.
        """
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = self._make_records(61, start) # 61 records to include Day 60
        self.tuning_service._eligible_records.return_value = records
        
        # Slice 0: Cand 60%, Base 50% (Delta 10%) | Cand EV 0.6, Base EV 0.5 (Delta 0.1)
        # Slice 1: Cand 55%, Base 50% (Delta 5%)  | Cand EV 0.55, Base EV 0.5 (Delta 0.05)
        # Slice 2: Cand 50%, Base 50% (Delta 0%)  | Cand EV 0.5, Base EV 0.5 (Delta 0.0)
        
        # Result: Avg Win Delta = (10+5+0)/3 = 5.0
        # Result: Avg EV Delta = (0.1+0.05+0)/3 = 0.05
        
        results = [
            ((20, 12, 0.6, 0), (20, 10, 0.5, 0)),
            ((20, 11, 0.55, 0), (20, 10, 0.5, 0)),
            ((20, 10, 0.5, 0), (20, 10, 0.5, 0)),
        ]
        calls = 0
        def score_side_effect(recs, config):
            nonlocal calls
            idx = calls // 2
            is_cand = config.get("name") == "candidate"
            calls += 1
            return results[idx][0] if is_cand else results[idx][1]

        self.tuning_service._score_records.side_effect = score_side_effect

        summary = self.service.summarize(
            candidate_config={"name": "candidate"}, 
            baseline_config={"name": "baseline"},
            validation_days=20, step_days=20,
            min_validation_resolved=10
        )
        
        self.assertAlmostEqual(summary.average_win_rate_delta, 5.0)
        self.assertAlmostEqual(summary.average_expected_value_delta, 0.05)

if __name__ == "__main__":
    unittest.main()
