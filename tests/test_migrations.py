import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from trade_proposer_app.migrations import HEAD_REVISION, try_repair_partial_sqlite_schema


class MigrationRepairTests(unittest.TestCase):
    def test_try_repair_partial_sqlite_schema_repairs_0003_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "repair.db")
            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                cursor.execute("INSERT INTO alembic_version (version_num) VALUES ('0003_recommendation_diagnostics_fields')")
                cursor.execute(
                    "CREATE TABLE jobs ("
                    "id INTEGER PRIMARY KEY, "
                    "name VARCHAR(120) NOT NULL, "
                    "tickers_csv TEXT NOT NULL, "
                    "schedule VARCHAR(120), "
                    "enabled BOOLEAN NOT NULL, "
                    "created_at DATETIME NOT NULL, "
                    "updated_at DATETIME NOT NULL, "
                    "last_enqueued_at DATETIME, "
                    "watchlist_id INTEGER"
                    ")"
                )
                cursor.execute(
                    "CREATE TABLE runs ("
                    "id INTEGER PRIMARY KEY, "
                    "job_id INTEGER NOT NULL, "
                    "status VARCHAR(64) NOT NULL, "
                    "created_at DATETIME NOT NULL, "
                    "updated_at DATETIME NOT NULL"
                    ")"
                )
                connection.commit()
            finally:
                connection.close()

            with patch("trade_proposer_app.migrations.settings.database_url", f"sqlite:///{db_path}"):
                repaired = try_repair_partial_sqlite_schema()

            self.assertTrue(repaired)

            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute("PRAGMA table_info(runs)")
                run_columns = [row[1] for row in cursor.fetchall()]
                self.assertIn("error_message", run_columns)
                self.assertIn("scheduled_for", run_columns)
                self.assertIn("job_type", run_columns)
                self.assertIn("summary_json", run_columns)
                self.assertIn("artifact_json", run_columns)
                cursor.execute("PRAGMA table_info(jobs)")
                job_columns = [row[1] for row in cursor.fetchall()]
                self.assertIn("job_type", job_columns)
                cursor.execute("SELECT version_num FROM alembic_version")
                self.assertEqual(cursor.fetchone()[0], HEAD_REVISION)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
