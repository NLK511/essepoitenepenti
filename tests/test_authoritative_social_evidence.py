from __future__ import annotations

import unittest

from trade_proposer_app.services.event_extraction import (
    authoritative_social_handles,
    classify_source_priority,
    extract_ranked_events,
    source_priority_counts,
)
from trade_proposer_app.domain.models import SignalBundle, SignalItem
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.social import SocialSentimentAnalyzer


class AuthoritativeSocialEvidenceTests(unittest.TestCase):
    def test_generic_nitter_item_remains_social(self) -> None:
        self.assertEqual(
            classify_source_priority("nitter", source_type="social", author_handle="random_trader"),
            "social",
        )

    def test_allowlisted_handle_becomes_authoritative_social(self) -> None:
        self.assertEqual(
            classify_source_priority("nitter", source_type="social", author_handle="@federalreserve"),
            "authoritative_social",
        )
        self.assertEqual(
            classify_source_priority("nitter", source_type="social", author_handle="NickTimiraos"),
            "authoritative_social",
        )

    def test_authoritative_social_is_counted_separately_from_primary_news(self) -> None:
        items = [
            {"publisher": "Nitter", "author_handle": "federalreserve", "title": "Fed signals rate cut"},
            {"publisher": "Nitter", "author_handle": "random_trader", "title": "rate cut soon"},
        ]

        counts = source_priority_counts(items, source_type="social")

        self.assertEqual(counts["authoritative_social"], 1)
        self.assertEqual(counts["social"], 1)
        self.assertEqual(authoritative_social_handles(items), ["@federalreserve"])

    def test_social_analyzer_exposes_authoritative_source_priority(self) -> None:
        result = SocialSentimentAnalyzer().analyze(
            SignalBundle(
                ticker="MACRO",
                items=[
                    SignalItem(
                        source_type="social",
                        provider="nitter",
                        title="Fed rate cut improves growth outlook",
                        author_handle="federalreserve",
                        publisher="Nitter",
                        scope_tags=["macro"],
                    )
                ],
            )
        )

        self.assertEqual(result["items"][0]["source_priority"], "authoritative_social")

    def test_authoritative_social_partially_mitigates_macro_confidence_cliff(self) -> None:
        active_themes = [{"saliency_weight": 0.65, "persistence_state": "new"}]
        empty_primary_counts = {"official": 0, "authoritative_social": 0, "trade": 0, "major": 0, "other": 0, "social": 0}

        generic_only = MacroContextService._confidence_percent(
            active_themes,
            news_item_count=0,
            social_item_count=1,
            diagnostics={"providers": ["Nitter"]},
            feed_errors=[],
            primary_source_counts=empty_primary_counts,
            authoritative_social_count=0,
            contradiction_count=0,
        )
        authoritative = MacroContextService._confidence_percent(
            active_themes,
            news_item_count=0,
            social_item_count=1,
            diagnostics={"providers": ["Nitter"]},
            feed_errors=[],
            primary_source_counts=empty_primary_counts,
            authoritative_social_count=1,
            contradiction_count=0,
        )
        primary_news = MacroContextService._confidence_percent(
            active_themes,
            news_item_count=1,
            social_item_count=0,
            diagnostics={"providers": ["Nitter"]},
            feed_errors=[],
            primary_source_counts={"official": 1, "authoritative_social": 0, "trade": 0, "major": 0, "other": 0, "social": 0},
            authoritative_social_count=0,
            contradiction_count=0,
        )

        self.assertGreater(authoritative, generic_only)
        self.assertLess(authoritative, primary_news)

    def test_event_extraction_ranks_authoritative_social_above_generic_social(self) -> None:
        # Provide a local definition so the assertion is independent from macro definitions.
        from trade_proposer_app.services.event_extraction import EventDefinition

        events = extract_ranked_events(
            primary_items=[],
            supporting_items=[
                {"publisher": "Nitter", "author_handle": "random_trader", "title": "rate cut announced"},
                {"publisher": "Nitter", "author_handle": "federalreserve", "title": "rate cut announced"},
            ],
            definitions=[EventDefinition("rates", "Rates", ("rate cut",))],
        )

        self.assertEqual(events[0]["source_priority"], "authoritative_social")
        self.assertGreater(events[0]["event_score"], 0.38)


if __name__ == "__main__":
    unittest.main()
