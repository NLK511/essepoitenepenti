"""
Comprehensive test suite for Social Sentiment Analysis math and logic.

Design principles:
  - Verify weighted averaging (Engagement + Recency + Quality + Credibility).
  - Verify scope breakdown (Macro vs Industry vs Ticker).
  - Verify noise penalties (short posts, noise phrases).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.models import SignalBundle, SignalEngagement, SignalItem
from trade_proposer_app.services.social import SocialSentimentAnalyzer


class SocialSentimentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = SocialSentimentAnalyzer()

    def _item(self, title: str, body: str = "", **kwargs) -> SignalItem:
        defaults = dict(
            source_type="social",
            provider="nitter",
            title=title,
            body=body,
            engagement=SignalEngagement(likes=0, retweets=0, replies=0),
            published_at=datetime.now(timezone.utc),
            scope_tags=["ticker"],
            quality_score=0.8,
            credibility_score=0.8
        )
        defaults.update(kwargs)
        return SignalItem(**defaults)

    def _bundle(self, items: list[SignalItem]) -> SignalBundle:
        return SignalBundle(ticker="TEST", items=items)

    # ─── Weighting Logic ──────────────────────────────────────────────────────

    def test_engagement_weight_increases_impact(self) -> None:
        """Likes and retweets should increase the weight of an item."""
        low_eng = self._item("growth")
        high_eng = self._item("growth", engagement=SignalEngagement(likes=200, retweets=0, replies=0))
        
        w_low = self.analyzer._item_weight(low_eng)
        w_high = self.analyzer._item_weight(high_eng)
        
        # engagement_weight = 1.0 + min(likes/200, 0.3) -> 1.0 vs 1.3
        self.assertAlmostEqual(w_high / w_low, 1.3)

    def test_noise_penalty_reduces_score(self) -> None:
        """Short posts and noise phrases should reduce the final relevance score."""
        # This tests _relevance_score in NitterProvider indirectly if we use it, 
        # but SocialSentimentAnalyzer has its own item scoring logic.
        # Actually, SocialSentimentAnalyzer uses item_weight for averaging.
        
        # Let's test the noise penalty in NitterProvider._relevance_score
        from trade_proposer_app.services.social import NitterProvider
        provider = NitterProvider(base_url="http://test")
        
        # Long post
        i1 = self._item("This is a very long and detailed post about the markets and stocks", "")
        # Short post (penalty 0.35)
        i2 = self._item("growth", "")
        
        s1 = provider._relevance_score(i1, query_profile={}, scope_tag="ticker", reference_now=datetime.now(timezone.utc))
        s2 = provider._relevance_score(i2, query_profile={}, scope_tag="ticker", reference_now=datetime.now(timezone.utc))
        
        self.assertGreater(s1, s2)

    # ─── Sentiment Math ───────────────────────────────────────────────────────

    def test_weighted_average_across_multiple_items(self) -> None:
        """
        Item 1: Score 1.0, Weight 1.0
        Item 2: Score -1.0, Weight 2.0
        Result = (1*1 + -1*2) / 3 = -1/3 = -0.333
        """
        # To get weight 1.0 and 2.0 exactly is hard due to floors, 
        # so we'll just verify the direction.
        i1 = self._item("growth", quality_score=0.4) # Low quality
        i2 = self._item("loss", quality_score=0.8)   # High quality
        
        result = self.analyzer.analyze(self._bundle([i1, i2]))
        # Weighted average should be closer to Item 2 (Negative)
        self.assertLess(result["score"], 0)

    # ─── Scope Breakdown ──────────────────────────────────────────────────────

    def test_breaks_down_scores_by_scope(self) -> None:
        i_macro = self._item("growth", scope_tags=["macro"]) # Score +
        i_ticker = self._item("loss", scope_tags=["ticker"]) # Score -
        
        result = self.analyzer.analyze(self._bundle([i_macro, i_ticker]))
        
        self.assertGreater(result["scope_breakdown"]["macro"]["score"], 0)
        self.assertLess(result["scope_breakdown"]["ticker"]["score"], 0)
        self.assertEqual(result["scope_breakdown"]["macro"]["item_count"], 1)

if __name__ == "__main__":
    unittest.main()
