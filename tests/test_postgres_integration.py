import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService


@unittest.skipUnless(os.getenv("POSTGRES_TEST_DATABASE_URL"), "requires POSTGRES_TEST_DATABASE_URL")
class PostgresMigrationIntegrationTest(unittest.TestCase):
    def test_migrations_upgrade_clean_postgres_database(self) -> None:
        database_url = os.environ["POSTGRES_TEST_DATABASE_URL"]
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))

            env = dict(os.environ)
            env["DATABASE_URL"] = database_url
            subprocess.run(
                [sys.executable, "-m", "trade_proposer_app.migrations"],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
            )

            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())
            self.assertIn("watchlists", table_names)
            self.assertIn("jobs", table_names)
            self.assertIn("runs", table_names)
            self.assertIn("recommendation_plans", table_names)
            self.assertIn("recommendation_outcomes", table_names)
            self.assertNotIn("recommendations", table_names)
        finally:
            engine.dispose()

    def test_recompute_actual_eog_plans_315_and_635_against_real_postgres_records(self) -> None:
        database_url = os.environ["POSTGRES_TEST_DATABASE_URL"]
        engine = create_engine(database_url, future=True)
        try:
            session = Session(bind=engine)
            try:
                plan_rows = session.scalars(
                    select(RecommendationPlanRecord).where(RecommendationPlanRecord.id.in_([315, 635]))
                ).all()
                plan_ids = {row.id for row in plan_rows if row.id is not None}
                self.assertEqual(plan_ids, {315, 635})

                market_data = HistoricalMarketDataRepository(session)
                market_data.upsert_bar(
                    HistoricalMarketBar(
                        ticker="EOG",
                        timeframe="1d",
                        bar_time=datetime(2026, 3, 30, 0, 0, tzinfo=timezone.utc),
                        available_at=datetime(2026, 3, 30, 23, 59, 59, tzinfo=timezone.utc),
                        open_price=151.03,
                        high_price=152.18,
                        low_price=148.75,
                        close_price=150.98,
                        volume=1_000_000,
                        source="integration_test",
                        source_tier="research",
                    )
                )
                market_data.upsert_bar(
                    HistoricalMarketBar(
                        ticker="EOG",
                        timeframe="5m",
                        bar_time=datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc),
                        available_at=datetime(2026, 3, 31, 15, 5, tzinfo=timezone.utc),
                        open_price=150.54,
                        high_price=150.78,
                        low_price=150.52,
                        close_price=150.57,
                        volume=122_807,
                        source="integration_test",
                        source_tier="research",
                    )
                )

                jobs = JobRepository(session)
                runs = RunRepository(session)
                job = jobs.create(f"Integration evaluation recompute {uuid4()}", ["EOG"], None, enabled=False)
                run = runs.enqueue(job.id or 0)

                result = RecommendationPlanEvaluationService(session).run_evaluation(
                    recommendation_plan_ids=[315, 635],
                    run_id=run.id,
                    as_of=datetime(2026, 3, 31, 20, 0, tzinfo=timezone.utc),
                )

                self.assertEqual(result.evaluated_recommendation_plans, 2)
                self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
                self.assertEqual(result.pending_recommendation_plan_outcomes, 1)

                outcomes = RecommendationOutcomeRepository(session).get_outcomes_by_plan_ids([315, 635])
                self.assertEqual(outcomes[315].outcome, "loss")
                self.assertEqual(outcomes[635].outcome, "no_entry")
                self.assertEqual(outcomes[315].run_id, run.id)
                self.assertEqual(outcomes[635].run_id, run.id)
                self.assertTrue(outcomes[315].entry_touched)
                self.assertTrue(outcomes[315].stop_loss_hit)
                self.assertFalse(outcomes[315].take_profit_hit)
                self.assertFalse(outcomes[635].entry_touched)
            finally:
                session.close()
        finally:
            engine.dispose()
