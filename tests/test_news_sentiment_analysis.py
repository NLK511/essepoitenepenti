"""
Comprehensive test suite for News Sentiment Analysis math and logic.

Design principles:
  - Verify weighted keyword scoring (Title boost vs Summary).
  - Verify phrase-level overrides (beats expectations > beat).
  - Verify score smoothing formula.
  - Verify context tag extraction.
  - Verify statistics (Polarity and Volatility).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from trade_proposer_app.domain.models import NewsArticle, NewsBundle
from trade_proposer_app.services.news import NaiveSentimentAnalyzer, ARTICLE_SCORE_SMOOTHING


class NewsSentimentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = NaiveSentimentAnalyzer()

    def _bundle(self, articles: list[NewsArticle]) -> NewsBundle:
        return NewsBundle(ticker="TEST", articles=articles)

    # ─── Sentiment Math ───────────────────────────────────────────────────────

    def test_scores_single_positive_keyword_correctly(self) -> None:
        """
        Input: Title="growth" (weight 1.1)
        Smoothing: 0.25
        Calculation:
          positives = 1.1 * 1.7 (title boost) = 1.87
          negatives = 0.0
          hits = 1.87
          score = (1.87 - 0) / (1.87 + 0.25) = 1.87 / 2.12 = 0.8820...
        """
        article = NewsArticle(title="growth", summary="")
        result = self.analyzer.analyze(self._bundle([article]))
        
        # score is the average of article scores (only 1 article here)
        self.assertAlmostEqual(result["score"], 0.8821, places=4)
        self.assertEqual(result["label"], "POSITIVE")

    def test_scores_mixed_keywords_with_title_boost(self) -> None:
        """
        Input: Title="growth" (+1.1), Summary="loss" (-1.1)
        Calculation:
          article_pos = 1.1 * 1.7 = 1.87
          article_neg = 1.1 * 1.2 = 1.32
          hits = 1.87 + 1.32 = 3.19
          score = (1.87 - 1.32) / (3.19 + 0.25) = 0.55 / 3.44 = 0.15988...
        """
        article = NewsArticle(title="growth", summary="loss")
        result = self.analyzer.analyze(self._bundle([article]))
        self.assertAlmostEqual(result["score"], 0.1599, places=4)
        self.assertEqual(result["label"], "POSITIVE") # 0.1599 > 0.15

    def test_phrase_augments_individual_keywords(self) -> None:
        """
        Input: "beats expectations" (+1.4 phrase, "beats" keyword +1.3)
        Calculation:
          keyword_pos = 1.3 * 1.7 (title boost) = 2.21
          phrase_pos = 1.4
          total_pos = 3.61
          score = 3.61 / (3.61 + 0.25) = 3.61 / 3.86 = 0.9352...
        """
        article = NewsArticle(title="beats expectations", summary="")
        result = self.analyzer.analyze(self._bundle([article]))
        self.assertAlmostEqual(result["score"], 0.9352, places=4)

    # ─── Statistics ───────────────────────────────────────────────────────────

    def test_calculates_polarity_trend(self) -> None:
        """
        Article 1: 2 positive units. Article 2: 1 negative unit.
        Polarity = (2 - 1) / (2 + 1) = 1 / 3 = 0.333...
        """
        a1 = NewsArticle(title="strong", summary="") # pos ~1.7
        a2 = NewsArticle(title="weak", summary="")   # neg ~1.7
        # Since weights are same (1.0 * 1.7), polarity should be 0.
        result = self.analyzer.analyze(self._bundle([a1, a2]))
        self.assertAlmostEqual(result["polarity_trend"], 0.0)

    def test_calculates_volatility_of_scores(self) -> None:
        """Volatility is standard deviation of article scores."""
        a1 = NewsArticle(title="strong", summary="") # score ~0.87
        a2 = NewsArticle(title="weak", summary="")   # score ~-0.87
        result = self.analyzer.analyze(self._bundle([a1, a2]))
        self.assertGreater(result["sentiment_volatility"], 0.5)

    # ─── Context Extraction ───────────────────────────────────────────────────

    def test_extracts_context_flags_from_keywords(self) -> None:
        article = NewsArticle(title="earnings release", summary="geopolitical conflict")
        result = self.analyzer.analyze(self._bundle([article]))
        
        self.assertEqual(result["context_flags"]["context_tag_earnings"], 1.0)
        self.assertEqual(result["context_flags"]["context_tag_geopolitical"], 1.0)
        self.assertEqual(result["context_flags"]["context_tag_industry"], 0.0)

    # ─── Coverage Insights ────────────────────────────────────────────────────

    def test_emits_neutral_policy_warning_when_no_keywords_match(self) -> None:
        article = NewsArticle(title="The weather is nice", summary="No financial content here")
        result = self.analyzer.analyze(self._bundle([article]))
        
        self.assertEqual(result["score"], 0.0)
        self.assertIn("no sentiment keywords matched", result["coverage_insights"][0])

if __name__ == "__main__":
    unittest.main()
