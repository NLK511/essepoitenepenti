"""
Comprehensive test suite for WatchlistOrchestrationService policy and selection logic.

Design principles:
  - Verify shortlist ranking and lane assignment (technical vs catalyst).
  - Verify rejection reasons (confidence floor, attention floor, shorts disabled).
  - Verify decision sample types and review priorities.
  - Verify confidence adjustments based on transmission bias.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RecommendationPlan, RunDiagnostics, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.services.watchlist_execution import WatchlistExecutionService
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
        candidates = [
            _CheapScanCandidate("A", "long", 40.0, 80.0, [], ""), # Ineligible on confidence
            _CheapScanCandidate("B", "long", 85.0, 90.0, [], ""), # Rank 1 (90, 85)
            _CheapScanCandidate("C", "long", 90.0, 80.0, [], ""), # Rank 2 (80, 90)
        ]
        # Padding to keep the ranking set visible while staying ineligible.
        for i in range(5):
            candidates.append(_CheapScanCandidate(f"P{i}", "long", 10.0, 10.0, [], ""))

        result = self.service._evaluate_shortlist(watchlist, candidates)
        self.assertEqual(result["shortlist"], ["B", "C"])

    def test_shortlist_has_no_hard_cap_for_eligible_candidates(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidates = [
            _CheapScanCandidate("A", "long", 70.0, 90.0, [], ""),
            _CheapScanCandidate("B", "long", 71.0, 89.0, [], ""),
            _CheapScanCandidate("C", "long", 72.0, 88.0, [], ""),
            _CheapScanCandidate("D", "long", 73.0, 87.0, [], ""),
            _CheapScanCandidate("E", "long", 74.0, 86.0, [], ""),
            _CheapScanCandidate("F", "long", 75.0, 85.0, [], ""),
        ]

        result = self.service._evaluate_shortlist(watchlist, candidates)

        self.assertEqual(len(result["shortlist"]), 6)
        self.assertEqual(result["rules"]["limit"], 6)
        self.assertEqual(result["rules"]["core_limit"], 6)
        self.assertEqual(result["rules"]["catalyst_lane_limit"], 6)

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

        # Mock catalyst score at the dedicated shortlist-selection boundary.
        with patch.object(self.service.shortlist_selection, "catalyst_shortlist_score", side_effect=lambda c: 90.0 if c.ticker == "CAT" else 10.0):
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

    def test_transmission_confidence_adjustment_caps_positive_boost(self) -> None:
        analysis = {
            "ticker_deep_analysis": {
                "transmission_analysis": {
                    "contradiction_count": 0,
                    "context_strength_percent": 100.0,
                    "context_event_relevance_percent": 100.0,
                    "context_quality_status": "usable",
                    "macro_context_quality_status": "usable",
                    "industry_context_quality_status": "usable",
                    "decay_state": "fresh",
                }
            }
        }
        adj = self.service._transmission_confidence_adjustment(analysis, transmission_bias="tailwind", alignment_score=80.0)
        self.assertEqual(adj, 2.0)

    def test_transmission_confidence_adjustment_does_not_boost_degraded_or_contradictory_context(self) -> None:
        degraded = {
            "ticker_deep_analysis": {
                "transmission_analysis": {
                    "contradiction_count": 0,
                    "context_strength_percent": 100.0,
                    "context_event_relevance_percent": 100.0,
                    "context_quality_status": "degraded",
                    "macro_context_quality_status": "degraded",
                    "industry_context_quality_status": "usable",
                    "decay_state": "fresh",
                }
            }
        }
        contradictory = {
            "ticker_deep_analysis": {
                "transmission_analysis": {
                    "contradiction_count": 1,
                    "context_strength_percent": 100.0,
                    "context_event_relevance_percent": 100.0,
                    "context_quality_status": "usable",
                    "macro_context_quality_status": "usable",
                    "industry_context_quality_status": "usable",
                    "decay_state": "fresh",
                }
            }
        }
        self.assertEqual(self.service._transmission_confidence_adjustment(degraded, transmission_bias="tailwind", alignment_score=80.0), 0.0)
        self.assertEqual(self.service._transmission_confidence_adjustment(contradictory, transmission_bias="tailwind", alignment_score=80.0), -2.0)

    def test_shortlisted_candidate_with_deep_summary_fallback_marks_warning(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 80.0, 90.0, [], "")
        deep_output = RunOutput(
            recommendation=Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=81.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
            ),
            diagnostics=RunDiagnostics(warnings=["plan context summary fell back to digest/static summary because pi_agent CLI timed out after 5s"]),
        )
        signal = Mock(diagnostics=Mock(get=Mock(return_value=None)))
        plan = RecommendationPlan(ticker="AAPL", horizon="1w", action="long", confidence_percent=81.0, entry_price_low=99.0, entry_price_high=101.0, stop_loss=95.0, take_profit=110.0)
        self.service._shortlist_decision_for_ticker = Mock(return_value={"ticker": "AAPL"})
        self.service._run_deep_analysis = Mock(return_value=(deep_output, None))
        self.service._build_signal_snapshot = Mock(return_value=signal)
        self.service.context_snapshots.create_ticker_signal_snapshot.return_value = signal
        self.service._build_plan_from_signal = Mock(return_value=plan)
        self.service.recommendation_plans.create_plan.return_value = plan
        self.service._record_decision_sample = Mock()

        warnings_found = WatchlistExecutionService(self.service)._process_shortlisted_candidate(
            self.service,
            watchlist,
            candidate,
            shortlist_rank=1,
            shortlist_evaluation={"shortlist": ["AAPL"]},
            calibration_summary=None,
            stored_signals=[],
            stored_plans=[],
            ticker_generation=[],
            warnings_found=False,
            job_id=1,
            run_id=1,
            as_of=None,
        )

        self.assertTrue(warnings_found)

    def test_calibration_curve_snapshot_adjusts_confidence_from_smoothed_bin(self) -> None:
        calibration_summary = SimpleNamespace(
            smoothed_calibration_report=SimpleNamespace(
                version_label="confidence-reliability-v2-smoothed",
                bins=[
                    SimpleNamespace(
                        bin_key="70_80",
                        bin_label="70-80",
                        predicted_probability=0.65,
                        realized_win_rate_percent=60.0,
                        resolved_count=30,
                    )
                ],
            )
        )

        curve = self.service._calibration_curve_snapshot(calibration_summary, 75.0)

        self.assertIsNotNone(curve)
        assert curve is not None
        self.assertEqual(curve["bin_key"], "70_80")
        self.assertEqual(curve["predicted_probability_percent"], 65.0)
        self.assertEqual(curve["confidence_adjustment"], -4.0)

    def test_calibration_curve_snapshot_prefers_recent_reports_when_available(self) -> None:
        calibration_summary = SimpleNamespace(
            recent_smoothed_calibration_report=SimpleNamespace(
                version_label="confidence-reliability-v2-smoothed-recent",
                bins=[
                    SimpleNamespace(
                        bin_key="70_80",
                        bin_label="70-80",
                        predicted_probability=0.25,
                        realized_win_rate_percent=25.0,
                        resolved_count=30,
                    )
                ],
            ),
            smoothed_calibration_report=SimpleNamespace(
                version_label="confidence-reliability-v2-smoothed",
                bins=[
                    SimpleNamespace(
                        bin_key="70_80",
                        bin_label="70-80",
                        predicted_probability=0.75,
                        realized_win_rate_percent=75.0,
                        resolved_count=30,
                    )
                ],
            ),
        )

        curve = self.service._calibration_curve_snapshot(calibration_summary, 75.0)

        self.assertIsNotNone(curve)
        assert curve is not None
        self.assertEqual(curve["report_scope"], "recent_smoothed")
        self.assertEqual(curve["predicted_probability_percent"], 25.0)
        self.assertEqual(curve["confidence_adjustment"], -4.0)

    # ─── Plan Confidence Source ───────────────────────────────────────────────

    def test_build_plan_uses_deep_analysis_confidence_for_action_gate(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 42.0, 85.0, [], "")
        signal = TickerSignalSnapshot(
            ticker="AAPL",
            direction="long",
            confidence_percent=42.0,
            attention_score=85.0,
            diagnostics={"shortlisted": True, "mode": "deep_analysis"},
        )
        deep_output = RunOutput(
            recommendation=Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=72.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=112.0,
            ),
            diagnostics=RunDiagnostics(
                analysis_json=json.dumps(
                    {
                        "summary": {"text": "Strong deep-analysis setup"},
                        "ticker_deep_analysis": {
                            "setup_family": "continuation",
                            "confidence_components": {
                                "context_confidence": 60.0,
                                "directional_confidence": 72.0,
                                "catalyst_confidence": 65.0,
                                "technical_clarity": 70.0,
                                "execution_clarity": 75.0,
                                "data_quality_cap": 90.0,
                            },
                            "transmission_analysis": {
                                "alignment_percent": 65.0,
                                "contradiction_count": 0,
                                "context_bias": "tailwind",
                            },
                        },
                    }
                )
            ),
        )

        plan = self.service._build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=None,
            calibration_summary=None,
            job_id=None,
            run_id=None,
        )

        self.assertEqual(plan.action, "long")
        self.assertEqual(plan.confidence_percent, 72.0)
        self.assertEqual(plan.evidence_summary["action_reason"], "actionable_setup")
        self.assertEqual(plan.signal_breakdown["cheap_scan_confidence_percent"], 42.0)
        self.assertEqual(plan.signal_breakdown["deep_analysis_confidence_percent"], 72.0)
        self.assertEqual(plan.signal_breakdown["raw_plan_confidence_percent"], 72.0)

    def test_build_plan_allows_mixed_context_contradiction_without_directional_conflict(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 42.0, 85.0, [], "")
        signal = TickerSignalSnapshot(
            ticker="AAPL",
            direction="long",
            confidence_percent=42.0,
            attention_score=85.0,
            diagnostics={"shortlisted": True, "mode": "deep_analysis"},
        )
        deep_output = RunOutput(
            recommendation=Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=62.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=112.0,
            ),
            diagnostics=RunDiagnostics(
                analysis_json=json.dumps(
                    {
                        "summary": {"text": "Threshold-clearing mixed-context setup"},
                        "ticker_deep_analysis": {
                            "setup_family": "continuation",
                            "confidence_components": {"directional_confidence": 62.0},
                            "transmission_analysis": {
                                "alignment_percent": 48.0,
                                "contradiction_count": 10,
                                "conflict_flags": ["timing_conflict", "context_contradiction", "context_quality_conflict"],
                            },
                        },
                    }
                )
            ),
        )

        plan = self.service._build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=None,
            calibration_summary=None,
            job_id=None,
            run_id=None,
        )

        self.assertEqual(plan.action, "long")
        self.assertEqual(plan.confidence_percent, 62.0)

    def test_build_plan_blocks_severe_directional_contradiction_until_extra_buffer_clears(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 42.0, 85.0, [], "")
        signal = TickerSignalSnapshot(
            ticker="AAPL",
            direction="long",
            confidence_percent=42.0,
            attention_score=85.0,
            diagnostics={"shortlisted": True, "mode": "deep_analysis"},
        )
        deep_output = RunOutput(
            recommendation=Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=62.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=112.0,
            ),
            diagnostics=RunDiagnostics(
                analysis_json=json.dumps(
                    {
                        "summary": {"text": "Directionally conflicted setup"},
                        "ticker_deep_analysis": {
                            "setup_family": "continuation",
                            "confidence_components": {"directional_confidence": 62.0},
                            "transmission_analysis": {
                                "alignment_percent": 48.0,
                                "contradiction_count": 2,
                                "conflict_flags": ["directional_conflict"],
                            },
                        },
                    }
                )
            ),
        )

        plan = self.service._build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=None,
            calibration_summary=None,
            job_id=None,
            run_id=None,
        )

        self.assertEqual(plan.action, "no_action")
        self.assertEqual(plan.evidence_summary["action_reason"], "context_transmission_contradiction")
        self.assertEqual(plan.confidence_percent, 62.0)

    def test_build_plan_falls_back_to_signal_confidence_when_deep_analysis_unavailable(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 42.0, 85.0, [], "")
        signal = TickerSignalSnapshot(
            ticker="AAPL",
            direction="long",
            confidence_percent=42.0,
            attention_score=85.0,
            diagnostics={"shortlisted": True, "mode": "deep_analysis"},
        )

        plan = self.service._build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=None,
            deep_error="provider unavailable",
            calibration_summary=None,
            job_id=None,
            run_id=None,
        )

        self.assertEqual(plan.action, "no_action")
        self.assertEqual(plan.status, "degraded")
        self.assertEqual(plan.confidence_percent, 42.0)
        self.assertEqual(plan.evidence_summary["action_reason"], "deep_analysis_unavailable")
        self.assertEqual(plan.signal_breakdown["cheap_scan_confidence_percent"], 42.0)
        self.assertIsNone(plan.signal_breakdown["deep_analysis_confidence_percent"])
        self.assertEqual(plan.signal_breakdown["raw_plan_confidence_percent"], 42.0)

    def test_build_plan_allows_when_macro_is_blocked_but_industry_is_only_degraded(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 42.0, 85.0, [], "")
        signal = TickerSignalSnapshot(
            ticker="AAPL",
            direction="long",
            confidence_percent=42.0,
            attention_score=85.0,
            diagnostics={"shortlisted": True, "mode": "deep_analysis"},
        )
        deep_output = RunOutput(
            recommendation=Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=62.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=112.0,
            ),
            diagnostics=RunDiagnostics(
                analysis_json=json.dumps(
                    {
                        "summary": {"text": "Macro is blocked but industry is only degraded"},
                        "ticker_deep_analysis": {
                            "setup_family": "continuation",
                            "confidence_components": {"directional_confidence": 62.0},
                            "context_quality_status": "blocked",
                            "context_quality": {"status": "blocked"},
                            "transmission_analysis": {
                                "alignment_percent": 68.0,
                                "contradiction_count": 0,
                                "context_quality_status": "blocked",
                                "trade_context_quality_status": "degraded",
                                "macro_context_quality_status": "blocked",
                                "industry_context_quality_status": "degraded",
                                "conflict_flags": ["context_quality_blocked"],
                            },
                        },
                    }
                )
            ),
        )

        plan = self.service._build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=None,
            calibration_summary=None,
            job_id=None,
            run_id=None,
        )

        self.assertEqual(plan.action, "long")
        self.assertEqual(plan.status, "partial")
        self.assertNotEqual(plan.evidence_summary["action_reason"], "context_quality_blocked")
        self.assertIn("context quality is degraded", " ".join(plan.warnings))

    def test_build_plan_blocks_when_both_macro_and_industry_context_are_blocked(self) -> None:
        watchlist = Watchlist(name="test", default_horizon=StrategyHorizon.ONE_WEEK, allow_shorts=True)
        candidate = _CheapScanCandidate("AAPL", "long", 42.0, 85.0, [], "")
        signal = TickerSignalSnapshot(
            ticker="AAPL",
            direction="long",
            confidence_percent=42.0,
            attention_score=85.0,
            diagnostics={"shortlisted": True, "mode": "deep_analysis"},
        )
        deep_output = RunOutput(
            recommendation=Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=62.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=112.0,
            ),
            diagnostics=RunDiagnostics(
                analysis_json=json.dumps(
                    {
                        "summary": {"text": "Blocked by context quality"},
                        "ticker_deep_analysis": {
                            "setup_family": "continuation",
                            "confidence_components": {"directional_confidence": 62.0},
                            "context_quality_status": "blocked",
                            "context_quality": {"status": "blocked"},
                            "transmission_analysis": {
                                "alignment_percent": 68.0,
                                "contradiction_count": 0,
                                "context_quality_status": "blocked",
                                "trade_context_quality_status": "blocked",
                                "macro_context_quality_status": "blocked",
                                "industry_context_quality_status": "blocked",
                                "conflict_flags": ["context_quality_blocked"],
                            },
                        },
                    }
                )
            ),
        )

        plan = self.service._build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=None,
            calibration_summary=None,
            job_id=None,
            run_id=None,
        )

        self.assertEqual(plan.action, "no_action")
        self.assertEqual(plan.status, "degraded")
        self.assertEqual(plan.evidence_summary["action_reason"], "context_quality_blocked")
        self.assertIn("context quality is blocked", " ".join(plan.warnings))

if __name__ == "__main__":
    unittest.main()
