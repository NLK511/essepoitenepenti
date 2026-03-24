import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import SignalBundle
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.services.macro_sentiment import MACRO_QUERIES, MACRO_SUBJECT_KEY, MacroSentimentService
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
                "item_count": 0,
                "coverage_insights": [],
                "items": [],
                "scope_breakdown": {},
            },
            "bundle": type("Bundle", (), {"feeds_used": ["Nitter"]})(),
        }


class MacroSentimentServiceTests(unittest.TestCase):
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
        repository = SentimentSnapshotRepository(self.session)
        social_service = StubSocialService()
        service = MacroSentimentService(repository, social_service=social_service)

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
