import pandas as pd
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import RecommendationDirection
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics
from trade_proposer_app.persistence.models import Base, RecommendationRecord, RunRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluations import RecommendationEvaluationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _set_recommendation_created_at(session: Session, recommendation_id: int, run_id: int, created_at: datetime) -> None:
    recommendation_record = session.get(RecommendationRecord, recommendation_id)
    run_record = session.get(RunRecord, run_id)
    assert recommendation_record is not None
    assert run_record is not None
    recommendation_record.created_at = created_at
    run_record.created_at = created_at
    run_record.updated_at = created_at
    run_record.completed_at = created_at
    session.commit()


class RecommendationEvaluationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = create_session()
        self.jobs = JobRepository(self.session)
        self.runs = RunRepository(self.session)
        job = self.jobs.create("Evaluation Job", ["AAPL", "MSFT"], None)
        run = self.runs.enqueue(job.id or 0)
        claimed = self.runs.claim_next_queued_run()
        assert claimed is not None
        self.run = run

    def tearDown(self) -> None:
        self.session.close()

    def _create_recommendation(
        self,
        direction: RecommendationDirection,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        created_at: datetime,
    ) -> Recommendation:
        recommendation = self.runs.add_recommendation(
            self.run.id or 0,
            Recommendation(
                ticker="AAPL" if direction == RecommendationDirection.LONG else "MSFT",
                direction=direction,
                confidence=75.0,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                indicator_summary="test",
            ),
            RunDiagnostics(),
        )
        _set_recommendation_created_at(self.session, recommendation.id or 0, self.run.id or 0, created_at)
        return recommendation

    def test_run_evaluation_marks_win_loss_and_pending_states(self) -> None:
        long_win = self._create_recommendation(
            RecommendationDirection.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=105.0,
            created_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
        )
        short_win = self._create_recommendation(
            RecommendationDirection.SHORT,
            entry_price=180.0,
            stop_loss=190.0,
            take_profit=170.0,
            created_at=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
        )
        pending = self._create_recommendation(
            RecommendationDirection.LONG,
            entry_price=120.0,
            stop_loss=90.0,
            take_profit=130.0,
            created_at=datetime(2024, 1, 3, 14, 0, tzinfo=timezone.utc),
        )

        price_history_aapl = pd.DataFrame(
            {
                "High": [108.0, 103.0],
                "Low": [100.0, 101.0],
            },
            index=pd.to_datetime(["2024-01-02T17:00:00Z", "2024-01-03T17:00:00Z"], utc=True),
        )
        price_history_msft = pd.DataFrame(
            {
                "High": [189.0],
                "Low": [169.0],
            },
            index=pd.to_datetime(["2024-01-02T17:00:00Z"], utc=True),
        )

        def fake_download(ticker: str, start_date: datetime, end_date: datetime):
            if ticker.upper() == "AAPL":
                return price_history_aapl
            if ticker.upper() == "MSFT":
                return price_history_msft
            return pd.DataFrame()

        with patch.object(RecommendationEvaluationService, "_download_price_history", side_effect=fake_download):
            result = RecommendationEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_trade_log_entries, 3)
        self.assertEqual(result.synced_recommendations, 2)
        self.assertEqual(result.win_recommendations, 2)
        self.assertEqual(result.loss_recommendations, 0)
        self.assertEqual(result.pending_recommendations, 1)
        self.assertIn("thresholds not hit yet", result.output)

        refreshed_long = self.runs.get_recommendation(long_win.id or 0)
        refreshed_short = self.runs.get_recommendation(short_win.id or 0)
        refreshed_pending = self.runs.get_recommendation(pending.id or 0)
        self.assertEqual(refreshed_long.state.value, "WIN")
        self.assertEqual(refreshed_short.state.value, "WIN")
        self.assertEqual(refreshed_pending.state.value, "PENDING")

    def test_run_evaluation_detects_missing_price_history(self) -> None:
        recommendation = self._create_recommendation(
            RecommendationDirection.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=105.0,
            created_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
        )

        with patch.object(RecommendationEvaluationService, "_download_price_history", return_value=pd.DataFrame()):
            result = RecommendationEvaluationService(self.session).run_evaluation(recommendation_ids=[recommendation.id or 0])

        self.assertEqual(result.synced_recommendations, 0)
        self.assertEqual(result.pending_recommendations, 1)
        self.assertIn("no price history", result.output.lower())

        refreshed = self.runs.get_recommendation(recommendation.id or 0)
        self.assertEqual(refreshed.state.value, "PENDING")


if __name__ == "__main__":
    unittest.main()
