import json
import unittest
from unittest.mock import MagicMock

from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot, NewsArticle, NewsBundle, SupportSnapshot
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.summary import SummaryResult


class StubNewsService:
    def __init__(self, bundle: NewsBundle, sentiment: dict[str, object]) -> None:
        self.bundle = bundle
        self.sentiment = sentiment
        self.fetch_topics_calls: list[tuple[str, list[str]]] = []
        self.fetch_many_calls: list[list[str]] = []

    def fetch_topics(self, subject: str, queries: list[str], *, per_query_limit: int = 4) -> NewsBundle:
        self.fetch_topics_calls.append((subject, list(queries)))
        return self.bundle

    def fetch_many(self, symbols: list[str], *, per_symbol_limit: int = 3) -> NewsBundle:
        self.fetch_many_calls.append(list(symbols))
        return self.bundle

    def analyze_bundle(self, bundle: NewsBundle) -> dict[str, object]:
        return {"bundle": bundle, "sentiment": self.sentiment}


class ContextServiceTests(unittest.TestCase):
    def test_macro_context_prefers_primary_news_evidence(self) -> None:
        repository = MagicMock()
        repository.get_latest_macro_context_snapshot.return_value = None
        repository.create_macro_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="Global Macro",
            articles=[
                NewsArticle(
                    title="ECB signals eurozone rates may stay restrictive",
                    summary="Inflation remains sticky while bond yields climb",
                    publisher="European Central Bank",
                    link="https://example.com/ecb",
                )
            ],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "ECB signals eurozone rates may stay restrictive",
                        "summary": "Inflation remains sticky while bond yields climb",
                        "publisher": "European Central Bank",
                    }
                ],
                "coverage_insights": [],
            },
        )
        snapshot = SupportSnapshot(
            id=7,
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.1,
            label="NEUTRAL",
            signals_json=json.dumps(
                {
                    "social_items": [
                        {"title": "Traders discuss ECB and yield pressure", "body": "Markets stay focused on rates"}
                    ]
                }
            ),
            diagnostics_json=json.dumps({"providers": ["nitter"]}),
            source_breakdown_json=json.dumps({"social": {"item_count": 1}}),
        )

        context = MacroContextService(repository, news_service=news_service).create_from_support_snapshot(snapshot)

        self.assertEqual(context.source_breakdown["primary_news_item_count"], 1)
        self.assertNotIn("primary_news_evidence", context.missing_inputs)
        self.assertTrue(any(theme["key"] == "european_monetary_policy" for theme in context.active_themes))
        self.assertEqual(context.active_themes[0]["source_priority"], "official")
        self.assertEqual(context.active_themes[0]["window_hint"], "1w_plus")
        self.assertEqual(context.active_themes[0]["persistence_state"], "new")
        self.assertEqual(context.source_breakdown["primary_news_coverage_quality"], "high")
        self.assertIn("official:1", context.source_breakdown["primary_news_source_priorities"])
        self.assertIn("NewsAPI", context.source_breakdown["primary_news_providers"])
        self.assertGreaterEqual(context.metadata["event_lifecycle_summary"]["new_event_count"], 1)
        self.assertIn("Top macro event: European monetary policy.", context.summary_text)
        self.assertIn("expected transmission window is about a week or longer", context.summary_text)
        self.assertTrue(news_service.fetch_topics_calls)

    def test_macro_context_tracks_lifecycle_and_contradictions(self) -> None:
        repository = MagicMock()
        repository.get_latest_macro_context_snapshot.return_value = MacroContextSnapshot(
            summary_text="Older macro state",
            active_themes=[
                {
                    "key": "energy_oil",
                    "label": "Oil and energy",
                    "event_score": 0.9,
                    "evidence_direction": "positive",
                    "unique_evidence_count": 1,
                }
            ],
        )
        repository.create_macro_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="Global Macro",
            articles=[],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "Oil spikes as conflict risk escalates",
                        "summary": "Brent rises on geopolitical conflict and sanctions pressure",
                        "publisher": "Reuters",
                    },
                    {
                        "title": "Oil falls as traders expect de-escalation",
                        "summary": "Crude retreats as de-escalation hopes improve",
                        "publisher": "Reuters",
                    },
                ],
                "coverage_insights": [],
            },
        )
        snapshot = SupportSnapshot(
            id=8,
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=-0.1,
            label="NEGATIVE",
            signals_json=json.dumps({"social_items": []}),
            diagnostics_json=json.dumps({"providers": ["nitter"]}),
            source_breakdown_json=json.dumps({}),
        )

        context = MacroContextService(repository, news_service=news_service).create_from_support_snapshot(snapshot)

        energy = next(theme for theme in context.active_themes if theme["key"] == "energy_oil")
        self.assertTrue(energy["contradiction_flag"])
        self.assertIn(energy["persistence_state"], {"persistent", "escalating"})
        self.assertIn("Oil and energy", context.metadata["event_lifecycle_summary"]["contradictory_event_labels"])
        self.assertTrue(any("contradictory evidence" in warning for warning in context.warnings))

    def test_macro_context_uses_llm_summary_when_available(self) -> None:
        repository = MagicMock()
        repository.get_latest_macro_context_snapshot.return_value = None
        repository.create_macro_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="Global Macro",
            articles=[],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "ECB keeps restrictive tone while yields rise",
                        "summary": "Markets stay focused on European rates and valuation pressure",
                        "publisher": "Reuters",
                    },
                    {
                        "title": "Oil firms as conflict risk remains elevated",
                        "summary": "Energy markets continue pricing geopolitical supply risk",
                        "publisher": "Financial Times",
                    },
                ],
                "coverage_insights": [],
            },
        )
        summary_service = MagicMock()
        summary_service.summarize_prompt.return_value = SummaryResult(
            summary="European rates and geopolitical oil risk are the two main macro pressures, with policy and energy headlines leading the evidence.",
            method="llm_summary",
            backend="pi_agent",
            model="test-model",
            llm_error=None,
            metadata={"summary_kind": "macro_context"},
            duration_seconds=0.2,
        )
        snapshot = SupportSnapshot(
            id=9,
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.0,
            label="NEUTRAL",
            signals_json=json.dumps({"social_items": []}),
            diagnostics_json=json.dumps({"providers": ["nitter"]}),
            source_breakdown_json=json.dumps({}),
        )

        context = MacroContextService(repository, news_service=news_service, summary_service=summary_service).create_from_support_snapshot(snapshot)

        self.assertEqual(context.summary_text, summary_service.summarize_prompt.return_value.summary)
        self.assertEqual(context.metadata["context_summary_method"], "llm_summary")
        self.assertEqual(context.metadata["context_summary_backend"], "pi_agent")
        summary_service.summarize_prompt.assert_called_once()

    def test_industry_context_uses_tracked_ticker_news_first(self) -> None:
        repository = MagicMock()
        repository.get_latest_industry_context_snapshot.return_value = None
        repository.create_industry_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="NVDA, AMD",
            articles=[
                NewsArticle(
                    title="Chip demand stays strong as AI server backlog grows",
                    summary="Semiconductor conference highlights supply chain and pricing discipline",
                    publisher="DigiTimes",
                    link="https://example.com/chips",
                )
            ],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "Chip demand stays strong as AI server backlog grows",
                        "summary": "Semiconductor conference highlights supply chain and pricing discipline",
                        "publisher": "DigiTimes",
                    }
                ],
                "coverage_insights": [],
            },
        )
        snapshot = SupportSnapshot(
            id=12,
            scope="industry",
            subject_key="semiconductors",
            subject_label="Semiconductors",
            score=0.2,
            label="POSITIVE",
            coverage_json=json.dumps({"tracked_tickers": ["NVDA", "AMD"]}),
            signals_json=json.dumps(
                {
                    "social_items": [
                        {"title": "AI chip launch chatter", "body": "Conference cycle continues"}
                    ]
                }
            ),
            diagnostics_json=json.dumps({"queries": ["semiconductor", "chip demand"], "providers": ["nitter"]}),
            source_breakdown_json=json.dumps({"social": {"item_count": 1}}),
        )

        context = IndustryContextService(repository, news_service=news_service).create_from_support_snapshot(snapshot)

        self.assertEqual(context.source_breakdown["primary_news_item_count"], 1)
        self.assertNotIn("primary_industry_news_evidence", context.missing_inputs)
        self.assertIn("conference_cycle", context.linked_industry_themes)
        self.assertIn("semiconductor_theme", context.linked_industry_themes)
        self.assertEqual(context.active_drivers[0]["source_priority"], "trade")
        self.assertIn(context.active_drivers[0]["window_hint"], {"1d", "2d_5d", "1w_plus"})
        self.assertEqual(context.source_breakdown["primary_news_coverage_quality"], "high")
        self.assertIn("trade:1", context.source_breakdown["primary_news_source_priorities"])
        self.assertGreaterEqual(context.metadata["event_lifecycle_summary"]["new_event_count"], 1)
        self.assertEqual(context.metadata["context_summary_method"], "news_digest")
        self.assertEqual(context.metadata["triaged_primary_evidence"][0]["publisher"], "DigiTimes")
        self.assertEqual(news_service.fetch_many_calls, [["NVDA", "AMD"]])

    def test_industry_context_uses_llm_summary_when_available(self) -> None:
        repository = MagicMock()
        repository.get_latest_industry_context_snapshot.return_value = None
        repository.create_industry_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="NVDA, AMD",
            articles=[],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "Chip demand stays strong as AI server backlog grows",
                        "summary": "Semiconductor conference highlights supply chain and pricing discipline",
                        "publisher": "DigiTimes",
                    },
                    {
                        "title": "Treasury yields rise as rate-cut hopes fade",
                        "summary": "Macro rate pressure keeps valuation sensitivity in focus for growth names",
                        "publisher": "Reuters",
                    },
                ],
                "coverage_insights": [],
            },
        )
        summary_service = MagicMock()
        summary_service.summarize_prompt.return_value = SummaryResult(
            summary="Semiconductors are still being driven by AI and supply-chain demand signals, while rate pressure remains an important macro offset for duration-heavy names.",
            method="llm_summary",
            backend="pi_agent",
            model="test-model",
            llm_error=None,
            metadata={"summary_kind": "industry_context"},
            duration_seconds=0.2,
        )
        snapshot = SupportSnapshot(
            id=13,
            scope="industry",
            subject_key="semiconductors",
            subject_label="Semiconductors",
            score=0.2,
            label="POSITIVE",
            coverage_json=json.dumps({"tracked_tickers": ["NVDA", "AMD"]}),
            signals_json=json.dumps({"social_items": []}),
            diagnostics_json=json.dumps({"queries": ["semiconductor", "chip demand"], "providers": ["nitter"]}),
            source_breakdown_json=json.dumps({}),
        )

        context = IndustryContextService(repository, news_service=news_service, summary_service=summary_service).create_from_support_snapshot(snapshot)

        self.assertEqual(context.summary_text, summary_service.summarize_prompt.return_value.summary)
        self.assertEqual(context.metadata["context_summary_method"], "llm_summary")
        self.assertEqual(context.metadata["context_summary_backend"], "pi_agent")
        self.assertEqual(context.metadata["context_summary_model"], "test-model")
        self.assertTrue(context.metadata["triaged_primary_evidence"])
        summary_service.summarize_prompt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
