import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import JobType, RecommendationDirection, RunStatus
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics
from trade_proposer_app.persistence.models import Base, RecommendationRecord, RunRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluations import RecommendationEvaluationService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.optimizations import WeightOptimizationError, WeightOptimizationService
from trade_proposer_app.services.proposals import ProposalService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class WeightOptimizationServiceTests(unittest.TestCase):
    def _seed_trade_log(self, db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    close_timestamp TEXT,
                    ticker TEXT,
                    direction TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    confidence REAL,
                    status TEXT,
                    analysis_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO trades (
                    timestamp, close_timestamp, ticker, direction, entry_price, stop_loss, take_profit, confidence, status, analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "2024-01-19 15:30:00",
                        "2024-01-31 20:00:00",
                        "AAPL",
                        "LONG",
                        191.56,
                        186.00,
                        198.50,
                        72.0,
                        "LOSS",
                        json.dumps({"note": "Based on AAPL trading near 191.56 in January 2024"}),
                    ),
                    (
                        "2024-02-02 15:30:00",
                        "2024-02-21 20:00:00",
                        "AAPL",
                        "SHORT",
                        185.85,
                        190.50,
                        178.00,
                        68.0,
                        "WIN",
                        json.dumps({"note": "Based on AAPL trading near 185.85 after the February 2024 earnings window"}),
                    ),
                    (
                        "2024-03-14 15:30:00",
                        "2024-04-01 20:00:00",
                        "AAPL",
                        "LONG",
                        172.62,
                        167.50,
                        178.50,
                        75.0,
                        "WIN",
                        json.dumps({"note": "Based on AAPL trading near 172.62 in mid-March 2024"}),
                    ),
                    (
                        "2024-04-11 15:30:00",
                        "2024-05-03 20:00:00",
                        "AAPL",
                        "SHORT",
                        175.04,
                        179.80,
                        169.50,
                        64.0,
                        "LOSS",
                        json.dumps({"note": "Based on AAPL trading near 175.04 in April 2024"}),
                    ),
                    (
                        "2024-05-29 15:30:00",
                        None,
                        "AAPL",
                        "LONG",
                        190.29,
                        184.00,
                        197.50,
                        71.0,
                        "PENDING",
                        json.dumps({"note": "Based on AAPL trading near 190.29 in late May 2024"}),
                    ),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def _seed_aapl_recommendations(self, session: Session, run_repository: RunRepository, job_repository: JobRepository) -> list[int]:
        job = job_repository.create(name="AAPL swing proposals", tickers=["AAPL"], schedule=None)
        cases = [
            (datetime(2024, 1, 19, 15, 31, tzinfo=timezone.utc), RecommendationDirection.LONG, 191.56, 186.00, 198.50, 72.0),
            (datetime(2024, 2, 2, 15, 31, tzinfo=timezone.utc), RecommendationDirection.SHORT, 185.85, 190.50, 178.00, 68.0),
            (datetime(2024, 3, 14, 15, 31, tzinfo=timezone.utc), RecommendationDirection.LONG, 172.62, 167.50, 178.50, 75.0),
            (datetime(2024, 4, 11, 15, 31, tzinfo=timezone.utc), RecommendationDirection.SHORT, 175.04, 179.80, 169.50, 64.0),
            (datetime(2024, 5, 29, 15, 31, tzinfo=timezone.utc), RecommendationDirection.LONG, 190.29, 184.00, 197.50, 71.0),
        ]

        recommendation_ids: list[int] = []
        for index, (created_at, direction, entry_price, stop_loss, take_profit, confidence) in enumerate(cases, start=1):
            run = run_repository.create(job.id or 0, RunStatus.COMPLETED.value)
            recommendation = run_repository.add_recommendation(
                run.id or 0,
                Recommendation(
                    ticker="AAPL",
                    direction=direction,
                    confidence=confidence,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    indicator_summary=f"Historical AAPL setup #{index}",
                ),
                RunDiagnostics(raw_output=f"seeded recommendation {index}"),
            )
            recommendation_record = session.get(RecommendationRecord, recommendation.id)
            run_record = session.get(RunRecord, run.id)
            assert recommendation_record is not None
            assert run_record is not None
            recommendation_record.created_at = created_at
            run_record.created_at = created_at
            run_record.updated_at = created_at
            run_record.completed_at = created_at
            recommendation_ids.append(recommendation.id or 0)
        session.commit()
        return recommendation_ids
    def test_count_resolved_trades_counts_win_and_loss_rows(self) -> None:
        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        try:
            db_path = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data" / "trade_log.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT)")
                connection.executemany(
                    "INSERT INTO trades (status) VALUES (?)",
                    [("WIN",), ("LOSS",), ("PENDING",), (None,)],
                )
                connection.commit()
            finally:
                connection.close()

            service = WeightOptimizationService(minimum_resolved_trades=1)
            self.assertEqual(service.count_resolved_trades(), 2)
        finally:
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()

    def test_execute_rejects_when_resolved_trade_threshold_not_met(self) -> None:
        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        try:
            script_path = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "scripts" / "optimize_weights.py"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("print('optimize')\n")

            db_path = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data" / "trade_log.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT)")
                connection.execute("INSERT INTO trades (status) VALUES ('WIN')")
                connection.commit()
            finally:
                connection.close()

            service = WeightOptimizationService(minimum_resolved_trades=5)
            with self.assertRaises(WeightOptimizationError) as context:
                service.execute()
            self.assertIn("minimum is 5", str(context.exception))
        finally:
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()

    def test_execute_returns_summary_and_artifact_fingerprints(self) -> None:
        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        try:
            script_path = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "scripts" / "optimize_weights.py"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("print('optimize')\n")

            data_dir = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            weights_path = data_dir / "weights.json"
            weights_path.write_text(json.dumps({"alpha": 1}))

            db_path = data_dir / "trade_log.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT)")
                connection.executemany(
                    "INSERT INTO trades (status) VALUES (?)",
                    [("WIN",), ("LOSS",), ("WIN",)],
                )
                connection.commit()
            finally:
                connection.close()

            service = WeightOptimizationService(minimum_resolved_trades=2)

            def fake_run(*args, **kwargs):
                weights_path.write_text(json.dumps({"alpha": 2}))
                class Result:
                    returncode = 0
                    stdout = "optimization complete\n"
                    stderr = ""
                return Result()

            with patch("trade_proposer_app.services.optimizations.subprocess.run", side_effect=fake_run):
                summary, artifact = service.execute()

            self.assertTrue(summary["weights_changed"])
            self.assertEqual(summary["resolved_trade_count"], 3)
            self.assertEqual(artifact["weights_path"], str(weights_path))
            self.assertTrue(artifact["before"]["exists"])
            self.assertTrue(artifact["after"]["exists"])
            self.assertIsNotNone(artifact["backup"])
            self.assertTrue(artifact["rollback_available"])
            self.assertNotEqual(artifact["before"]["sha256"], artifact["after"]["sha256"])
        finally:
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()

    def test_rollback_latest_backup_restores_previous_weights(self) -> None:
        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        try:
            data_dir = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            weights_path = data_dir / "weights.json"
            weights_path.write_text(json.dumps({"alpha": 1}))

            service = WeightOptimizationService(minimum_resolved_trades=2)
            backup = service.create_backup()
            self.assertIsNotNone(backup)

            weights_path.write_text(json.dumps({"alpha": 99}))
            rollback = service.rollback_latest_backup()

            self.assertEqual(json.loads(weights_path.read_text())["alpha"], 1)
            self.assertEqual(rollback["status"], "rolled_back")
            self.assertEqual(rollback["weights_path"], str(weights_path))
        finally:
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()

    def test_optimization_job_runs_on_evaluated_realistic_aapl_dataset(self) -> None:
        prototype_root = tempfile.TemporaryDirectory()
        original_prototype_repo_path = settings.prototype_repo_path
        settings.prototype_repo_path = prototype_root.name
        session = create_session()
        try:
            scripts_dir = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            optimization_script_path = scripts_dir / "optimize_weights.py"
            optimization_script_path.write_text("print('optimize weights from evaluated AAPL recommendations')\n")

            data_dir = Path(prototype_root.name) / ".pi" / "skills" / "trade-proposer" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            weights_path = data_dir / "weights.json"
            weights_path.write_text(json.dumps({"trend": 1.0, "sentiment": 0.8, "risk": 1.1}))
            trade_log_path = data_dir / "trade_log.db"
            self._seed_trade_log(trade_log_path)

            jobs = JobRepository(session)
            runs = RunRepository(session)
            recommendation_ids = self._seed_aapl_recommendations(session, runs, jobs)

            price_history = pd.DataFrame(
                {
                    "High": [193.0, 188.0, 180.0, 181.0, 195.0],
                    "Low": [185.0, 177.0, 169.0, 172.0, 188.0],
                },
                index=pd.to_datetime(
                    [
                        "2024-01-19T17:00:00Z",
                        "2024-02-02T17:00:00Z",
                        "2024-03-14T17:00:00Z",
                        "2024-04-11T17:00:00Z",
                        "2024-05-29T17:00:00Z",
                    ],
                    utc=True,
                ),
            )

            def fake_price_history(ticker, start_date, end_date):
                if ticker.upper() == "AAPL":
                    return price_history
                return pd.DataFrame()

            with patch.object(RecommendationEvaluationService, "_download_price_history", side_effect=fake_price_history):
                evaluation_result = RecommendationEvaluationService(session).run_evaluation()

            def fake_subprocess_run(command, *args, **kwargs):
                script_name = Path(command[1]).name
                class Result:
                    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout
                        self.stderr = stderr

                if script_name == "optimize_weights.py":
                    weights_path.write_text(json.dumps({"trend": 1.15, "sentiment": 0.72, "risk": 0.95}))
                    return Result(0, "optimized weights from 4 resolved AAPL trades\n")
                raise AssertionError(f"unexpected subprocess invocation: {command}")

            self.assertEqual(evaluation_result.evaluated_trade_log_entries, 5)
            self.assertEqual(evaluation_result.synced_recommendations, 4)
            self.assertEqual(evaluation_result.win_recommendations, 2)
            self.assertEqual(evaluation_result.loss_recommendations, 2)
            self.assertEqual(evaluation_result.pending_recommendations, 1)

            evaluated_states = {
                recommendation.id: recommendation.state.value
                for recommendation in (runs.get_recommendation(recommendation_id) for recommendation_id in recommendation_ids)
            }
            self.assertEqual(
                [evaluated_states[recommendation_id] for recommendation_id in recommendation_ids],
                ["LOSS", "WIN", "WIN", "LOSS", "PENDING"],
            )

            optimization_job = jobs.create(
                name="Optimize from evaluated AAPL history",
                tickers=[],
                schedule=None,
                job_type=JobType.WEIGHT_OPTIMIZATION,
            )
            execution = JobExecutionService(
                jobs=jobs,
                runs=runs,
                proposals=ProposalService(),
                optimizations=WeightOptimizationService(minimum_resolved_trades=4),
            )
            queued_run = execution.enqueue_job(optimization_job.id or 0)

            with patch("trade_proposer_app.services.optimizations.subprocess.run", side_effect=fake_subprocess_run):
                processed_run, recommendations = execution.process_next_queued_run()

            self.assertIsNotNone(processed_run)
            assert processed_run is not None
            self.assertEqual(processed_run.id, queued_run.id)
            self.assertEqual(processed_run.status, RunStatus.COMPLETED.value)
            self.assertEqual(recommendations, [])

            summary = json.loads(runs.get_run(processed_run.id or 0).summary_json or "{}")
            artifact = json.loads(runs.get_run(processed_run.id or 0).artifact_json or "{}")
            self.assertEqual(summary["resolved_trade_count"], 4)
            self.assertEqual(summary["minimum_resolved_trades"], 4)
            self.assertTrue(summary["weights_changed"])
            self.assertEqual(artifact["weights_path"], str(weights_path))
            self.assertTrue(artifact["rollback_available"])
            self.assertEqual(json.loads(weights_path.read_text()), {"trend": 1.15, "sentiment": 0.72, "risk": 0.95})
        finally:
            session.close()
            settings.prototype_repo_path = original_prototype_repo_path
            prototype_root.cleanup()


if __name__ == "__main__":
    unittest.main()
