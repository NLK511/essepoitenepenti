import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trade_proposer_app.migrations import (
    HEAD_REVISION,
    LEGACY_REVISION_MAP,
    normalize_alembic_revision_ids,
    try_repair_partial_sqlite_schema,
)


class MigrationRepairTests(unittest.TestCase):
    def test_alembic_revision_ids_fit_default_version_column(self) -> None:
        versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
        too_long: list[tuple[str, int]] = []
        for path in versions_dir.glob("*.py"):
            match = re.search(r'^revision = "([^"]+)"', path.read_text(), re.MULTILINE)
            if match and len(match.group(1)) > 32:
                too_long.append((match.group(1), len(match.group(1))))

        self.assertEqual(too_long, [])
        self.assertLessEqual(len(HEAD_REVISION), 32)

    def test_broker_account_seed_migration_uses_boolean_literals(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0044_broker_accounts.py"
        ).read_text()

        self.assertIn("false, false, true", migration)
        self.assertNotIn(":id, 'alpaca', 'paper', :id, 0, 0, 1", migration)

    def test_historical_news_link_migration_uses_sqlite_safe_batch_alter(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "alembic"
            / "versions"
            / "0035_news_link_to_text.py"
        ).read_text()

        self.assertIn("batch_alter_table('historical_news_items')", migration)
        self.assertNotIn("op.alter_column(\n        'historical_news_items'", migration)

    def test_historical_news_available_at_migration_uses_sqlite_safe_batch_alter(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "alembic"
            / "versions"
            / "0048_historical_news_available_at.py"
        ).read_text()

        self.assertIn('batch_alter_table("historical_news_items")', migration)
        self.assertIn("available_at", migration)
        self.assertIn("availability_metadata_json", migration)
        self.assertNotIn("op.alter_column(\n        'historical_news_items'", migration)

    def test_normalize_alembic_revision_ids_updates_legacy_revision_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "normalize.db")
            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                cursor.execute(
                    "INSERT INTO alembic_version (version_num) VALUES ('0015_drop_legacy_recommendations_table')"
                )
                connection.commit()
            finally:
                connection.close()

            with patch(
                "trade_proposer_app.migrations.settings.database_url", f"sqlite:///{db_path}"
            ):
                normalized = normalize_alembic_revision_ids()

            self.assertTrue(normalized)

            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT version_num FROM alembic_version")
                self.assertEqual(
                    cursor.fetchone()[0],
                    LEGACY_REVISION_MAP["0015_drop_legacy_recommendations_table"],
                )
            finally:
                connection.close()

    def test_try_repair_partial_sqlite_schema_repairs_0003_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "repair.db")
            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                cursor.execute(
                    "INSERT INTO alembic_version (version_num) VALUES ('0003_recommendation_diagnostics_fields')"
                )
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

            with patch(
                "trade_proposer_app.migrations.settings.database_url", f"sqlite:///{db_path}"
            ):
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
