import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd

from trade_proposer_app.domain.enums import RecommendationDirection
import json

from trade_proposer_app.domain.models import HistoricalMarketBar, NewsArticle, NewsBundle
from trade_proposer_app.services.news import SUMMARY_METHOD_NEWS_DIGEST
from trade_proposer_app.services.proposals import DEFAULT_SUMMARY_METHOD, ProposalExecutionError, ProposalService
from trade_proposer_app.services.summary import SummaryResult


def make_sample_history(days: int = 260) -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.today(), periods=days, freq="B")
    base = np.linspace(100, 110, len(dates))
    df = pd.DataFrame(
        {
            "Open": base * 0.995,
            "High": base * 1.01,
            "Low": base * 0.99,
            "Close": base,
            "Volume": np.full(len(dates), 100_0000),
        },
        index=dates,
    )
    return df


def make_downtrend_history(days: int = 260) -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.today(), periods=days, freq="B")
    base = np.linspace(120, 90, len(dates))
    df = pd.DataFrame(
        {
            "Open": base * 0.995,
            "High": base * 1.01,
            "Low": base * 0.99,
            "Close": base,
            "Volume": np.full(len(dates), 100_0000),
        },
        index=dates,
    )
    return df


class _FakeNewsService:
    def __init__(self, bundle: NewsBundle) -> None:
        self._bundle = bundle
        self.fetch_calls: list[dict[str, object]] = []

    def fetch(self, ticker: str, start_at=None, end_at=None, request_mode="live") -> NewsBundle:
        self.fetch_calls.append({"ticker": ticker, "start_at": start_at, "end_at": end_at, "request_mode": request_mode})
        self._bundle.ticker = ticker
        return self._bundle


class _StubSummaryService:
    def __init__(self, result: SummaryResult) -> None:
        self.result = result

    def summarize(self, request: object) -> SummaryResult:
        return self.result


class _StubSnapshotResolver:
    def resolve_macro_snapshot(self, as_of=None) -> dict[str, object]:
        return {
            "score": -0.2,
            "label": "NEGATIVE",
            "source": "snapshot_plus_context",
            "snapshot_id": 3,
            "subject_key": "global_macro",
            "subject_label": "Global Macro",
            "coverage": {"social_count": 4},
            "source_breakdown": {"social": {"score": -0.2, "item_count": 4}},
            "drivers": ["rates rising"],
            "context_snapshot_id": 13,
            "context_summary": "Macro context summary",
            "context_saliency_score": 0.74,
            "context_confidence_percent": 81.0,
            "context_regime_tags": ["risk_off"],
            "context_lifecycle": {"escalating_event_count": 1},
            "context_contradictory_event_labels": ["Oil and energy"],
            "context_active_events": [{"key": "bond_yields", "window_hint": "2d_5d"}],
            "diagnostics": {"warnings": ["macro snapshot used"]},
        }

    def resolve_industry_snapshot(self, ticker: str, as_of=None) -> dict[str, object]:
        return {
            "score": 0.3,
            "label": "POSITIVE",
            "source": "snapshot_plus_context",
            "snapshot_id": 5,
            "subject_key": "consumer_electronics",
            "subject_label": "Consumer Electronics",
            "coverage": {"social_count": 6},
            "source_breakdown": {"social": {"score": 0.3, "item_count": 6}},
            "drivers": [f"industry snapshot for {ticker}"],
            "context_snapshot_id": 15,
            "context_summary": "Industry context summary",
            "context_saliency_score": 0.68,
            "context_confidence_percent": 77.0,
            "context_regime_tags": ["rates"],
            "context_lifecycle": {"new_event_count": 1},
            "context_contradictory_event_labels": ["Guidance"],
            "context_active_events": [{"key": "guidance", "window_hint": "2d_5d"}],
            "diagnostics": {"warnings": ["industry snapshot used"]},
        }


class ProposalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ProposalService()

    def test_generate_requires_price_history(self) -> None:
        with patch.object(ProposalService, "_fetch_price_history", side_effect=ProposalExecutionError("no data")):
            with self.assertRaises(ProposalExecutionError):
                self.service.generate("AAPL")

    def test_generate_outputs_recommendation(self) -> None:
        history = make_sample_history()
        with patch.object(ProposalService, "_fetch_price_history", return_value=history):
            output = self.service.generate("AAPL")

        stop_pct = ((output.recommendation.entry_price - output.recommendation.stop_loss) / output.recommendation.entry_price) * 100
        take_pct = ((output.recommendation.take_profit - output.recommendation.entry_price) / output.recommendation.entry_price) * 100

        self.assertIn(output.recommendation.direction, {RecommendationDirection.LONG, RecommendationDirection.SHORT})
        self.assertGreater(output.recommendation.confidence, 0)
        if output.recommendation.direction == RecommendationDirection.LONG:
            self.assertGreater(output.recommendation.take_profit, output.recommendation.entry_price)
            self.assertLess(output.recommendation.stop_loss, output.recommendation.entry_price)
        else:
            self.assertLess(output.recommendation.take_profit, output.recommendation.entry_price)
            self.assertGreater(output.recommendation.stop_loss, output.recommendation.entry_price)
        self.assertLessEqual(stop_pct, 3.0)
        self.assertLessEqual(take_pct, 4.5)
        self.assertIn("feature_vectors", output.diagnostics.analysis_json)
        self.assertIn("aggregations", output.diagnostics.analysis_json)
        self.assertIsNotNone(output.diagnostics.feature_vector_json)

    def test_generate_resolves_direction_from_aggregated_score(self) -> None:
        history = make_downtrend_history()
        article = NewsArticle(
            title="Strong earnings beat",
            summary="Revenue guidance raised",
            publisher="Reuters",
            link="https://example.com/beat",
            published_at=None,
        )
        bundle = NewsBundle(ticker="", articles=[article], feeds_used=["Finnhub"])
        service = ProposalService(
            news_service=_FakeNewsService(bundle),
            summary_service=_StubSummaryService(
                SummaryResult(
                    summary="Positive catalyst digest",
                    method="news_digest",
                    backend="test",
                    model=None,
                    llm_error=None,
                    metadata={},
                    duration_seconds=None,
                )
            ),
        )
        service.sentiment_analyzer.analyze = MagicMock(
            return_value={
                "score": 0.8,
                "label": "POSITIVE",
                "contexts": [],
                "context_flags": {},
                "sentiment_volatility": 0.0,
                "polarity_trend": 0.9,
                "sources": ["Finnhub"],
                "news_items": [{"title": "Strong earnings beat", "link": "https://example.com/beat", "compound": 0.8}],
                "problems": [],
            }
        )

        with patch.object(ProposalService, "_fetch_price_history", return_value=history), patch.object(
            ProposalService,
            "_compute_aggregations",
            return_value={
                "direction_score": 0.82,
                "risk_offset_pct": 0.0,
                "risk_stop_offset": 0.0,
                "risk_take_profit_offset": 0.0,
                "entry_adjustment": 100.0,
                "entry_drift_signal": 0.0,
            },
        ):
            output = service.generate("AAPL")

        analysis = json.loads(output.diagnostics.analysis_json)
        self.assertEqual(output.recommendation.direction, RecommendationDirection.LONG)
        self.assertEqual(analysis["trade"]["direction"], "LONG")
        self.assertEqual(analysis["trade"]["technical_direction"], "SHORT")
        self.assertEqual(analysis["trade"]["direction_score"], 0.82)

    def test_fetch_price_history_retries_live_remote_failures(self) -> None:
        history = make_sample_history()
        service = ProposalService()
        with patch.object(service, "_fetch_price_history_remote", side_effect=[ProposalExecutionError("temporary"), pd.DataFrame(), history]) as remote_fetch:
            with patch("time.sleep", return_value=None):
                result = service._fetch_price_history("AAPL")

        self.assertEqual(remote_fetch.call_count, 3)
        self.assertEqual(len(result), len(history))

    def test_fetch_price_history_falls_back_to_local_store_after_remote_failures(self) -> None:
        history = make_sample_history()
        repo = Mock()
        repo.list_bars.return_value = [
            HistoricalMarketBar(
                ticker="AAPL",
                timeframe="1d",
                bar_time=index.to_pydatetime(),
                available_at=index.to_pydatetime(),
                open_price=float(row["Open"]),
                high_price=float(row["High"]),
                low_price=float(row["Low"]),
                close_price=float(row["Close"]),
                volume=float(row["Volume"]),
            )
            for index, row in history.iterrows()
        ]
        service = ProposalService(historical_market_data=repo)
        with patch.object(service, "_fetch_price_history_remote", side_effect=ProposalExecutionError("remote down")) as remote_fetch:
            with patch("time.sleep", return_value=None):
                result = service._fetch_price_history("AAPL")

        self.assertEqual(remote_fetch.call_count, 3)
        self.assertEqual(len(result), len(history))
        self.assertEqual(float(result.iloc[-1]["Close"]), float(history.iloc[-1]["Close"]))

    def test_build_news_summary_handles_mixed_inputs(self) -> None:
        article = NewsArticle(title="Article", summary=None, publisher=None, link=None, published_at=None)
        summary = self.service._build_news_summary([{"title": "Dict"}, article])
        self.assertEqual(summary, "Dict | Article")

    def test_apply_news_context_prefers_news_items(self) -> None:
        bundle = NewsBundle(ticker="", articles=[], feeds_used=["NewsAPI"])
        service = ProposalService(news_service=_FakeNewsService(bundle))
        sentiment_payload = {
            "score": 0.0,
            "label": "NEUTRAL",
            "contexts": [],
            "context_flags": {},
            "sentiment_volatility": 0.0,
            "polarity_trend": 0.0,
            "sources": ["NewsAPI"],
            "news_items": [{"title": "News Title", "link": "https://example.com", "compound": 0.5}],
            "problems": [],
        }
        service.sentiment_analyzer.analyze = MagicMock(return_value=sentiment_payload)
        context = service._apply_news_context({}, "AAPL")
        self.assertEqual(context["summary_text"], "News Title")
        self.assertEqual(context["summary_method"], SUMMARY_METHOD_NEWS_DIGEST)
        self.assertEqual(context["news_items"], sentiment_payload["news_items"])
        self.assertEqual(context["news_point_count"], 1)

    def test_apply_news_context_uses_replay_mode_for_historical_as_of(self) -> None:
        bundle = NewsBundle(ticker="", articles=[], feeds_used=["database"])
        news_service = _FakeNewsService(bundle)
        service = ProposalService(news_service=news_service)
        service.sentiment_analyzer.analyze = MagicMock(
            return_value={
                "score": 0.0,
                "label": "NEUTRAL",
                "contexts": [],
                "context_flags": {},
                "sentiment_volatility": 0.0,
                "polarity_trend": 0.0,
                "sources": ["database"],
                "news_items": [],
                "problems": [],
            }
        )

        service._apply_news_context({}, "AAPL", as_of=pd.Timestamp("2026-04-27T12:00:00Z").to_pydatetime())

        self.assertEqual(news_service.fetch_calls[0]["request_mode"], "replay")

    def test_apply_news_context_records_llm_summary(self) -> None:
        article = NewsArticle(
            title="LLM News",
            summary="Positive tone",
            publisher="Provider",
            link="https://example.com",
            published_at=None,
        )
        bundle = NewsBundle(ticker="", articles=[article], feeds_used=["NewsAPI"])
        service = ProposalService(
            news_service=_FakeNewsService(bundle),
            summary_service=_StubSummaryService(
                SummaryResult(
                    summary="LLM summary notes a strong earnings beat",
                    method="llm_summary",
                    backend="openai_api",
                    model="gpt-4o-mini",
                    llm_error=None,
                    metadata={"news_item_count": 1},
                    duration_seconds=0.4,
                )
            ),
        )
        sentiment_payload = {
            "score": 0.0,
            "label": "NEUTRAL",
            "contexts": [],
            "context_flags": {},
            "sentiment_volatility": 0.0,
            "polarity_trend": 0.0,
            "sources": ["NewsAPI"],
            "news_items": [{"title": "LLM News", "link": "https://example.com", "compound": 0.5}],
            "problems": [],
        }
        service.sentiment_analyzer.analyze = MagicMock(return_value=sentiment_payload)
        context = service._apply_news_context({}, "AAPL")
        self.assertEqual(context["summary_text"], "LLM summary notes a strong earnings beat")
        self.assertEqual(context["summary_method"], "llm_summary")
        self.assertEqual(context["summary_backend"], "openai_api")
        self.assertEqual(context["summary_model"], "gpt-4o-mini")
        self.assertEqual(context["summary_metadata"], {"news_item_count": 1})
        self.assertEqual(context["news_digest"], "LLM News")
        self.assertEqual(context["enhanced_sentiment_score"], context["sentiment_score"])
        self.assertGreater(context["sentiment_score"], 0.0)

    def test_apply_news_context_records_summary_problems(self) -> None:
        bundle = NewsBundle(
            ticker="",
            articles=[],
            feeds_used=["NewsAPI"],
        )
        service = ProposalService(
            news_service=_FakeNewsService(bundle),
            summary_service=_StubSummaryService(
                SummaryResult(
                    summary="Headline digest",
                    method="news_digest",
                    backend="openai_api",
                    model=None,
                    llm_error="openai api key is not configured",
                    metadata={"news_item_count": 1},
                    duration_seconds=None,
                )
            ),
        )
        sentiment_payload = {
            "score": 0.0,
            "label": "NEUTRAL",
            "contexts": [],
            "context_flags": {},
            "sentiment_volatility": 0.0,
            "polarity_trend": 0.0,
            "sources": ["NewsAPI"],
            "news_items": [{"title": "Headline", "compound": 0.0}],
            "problems": [],
        }
        service.sentiment_analyzer.analyze = MagicMock(return_value=sentiment_payload)
        context = service._apply_news_context({}, "AAPL")
        self.assertIn("openai api key is not configured", context["problems"])

    def test_apply_news_context_falls_back_to_articles(self) -> None:
        article = NewsArticle(
            title="Fallback Title",
            summary="Details",
            publisher="Provider",
            link="https://fallback",
            published_at=None,
        )
        bundle = NewsBundle(ticker="", articles=[article], feeds_used=["NewsAPI"])
        service = ProposalService(news_service=_FakeNewsService(bundle))
        sentiment_payload = {
            "score": 0.0,
            "label": "NEUTRAL",
            "contexts": [],
            "context_flags": {},
            "sentiment_volatility": 0.0,
            "polarity_trend": 0.0,
            "sources": ["NewsAPI"],
            "news_points": [],
            "problems": [],
        }
        service.sentiment_analyzer.analyze = MagicMock(return_value=sentiment_payload)
        context = service._apply_news_context({}, "AAPL")
        self.assertEqual(context["summary_text"], "Fallback Title")
        self.assertEqual(context["summary_method"], SUMMARY_METHOD_NEWS_DIGEST)
        self.assertEqual(context["news_items"], [])
        self.assertEqual(context["news_point_count"], 0)

    def test_generate_uses_macro_and_industry_snapshots_in_analysis_payload(self) -> None:
        history = make_sample_history()
        article = NewsArticle(
            title="Apple update",
            summary="Mixed outlook",
            publisher="Provider",
            link="https://example.com/apple",
            published_at=None,
        )
        bundle = NewsBundle(ticker="", articles=[article], feeds_used=["NewsAPI"])
        service = ProposalService(
            news_service=_FakeNewsService(bundle),
            snapshot_resolver=_StubSnapshotResolver(),
            summary_service=_StubSummaryService(
                SummaryResult(
                    summary="Apple sentiment digest",
                    method="news_digest",
                    backend="test",
                    model=None,
                    llm_error=None,
                    metadata={},
                    duration_seconds=None,
                )
            ),
        )
        service.sentiment_analyzer.analyze = MagicMock(
            return_value={
                "score": 0.1,
                "label": "POSITIVE",
                "contexts": [],
                "context_flags": {"context_tag_industry": 1.0},
                "sentiment_volatility": 0.0,
                "polarity_trend": 0.0,
                "sources": ["NewsAPI"],
                "news_items": [{"title": "Apple update", "compound": 0.1}],
                "problems": [],
                "coverage_insights": [],
                "keyword_hits": 1,
            }
        )

        with patch.object(ProposalService, "_fetch_price_history", return_value=history):
            output = service.generate("AAPL")

        analysis = json.loads(output.diagnostics.analysis_json or "{}")
        sentiment = analysis.get("sentiment", {})
        self.assertEqual(sentiment.get("macro", {}).get("source"), "snapshot_plus_context")
        self.assertEqual(sentiment.get("macro", {}).get("snapshot_id"), 3)
        self.assertEqual(sentiment.get("macro", {}).get("context_snapshot_id"), 13)
        self.assertEqual(sentiment.get("macro", {}).get("context_lifecycle", {}).get("escalating_event_count"), 1)
        self.assertEqual(sentiment.get("industry", {}).get("source"), "snapshot_plus_context")
        self.assertEqual(sentiment.get("industry", {}).get("snapshot_id"), 5)
        self.assertEqual(sentiment.get("industry", {}).get("context_snapshot_id"), 15)
        self.assertEqual(sentiment.get("industry", {}).get("subject_key"), "consumer_electronics")
        self.assertEqual(sentiment.get("ticker", {}).get("source"), "live")
        self.assertIn("industry snapshot used", sentiment.get("industry", {}).get("coverage_insights", []))


if __name__ == "__main__":
    unittest.main()
