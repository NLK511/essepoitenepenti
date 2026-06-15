from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_postgres_validation.py"
spec = importlib.util.spec_from_file_location("check_postgres_validation", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
postgres_validation = importlib.util.module_from_spec(spec)
sys.modules["check_postgres_validation"] = postgres_validation
spec.loader.exec_module(postgres_validation)


def test_postgres_integration_target_defaults_to_clean_migration_smoke() -> None:
    target = postgres_validation.postgres_integration_target({})

    assert target.endswith("test_migrations_upgrade_clean_postgres_database")


def test_postgres_integration_target_can_include_data_dependent_tests() -> None:
    target = postgres_validation.postgres_integration_target(
        {"POSTGRES_VALIDATION_INCLUDE_DATA_TESTS": "1"}
    )

    assert target == "tests/test_postgres_integration.py"


def test_verify_broker_account_schema_passes_with_required_tables_columns_and_default_account(
    tmp_path,
) -> None:
    db_path = tmp_path / "postgres-validation-shim.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE broker_accounts (broker_account_id TEXT PRIMARY KEY, broker TEXT, account_mode TEXT, credential_reference TEXT)"
                )
            )
            connection.execute(
                text("CREATE TABLE broker_account_credentials (broker_account_id TEXT PRIMARY KEY)")
            )
            connection.execute(
                text("CREATE TABLE broker_circuit_breakers (broker_account_id TEXT PRIMARY KEY)")
            )
            connection.execute(
                text("CREATE TABLE broker_drawdown_states (broker_account_id TEXT PRIMARY KEY)")
            )
            for table in postgres_validation.REQUIRED_ACCOUNT_SCOPED_COLUMNS:
                if table == "broker_positions":
                    protective_columns = ", ".join(
                        f"{column} TEXT"
                        for column in postgres_validation.REQUIRED_BROKER_POSITION_COLUMNS
                    )
                    connection.execute(
                        text(
                            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, broker_account_id TEXT, {protective_columns})"
                        )
                    )
                else:
                    connection.execute(
                        text(
                            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, broker_account_id TEXT)"
                        )
                    )
            connection.execute(
                text(
                    "INSERT INTO broker_accounts (broker_account_id, broker, account_mode, credential_reference) VALUES (:id, 'alpaca', 'paper', :ref)"
                ),
                {"id": "alpaca-paper-default", "ref": "broker_account:alpaca-paper-default"},
            )
    finally:
        engine.dispose()

    report = postgres_validation.verify_broker_account_schema(f"sqlite:///{db_path}")

    assert report["status"] == "passed"
    assert report["errors"] == []


def test_verify_broker_account_schema_fails_closed_when_account_scoped_column_missing(
    tmp_path,
) -> None:
    db_path = tmp_path / "postgres-validation-missing.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE broker_accounts (broker_account_id TEXT PRIMARY KEY, broker TEXT, account_mode TEXT, credential_reference TEXT)"
                )
            )
            connection.execute(
                text("CREATE TABLE broker_account_credentials (broker_account_id TEXT PRIMARY KEY)")
            )
            connection.execute(
                text("CREATE TABLE broker_circuit_breakers (broker_account_id TEXT PRIMARY KEY)")
            )
            connection.execute(
                text("CREATE TABLE broker_drawdown_states (broker_account_id TEXT PRIMARY KEY)")
            )
            connection.execute(
                text("CREATE TABLE broker_order_executions (id INTEGER PRIMARY KEY)")
            )
            connection.execute(
                text(
                    "CREATE TABLE broker_positions (id INTEGER PRIMARY KEY, broker_account_id TEXT)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE broker_reconciliation_snapshots (id INTEGER PRIMARY KEY, broker_account_id TEXT)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE broker_steering_decisions (id INTEGER PRIMARY KEY, broker_account_id TEXT)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE risk_halt_events (id INTEGER PRIMARY KEY, broker_account_id TEXT)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO broker_accounts (broker_account_id, broker, account_mode, credential_reference) VALUES (:id, 'alpaca', 'paper', :ref)"
                ),
                {"id": "alpaca-paper-default", "ref": "broker_account:alpaca-paper-default"},
            )
    finally:
        engine.dispose()

    report = postgres_validation.verify_broker_account_schema(f"sqlite:///{db_path}")

    assert report["status"] == "failed"
    assert "missing column: broker_order_executions.broker_account_id" in report["errors"]
