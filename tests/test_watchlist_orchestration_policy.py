"""
Comprehensive test suite for WatchlistOrchestrationService policy and selection logic.

Design principles:
  - Verify shortlist ranking and lane assignment (technical vs catalyst).
  - Verify rejection reasons (confidence floor, attention floor, shorts disabled).
  - Verify decision sample types and review priorities.
  - Verify confidence adjustments based on transmission bias.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics, RunOutput, Watchlist
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService, _CheapScanCandidate


class WatchlistOrchestrationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context_snapshots = Mock()
        self.recommendation_plans = Mock()
        self.cheap_scan_service = Mock()
        self.decision_samples = Mock()
        self.deep_analysis_service = Mock()
        
        self.service = WatchlistOrchestrationService(
            context_snapshots=self.context_snapshots,
            recommendation_plans=self.recommendation_plans,
            cheap_scan_service=self.cheap_scan_service,
            decision_samples=self.decision_samples,
            deep_analysis_service=self.deep_analysis_service,
            confidence_threshold=60.0
        )

    # ─── Shortlist Ranking & Lane Logic ───────────────────────────────────────

    def test_shortlist_ranks_by_attention_then_confidence(self) -> None:
        """ranking = (attention, confidence) descending."""
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        # ticker_count=8 -> limit = 8 // 4 = 2.
        candidates = [
            _CheapScanCandidate("A", "long", 70.0, 80.0, [], ""), # Rank 3 (80, 70)
            _CheapScanCandidate("B", "long", 85.0, 90.0, [], ""), # Rank 1 (90, 85)
            _CheapScanCandidate("C", "long", 90.0, 80.0, [], ""), # Rank 2 (80, 90)
        ]
        # Padding to ensure limit=2
        for i in range(5):
            candidates.append(_CheapScanCandidate(f"P{i}", "long", 10.0, 10.0, [], ""))
        
        result = self.service._evaluate_shortlist(watchlist, candidates)
        # B: (90, 85), C: (80, 90)
        self.assertEqual(result["shortlist"], ["B", "C"])

    def test_catalyst_lane_selection_with_relaxed_floors(self) -> None:
        """
        Catalyst lane allows candidates that fail technical floors but pass catalyst floors.
        Technical floor for 1w (8 tickers): confidence=45, attention=65.
        """
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        
        # Candidate 1: Passes all technical floors
        c1 = _CheapScanCandidate("TECH", "long", 70.0, 80.0, [], "")
        
        # Candidate 2: Fails technical confidence (40 < 45) but passes catalyst floors
        c2 = _CheapScanCandidate("CAT", "long", 40.0, 70.0, [], "")
        
        # Padding to ensure limit >= 2 (8 tickers -> limit=2)
        candidates = [c1, c2]
        for i in range(6):
            candidates.append(_CheapScanCandidate(f"P{i}", "long", 10.0, 10.0, [], ""))

        # Mock catalyst score
        with patch.object(self.service, "_catalyst_shortlist_score", side_effect=lambda c: 90.0 if c.ticker == "CAT" else 10.0):
            result = self.service._evaluate_shortlist(watchlist, candidates)
            
            self.assertIn("TECH", result["shortlist"])
            self.assertIn("CAT", result["shortlist"])
            
            decisions = {d["ticker"]: d for d in result["decisions"]}
            self.assertEqual(decisions["TECH"]["selection_lane"], "technical")
            self.assertEqual(decisions["CAT"]["selection_lane"], "catalyst")

    # ─── Exclusion Logic ──────────────────────────────────────────────────────

    def test_excludes_shorts_when_watchlist_disallows(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=False)
        candidates = [_CheapScanCandidate("S", "short", 90.0, 90.0, [], "")]
        
        result = self.service._evaluate_shortlist(watchlist, candidates)
        self.assertNotIn("S", result["shortlist"])
        self.assertIn("shorts_disabled", result["decisions"][0]["reasons"])

    def test_excludes_tickers_below_confidence_floor(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        # For 1 ticker, ticker_count <= 2 -> limit=ticker_count=1.
        # minimum_confidence for 1w, count 1 -> 55.0.
        candidates = [_CheapScanCandidate("LOW", "long", 40.0, 90.0, [], "")]
        
        result = self.service._evaluate_shortlist(watchlist, candidates)
        self.assertNotIn("LOW", result["shortlist"])
        self.assertIn("below_confidence_threshold", result["decisions"][0]["reasons"])

    # ─── Decision Sample Metadata ─────────────────────────────────────────────

    def test_decision_type_near_miss_when_confidence_is_within_threshold(self) -> None:
        # gap >= -5.0 -> near_miss
        self.assertEqual(
            self.service._decision_type("no_action", "ok", "reason", -2.0, shortlisted=True),
            "near_miss"
        )

    def test_review_priority_high_for_near_miss_at_threshold(self) -> None:
        # gap >= -2.0 -> high
        self.assertEqual(
            self.service._review_priority("near_miss", confidence_gap=-1.5, shortlisted=True, status="ok"),
            "high"
        )

    def test_review_priority_medium_for_partial_actionable_plan(self) -> None:
        # actionable + status=partial -> medium
        self.assertEqual(
            self.service._review_priority("actionable", confidence_gap=10.0, shortlisted=True, status="partial"),
            "medium"
        )

    # ─── Transmission Bias Calculation ────────────────────────────────────────

    def test_bias_from_alignment_score_mapping(self) -> None:
        # tailwind: >= 62
        self.assertEqual(self.service._bias_from_alignment(62.0), "tailwind")
        # headwind: <= 42
        self.assertEqual(self.service._bias_from_alignment(42.0), "headwind")
        # mixed: between
        self.assertEqual(self.service._bias_from_alignment(50.0), "mixed")

    def test_transmission_confidence_adjustment_penalty_for_headwind(self) -> None:
        # headwind Penalty = (55 - 40) * 0.16 = 2.4
        analysis = {
            "ticker_deep_analysis": {
                "transmission_analysis": {
                    "contradiction_count": 0,
                    "context_strength_percent": 0.0,
                    "context_event_relevance_percent": 0.0,
                    "decay_state": "unknown"
                }
            }
        }
        adj = self.service._transmission_confidence_adjustment(analysis, transmission_bias="headwind", alignment_score=40.0)
        self.assertEqual(adj, -2.4)

if __name__ == "__main__":
    unittest.main()
