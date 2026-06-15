from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_broker_migration_backfill.py"
spec = importlib.util.spec_from_file_location("check_broker_migration_backfill", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
sys.modules["check_broker_migration_backfill"] = checker
spec.loader.exec_module(checker)


def test_verify_sqlite_database_accepts_required_broker_backfill_schema(tmp_path) -> None:
    db_path = tmp_path / "schema.db"
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "CREATE TABLE broker_accounts (broker_account_id TEXT PRIMARY KEY, broker TEXT, account_mode TEXT, credential_reference TEXT)"
        )
        cursor.execute(
            "CREATE TABLE broker_account_credentials (broker_account_id TEXT PRIMARY KEY)"
        )
        cursor.execute("CREATE TABLE broker_circuit_breakers (broker_account_id TEXT PRIMARY KEY)")
        cursor.execute("CREATE TABLE broker_drawdown_states (broker_account_id TEXT PRIMARY KEY)")
        for table in checker.REQUIRED_ACCOUNT_SCOPED_COLUMNS:
            if table == "broker_positions":
                protective_columns = ", ".join(
                    f"{column} TEXT" for column in checker.REQUIRED_BROKER_POSITION_COLUMNS
                )
                cursor.execute(
                    f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, broker_account_id TEXT, {protective_columns})"
                )
            else:
                cursor.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, broker_account_id TEXT)")
        cursor.execute(
            "INSERT INTO broker_accounts (broker_account_id, broker, account_mode, credential_reference) VALUES (?, ?, ?, ?)",
            ("alpaca-paper-default", "alpaca", "paper", "broker_account:alpaca-paper-default"),
        )
        connection.commit()
    finally:
        connection.close()

    report = checker.verify_sqlite_database(db_path, database_url=f"sqlite:///{db_path}")

    assert report.status == "passed"
    assert report.errors == []
    assert report.default_account_id == "alpaca-paper-default"


def test_verify_sqlite_database_fails_closed_on_missing_default_account(tmp_path) -> None:
    db_path = tmp_path / "missing.db"
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "CREATE TABLE broker_accounts (broker_account_id TEXT PRIMARY KEY, broker TEXT, account_mode TEXT, credential_reference TEXT)"
        )
        cursor.execute(
            "CREATE TABLE broker_account_credentials (broker_account_id TEXT PRIMARY KEY)"
        )
        cursor.execute("CREATE TABLE broker_circuit_breakers (broker_account_id TEXT PRIMARY KEY)")
        cursor.execute("CREATE TABLE broker_drawdown_states (broker_account_id TEXT PRIMARY KEY)")
        for table in checker.REQUIRED_ACCOUNT_SCOPED_COLUMNS:
            cursor.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, broker_account_id TEXT)")
        connection.commit()
    finally:
        connection.close()

    report = checker.verify_sqlite_database(db_path, database_url=f"sqlite:///{db_path}")

    assert report.status == "failed"
    assert "missing default broker account: alpaca-paper-default" in report.errors


def test_release_readiness_includes_broker_migration_backfill_validation() -> None:
    release_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_etoro_release_readiness.py"
    )
    release_spec = importlib.util.spec_from_file_location(
        "check_etoro_release_readiness", release_path
    )
    assert release_spec is not None and release_spec.loader is not None
    readiness = importlib.util.module_from_spec(release_spec)
    sys.modules["check_etoro_release_readiness"] = readiness
    release_spec.loader.exec_module(readiness)

    commands = readiness.build_commands(skip_frontend=True, skip_postgres=True)

    assert "broker_migration_backfill" in [command.name for command in commands]
