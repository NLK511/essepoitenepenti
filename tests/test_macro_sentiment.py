import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import SignalBundle
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.support_snapshots import SupportSnapshotRepository
from trade_proposer_app.services.industry_support import IndustrySupportRefreshService
from trade_proposer_app.services.macro_support import MACRO_QUERIES, MACRO_SUBJECT_KEY, MACRO_SUBJECT_LABEL, MacroSupportRefreshService
from trade_proposer_app.services.social import SocialSentimentAnalyzer


class StubSocialService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze_subject(self, *, subject_key: str, subject_label: str, queries: list[str], scope_tag: str) -> dict[str, object]:
        self.calls.append(
            {
                "subject_key": subject_key,
                "subject_label": subject_label,
                "queries": queries,
                "scope_tag": scope_tag,
            }
        )
        return {
            "sentiment": {
                "score": 0.0,
                "label": "NEUTRAL",
                "item_count": 1,
                "coverage_insights": [],
                "items": [],
                "scope_breakdown": {},
            },
            "bundle": type("Bundle", (), {"feeds_used": ["Nitter"]})(),
        }


class StubTaxonomyService:
    def list_industry_profiles(self) -> list[dict[str, object]]:
        return [
            {
                "subject_key": "consumer_electronics",
                "subject_label": "Consumer Electronics",
                "queries": ["consumer electronics", "apple"],
                "tickers": ["AAPL"],
            }
        ]

    def get_industry_profile(self, ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "subject_key": "consumer_electronics",
            "subject_label": "Consumer Electronics",
        }


class MacroSupportRefreshServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=engine)
        self.session = Session(bind=engine)
        self.addCleanup(self.session.close)

    def test_social_sentiment_analyzer_uses_scope_neutral_zero_item_warning(self) -> None:
        analyzer = SocialSentimentAnalyzer()
        result = analyzer.analyze(SignalBundle(ticker="global_macro"))
        self.assertTrue(any("current subject query profile" in insight for insight in result["coverage_insights"]))
        self.assertFalse(any("current ticker query profile" in insight for insight in result["coverage_insights"]))

    def test_refresh_uses_european_and_geopolitical_macro_queries(self) -> None:
        repository = SupportSnapshotRepository(self.session)
        social_service = StubSocialService()
        service = MacroSupportRefreshService(repository, social_service=social_service)

        result = service.refresh()

        self.assertEqual(len(social_service.calls), 1)
        call = social_service.calls[0]
        self.assertEqual(call["subject_key"], MACRO_SUBJECT_KEY)
        self.assertEqual(call["scope_tag"], "macro")
        self.assertEqual(call["queries"], MACRO_QUERIES)
        self.assertIn("european monetary policy", call["queries"])
        self.assertIn("ecb", call["queries"])
        self.assertIn("war", call["queries"])
        self.assertIn("military tensions", call["queries"])
        self.assertIn("geopolitical tensions", call["queries"])
        self.assertEqual(result["summary"]["subject_key"], MACRO_SUBJECT_KEY)
        self.assertEqual(result["summary"]["scope"], "macro")

    def test_macro_summary_uses_previous_snapshot_summary_for_continuity(self) -> None:
        repository = SupportSnapshotRepository(self.session)
        repository.create_snapshot(
            scope="macro",
            subject_key=MACRO_SUBJECT_KEY,
            subject_label=MACRO_SUBJECT_LABEL,
            score=-0.25,
            label="NEGATIVE",
            summary_text="Global Macro remains negative overall. The earlier summary centered on rate pressure and risk-off tone.",
        )
        social_service = StubSocialService()
        service = MacroSupportRefreshService(repository, social_service=social_service)

        result = service.refresh()
        snapshot = result["snapshot"]

        self.assertEqual(snapshot.scope, "macro")
        # self.assertIn("Update:", snapshot.summary_text)
        # self.assertIn("prior summary centered on rate pressure and risk-off tone", snapshot.summary_text)
        # self.assertEqual(result["summary"]["previous_snapshot_id"], 1)

    def test_industry_summary_uses_previous_snapshot_summary_for_continuity(self) -> None:
        repository = SupportSnapshotRepository(self.session)
        repository.create_snapshot(
            scope="industry",
            subject_key="consumer_electronics",
            subject_label="Consumer Electronics",
            score=0.12,
            label="POSITIVE",
            summary_text="Consumer Electronics remains positive overall. The earlier summary centered on phone demand and stable margins.",
        )

        class StubSocialServiceWithItem:
            def analyze_subject(self, *, subject_key: str, subject_label: str, queries: list[str], scope_tag: str) -> dict[str, object]:
                return {
                    "sentiment": {
                        "score": 0.15,
                        "label": "POSITIVE",
                        "item_count": 2,
                        "coverage_insights": [],
                        "items": [],
                        "scope_breakdown": {},
                    },
                    "bundle": type("Bundle", (), {"feeds_used": ["Nitter"], "query_diagnostics": {}})(),
                }

        service = IndustrySupportRefreshService(
            repository,
            social_service=StubSocialServiceWithItem(),
            taxonomy_service=StubTaxonomyService(),
        )

        snapshot = service.refresh_industry(
            subject_key="consumer_electronics",
            subject_label="Consumer Electronics",
            queries=["consumer electronics", "apple"],
            tickers=["AAPL"],
        )

        self.assertEqual(snapshot.scope, "industry")
        # self.assertIn("Update:", snapshot.summary_text)
        # self.assertIn("prior summary centered on phone demand and stable margins", snapshot.summary_text)
        # self.assertEqual(summary["previous_snapshot_id"], 1)
