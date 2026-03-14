import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import RecommendationDirection, RecommendationState
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics
from trade_proposer_app.persistence.models import Base, RecommendationRecord, RunRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluations import RecommendationEvaluationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class RecommendationEvaluationServiceTests(unittest.TestCase):
    def _seed_trade_log(self, db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    ticker TEXT,
                    direction TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    status TEXT,
                    close_timestamp TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO trades (
                    timestamp, ticker, direction, entry_price, stop_loss, take_profit, status, close_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("2024-01-19 15:30:00", "AAPL", "LONG", 191.56, 186.00, 198.50, "LOSS", "2024-01-31 20:00:00"),
                    ("2024-02-02 15:30:00", "AAPL", "SHORT", 185.85, 190.50, 178.00, "WIN", "2024-02-21 20:00:00"),
                    ("2024-03-14 15:30:00", "AAPL", "LONG", 172.62, 167.50, 178.50, "WIN", "2024-04-01 20:00:00"),
                    ("2024-04-11 15:30:00", "AAPL", "SHORT", 175.04, 179.80, 169.50, "LOSS", "2024-05-03 20:00:00"),
                    ("2024-05-29 15:30:00", "AAPL", "LONG", 190.29, 184.00, 197.50, "PENDING", None)
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def _set_recommendation_created_at(self, session: Session, recommendation_id: int, run_id: int, created_at: datetime) -> None:
        recommendation_record = session.get(RecommendationRecord, recommendation_id)
        run_record = session.get(RunRecord, run_id)
        assert recommendation_record is not None
        assert run_record is not None
        recommendation_record.created_at = created_at
        run_record.created_at = created_at
        run_record.updated_at = created_at
        run_record.completed_at = created_at
        session.commit()

    def test_sync_recommendation_states_from_trade_log_updates_matching_recommendation(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Eval Job", ["AAPL"], None)
        run = runs.enqueue(job.id or 0)
        claimed = runs.claim_next_queued_run()
        assert claimed is not None
        stored = runs.add_recommendation(
            run.id or 0,
            Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=81.0,
                entry_price=101.0,
                stop_loss=97.0,
                take_profit=111.0,
                indicator_summary="Above SMA200 · RSI 58.0",
            ),
            RunDiagnostics(raw_output="raw output"),
        )

        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        try:
            db_path = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data" / "trade_log.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        ticker TEXT,
                        direction TEXT,
                        entry_price REAL,
                        stop_loss REAL,
                        take_profit REAL,
                        status TEXT,
                        close_timestamp TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO trades (
                        timestamp, ticker, direction, entry_price, stop_loss, take_profit, status, close_timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-03-12 09:30:00",
                        "AAPL",
                        "LONG",
                        101.0,
                        97.0,
                        111.0,
                        "WIN",
                        "2026-03-14 16:00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            synced = RecommendationEvaluationService(session).sync_recommendation_states_from_trade_log()
            refreshed = runs.get_recommendation(stored.id or 0)

            self.assertEqual(synced, 1)
            self.assertEqual(refreshed.state, RecommendationState.WIN)
            self.assertIsNotNone(refreshed.evaluated_at)
        finally:
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()

    def test_sync_recommendation_states_uses_realistic_aapl_history_and_nearest_matching_trade(self) -> None:
        session = create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("AAPL Eval Job", ["AAPL"], None)

        cases = [
            (datetime(2024, 1, 19, 15, 31, tzinfo=timezone.utc), RecommendationDirection.LONG, 191.56, 186.00, 198.50, RecommendationState.LOSS),
            (datetime(2024, 2, 2, 15, 31, tzinfo=timezone.utc), RecommendationDirection.SHORT, 185.85, 190.50, 178.00, RecommendationState.WIN),
            (datetime(2024, 3, 14, 15, 31, tzinfo=timezone.utc), RecommendationDirection.LONG, 172.62, 167.50, 178.50, RecommendationState.WIN),
            (datetime(2024, 4, 11, 15, 31, tzinfo=timezone.utc), RecommendationDirection.SHORT, 175.04, 179.80, 169.50, RecommendationState.LOSS),
            (datetime(2024, 5, 29, 15, 31, tzinfo=timezone.utc), RecommendationDirection.LONG, 190.29, 184.00, 197.50, RecommendationState.PENDING),
        ]

        stored_ids: list[int] = []
        for index, (created_at, direction, entry_price, stop_loss, take_profit, _expected_state) in enumerate(cases, start=1):
            run = runs.create(job.id or 0, "completed")
            recommendation = runs.add_recommendation(
                run.id or 0,
                Recommendation(
                    ticker="AAPL",
                    direction=direction,
                    confidence=60.0 + index,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    indicator_summary=f"AAPL historical setup #{index}",
                ),
                RunDiagnostics(raw_output=f"seeded recommendation {index}"),
            )
            self._set_recommendation_created_at(session, recommendation.id or 0, run.id or 0, created_at)
            stored_ids.append(recommendation.id or 0)

        duplicate_signature_run = runs.create(job.id or 0, "completed")
        duplicate_signature = runs.add_recommendation(
            duplicate_signature_run.id or 0,
            Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=79.0,
                entry_price=191.56,
                stop_loss=186.00,
                take_profit=198.50,
                indicator_summary="AAPL duplicate signature later in time",
            ),
            RunDiagnostics(raw_output="duplicate signature"),
        )
        self._set_recommendation_created_at(
            session,
            duplicate_signature.id or 0,
            duplicate_signature_run.id or 0,
            datetime(2024, 1, 22, 15, 31, tzinfo=timezone.utc),
        )

        unmatched_run = runs.create(job.id or 0, "completed")
        unmatched = runs.add_recommendation(
            unmatched_run.id or 0,
            Recommendation(
                ticker="AAPL",
                direction=RecommendationDirection.LONG,
                confidence=55.0,
                entry_price=188.10,
                stop_loss=180.00,
                take_profit=196.00,
                indicator_summary="No matching trade log entry",
            ),
            RunDiagnostics(raw_output="unmatched recommendation"),
        )
        self._set_recommendation_created_at(
            session,
            unmatched.id or 0,
            unmatched_run.id or 0,
            datetime(2024, 1, 25, 15, 31, tzinfo=timezone.utc),
        )

        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        try:
            db_path = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data" / "trade_log.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._seed_trade_log(db_path)

            synced = RecommendationEvaluationService(session).sync_recommendation_states_from_trade_log()

            self.assertEqual(synced, 5)
            for recommendation_id, expected_state in zip(stored_ids, [case[5] for case in cases], strict=True):
                refreshed = runs.get_recommendation(recommendation_id)
                self.assertEqual(refreshed.state, expected_state)
                if expected_state == RecommendationState.PENDING:
                    self.assertIsNone(refreshed.evaluated_at)
                else:
                    self.assertIsNotNone(refreshed.evaluated_at)

            duplicate_refreshed = runs.get_recommendation(duplicate_signature.id or 0)
            self.assertEqual(duplicate_refreshed.state, RecommendationState.LOSS)
            self.assertIsNotNone(duplicate_refreshed.evaluated_at)

            unmatched_refreshed = runs.get_recommendation(unmatched.id or 0)
            self.assertEqual(unmatched_refreshed.state, RecommendationState.PENDING)
            self.assertIsNone(unmatched_refreshed.evaluated_at)
        finally:
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()


if __name__ == "__main__":
    unittest.main()
