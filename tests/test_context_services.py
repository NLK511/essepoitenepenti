import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock

from trade_proposer_app.domain.models import IndustryContextRefreshPayload, IndustryContextSnapshot, MacroContextRefreshPayload, MacroContextSnapshot, NewsArticle, NewsBundle
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.summary import SummaryResult


class StubNewsService:
    def __init__(self, bundle: NewsBundle, sentiment: dict[str, object]) -> None:
        self.bundle = bundle
        self.sentiment = sentiment
        self.fetch_topics_calls: list[dict[str, object]] = []
        self.fetch_many_calls: list[dict[str, object]] = []

    def fetch_topics(
        self,
        subject: str,
        queries: list[str],
        *,
        per_query_limit: int = 4,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: str = "live",
        primary_only: bool = False,
    ) -> NewsBundle:
        self.fetch_topics_calls.append({
            "subject": subject,
            "queries": list(queries),
            "per_query_limit": per_query_limit,
            "start_at": start_at,
            "end_at": end_at,
            "request_mode": request_mode,
            "primary_only": primary_only,
        })
        return self.bundle

    def fetch_many(
        self,
        symbols: list[str],
        *,
        per_symbol_limit: int = 3,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: str = "live",
        primary_only: bool = False,
    ) -> NewsBundle:
        self.fetch_many_calls.append({
            "symbols": list(symbols),
            "per_symbol_limit": per_symbol_limit,
            "start_at": start_at,
            "end_at": end_at,
            "request_mode": request_mode,
            "primary_only": primary_only,
        })
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
        snapshot = MacroContextRefreshPayload(
                        subject_key="global_macro",
            subject_label="Global Macro",
            score=0.1,
            label="NEUTRAL",
            signals={"social_items": [{"title": "Traders discuss ECB and yield pressure", "body": "Markets stay focused on rates"}]},
            diagnostics={"providers": ["nitter"]},
            source_breakdown={"social": {"item_count": 1}},
        )

        context = MacroContextService(repository, news_service=news_service).create_from_refresh_payload(snapshot)

        self.assertEqual(context.source_breakdown["primary_news_item_count"], 1)
        self.assertNotIn("primary_news_evidence", context.missing_inputs)
        self.assertTrue(any(theme["key"] in {"bond_yield_spike", "european_monetary_policy"} for theme in context.active_themes))
        self.assertEqual(context.active_themes[0]["source_priority"], "official")
        self.assertEqual(context.active_themes[0]["source_priority_detail"]["label"], "official")
        self.assertIn(context.active_themes[0]["window_hint"], {"2d_5d", "1w_plus"})
        self.assertTrue(isinstance(context.active_themes[0]["window_hint_detail"]["label"], str))
        self.assertEqual(context.active_themes[0]["persistence_state"], "new")
        self.assertEqual(context.active_themes[0]["persistence_state_detail"]["label"], "new")
        self.assertTrue(any(item["key"] in {"euro_rates", "rates", "valuation_duration"} for item in context.active_themes[0]["transmission_channel_details"]))
        self.assertEqual(context.source_breakdown["primary_news_coverage_quality"], "high")
        self.assertIn("official:1", context.source_breakdown["primary_news_source_priorities"])
        self.assertIn("NewsAPI", context.source_breakdown["primary_news_providers"])
        self.assertGreaterEqual(context.metadata["event_lifecycle_summary"]["new_event_count"], 1)
        self.assertIn("Top macro event:", context.summary_text)
        self.assertIn("matters mainly through", context.summary_text)
        self.assertLess(context.saliency_score, 1.0)
        self.assertLess(context.confidence_percent, 100.0)
        self.assertTrue(news_service.fetch_topics_calls)
        self.assertEqual(news_service.fetch_topics_calls[0]["request_mode"], "live")
        self.assertTrue(news_service.fetch_topics_calls[0]["primary_only"])

    def test_macro_context_tracks_lifecycle_and_contradictions(self) -> None:
        repository = MagicMock()
        snapshot_obj = MacroContextSnapshot(
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
        repository.get_latest_macro_context_snapshot.return_value = snapshot_obj
        repository.get_latest_macro_context_snapshot_before.return_value = snapshot_obj
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
        snapshot = MacroContextRefreshPayload(
                        subject_key="global_macro",
            subject_label="Global Macro",
            score=-0.1,
            label="NEGATIVE",
            signals={"social_items": []},
            diagnostics={"providers": ["nitter"]},
            source_breakdown={},
        )

        context = MacroContextService(repository, news_service=news_service).create_from_refresh_payload(snapshot)

        energy = next(theme for theme in context.active_themes if theme["key"] == "oil_supply_risk")
        self.assertTrue(energy["contradiction_flag"])
        self.assertEqual(energy["persistence_state"], "new")
        self.assertEqual(energy["persistence_state_detail"]["label"], "new")
        contradiction_reason_map = {item["key"]: item for item in energy["contradiction_reason_details"]}
        self.assertTrue(set(contradiction_reason_map).issubset({"mixed_directional_evidence", "ambiguous_evidence_text", "direction_changed_vs_previous_snapshot"}))
        self.assertGreaterEqual(len(contradiction_reason_map), 1)
        self.assertTrue(any(item["key"] == "commodity_input_costs" for item in energy["transmission_channel_details"]))
        self.assertIn("Oil supply risk", context.metadata["event_lifecycle_summary"]["contradictory_event_labels"])
        self.assertTrue(any("contradictory evidence" in warning for warning in context.warnings))
        self.assertEqual(news_service.fetch_topics_calls[0]["request_mode"], "live")
        self.assertTrue(news_service.fetch_topics_calls[0]["primary_only"])

    def test_macro_context_uses_llm_summary_when_available(self) -> None:
        repository = MagicMock()
        snapshot_obj = MacroContextSnapshot(
            summary_text="Prior macro summary about rates and yields.",
            active_themes=[
                {"key": "bond_yields", "label": "Bond yields", "event_score": 0.8},
                {"key": "us_monetary_policy", "label": "U.S. monetary policy", "event_score": 0.7},
            ],
            regime_tags=["rates", "risk_off"],
        )
        repository.get_latest_macro_context_snapshot.return_value = snapshot_obj
        repository.get_latest_macro_context_snapshot_before.return_value = snapshot_obj
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
        snapshot = MacroContextRefreshPayload(
                        subject_key="global_macro",
            subject_label="Global Macro",
            score=0.0,
            label="NEUTRAL",
            signals={"social_items": []},
            diagnostics={"providers": ["nitter"]},
            source_breakdown={},
        )

        context = MacroContextService(repository, news_service=news_service, summary_service=summary_service).create_from_refresh_payload(snapshot)

        self.assertEqual(context.summary_text, summary_service.summarize_prompt.return_value.summary)
        self.assertEqual(context.metadata["context_summary_method"], "llm_summary")
        self.assertEqual(context.metadata["context_summary_backend"], "pi_agent")
        summary_service.summarize_prompt.assert_called_once()
        prompt = summary_service.summarize_prompt.call_args.args[0]
        self.assertIn("Previous snapshot context:", prompt)
        self.assertIn("previous top events: Bond yields, U.S. monetary policy", prompt)
        self.assertIn("previous regime tags: rates, risk_off", prompt)
        self.assertIn("previous summary: Prior macro summary about rates and yields.", prompt)
        self.assertIn("Change since previous snapshot:", prompt)

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
        snapshot = IndustryContextRefreshPayload(
                        subject_key="semiconductors",
            subject_label="Semiconductors",
            score=0.2,
            label="POSITIVE",
            coverage={"tracked_tickers": ["NVDA", "AMD"]},
            signals={"social_items": [{"title": "AI chip launch chatter", "body": "Conference cycle continues"}]},
            diagnostics={"queries": ["semiconductor", "chip demand"], "providers": ["nitter"]},
            source_breakdown={"social": {"item_count": 1}},
        )

        context = IndustryContextService(repository, news_service=news_service).create_from_refresh_payload(snapshot)

        self.assertEqual(context.source_breakdown["primary_news_item_count"], 1)
        self.assertNotIn("primary_industry_news_evidence", context.missing_inputs)
        self.assertIn("supply_chain_disruption", context.linked_industry_themes)
        self.assertIn("product_cycle", context.linked_industry_themes)
        self.assertEqual(context.active_drivers[0]["source_priority"], "trade")
        self.assertEqual(context.active_drivers[0]["source_priority_detail"]["label"], "trade")
        self.assertIn(context.active_drivers[0]["window_hint"], {"1d", "2d_5d", "1w_plus"})
        self.assertTrue(isinstance(context.active_drivers[0]["window_hint_detail"]["label"], str))
        self.assertTrue(any(driver.get("transmission_channel_details") for driver in context.active_drivers))
        self.assertTrue(any(item["key"] in {"supply_chain", "product_cycle"} for driver in context.active_drivers for item in driver.get("transmission_channel_details", [])))
        self.assertEqual(context.source_breakdown["primary_news_coverage_quality"], "high")
        self.assertIn("trade:1", context.source_breakdown["primary_news_source_priorities"])
        self.assertGreaterEqual(context.metadata["event_lifecycle_summary"]["new_event_count"], 1)
        self.assertEqual(context.metadata["context_summary_method"], "news_digest")
        self.assertEqual(context.metadata["triaged_primary_evidence"][0]["publisher"], "DigiTimes")
        self.assertLess(context.saliency_score, 1.0)
        self.assertLess(context.confidence_percent, 100.0)
        self.assertEqual(context.metadata["taxonomy_source_mode"], "split")
        self.assertEqual(context.metadata["ontology_profile"]["label"], "Semiconductors")
        self.assertTrue(any(item["key"] == "ai_capex" for item in context.metadata["ontology_profile"]["transmission_channel_details"]))
        self.assertTrue(context.metadata["matched_ontology_relationships"])
        self.assertTrue(any(item["target"] == "ai_capex" for item in context.metadata["matched_ontology_relationships"]))
        self.assertEqual(len(news_service.fetch_many_calls), 1)
        self.assertEqual(news_service.fetch_many_calls[0]["symbols"], ["NVDA", "AMD"])
        self.assertEqual(news_service.fetch_many_calls[0]["request_mode"], "live")
        self.assertTrue(news_service.fetch_many_calls[0]["primary_only"])

    def test_industry_context_uses_llm_summary_when_available(self) -> None:
        repository = MagicMock()
        snapshot_obj = IndustryContextSnapshot(
            industry_key="semiconductors",
            industry_label="Semiconductors",
            summary_text="Prior semiconductor summary about AI demand and rate pressure.",
            active_drivers=[
                {"key": "ai_theme", "label": "AI theme", "event_score": 0.9},
                {"key": "demand", "label": "Demand", "event_score": 0.7},
            ],
            linked_macro_themes=["rates", "yield_pressure"],
        )
        repository.get_latest_industry_context_snapshot.return_value = snapshot_obj
        repository.get_latest_industry_context_snapshot_before.return_value = snapshot_obj
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
        snapshot = IndustryContextRefreshPayload(
                        subject_key="semiconductors",
            subject_label="Semiconductors",
            score=0.2,
            label="POSITIVE",
            coverage={"tracked_tickers": ["NVDA", "AMD"]},
            signals={"social_items": []},
            diagnostics={"queries": ["semiconductor", "chip demand"], "providers": ["nitter"]},
            source_breakdown={},
        )

        context = IndustryContextService(repository, news_service=news_service, summary_service=summary_service).create_from_refresh_payload(snapshot)

        self.assertEqual(context.summary_text, summary_service.summarize_prompt.return_value.summary)
        self.assertEqual(context.metadata["context_summary_method"], "llm_summary")
        self.assertEqual(context.metadata["context_summary_backend"], "pi_agent")
        self.assertEqual(context.metadata["context_summary_model"], "test-model")
        self.assertTrue(context.metadata["triaged_primary_evidence"])
        summary_service.summarize_prompt.assert_called_once()
        prompt = summary_service.summarize_prompt.call_args.args[0]
        self.assertIn("Previous snapshot context:", prompt)
        self.assertIn("previous top drivers: AI theme, Demand", prompt)
        self.assertIn("previous linked macro themes: rates, yield_pressure", prompt)
        self.assertIn("previous summary: Prior semiconductor summary about AI demand and rate pressure.", prompt)
        self.assertIn("Change since previous snapshot:", prompt)
        self.assertIn("Ontology context:", prompt)
        self.assertIn("Matched ontology relationships:", prompt)
        self.assertIn("sector: Information Technology", prompt)
        self.assertTrue(context.metadata["matched_ontology_relationships"])


if __name__ == "__main__":
    unittest.main()
