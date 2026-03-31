import os
import subprocess
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


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
