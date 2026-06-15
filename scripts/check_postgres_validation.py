#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

REQUIRED_BROKER_TABLES = (
    "broker_accounts",
    "broker_account_credentials",
    "broker_circuit_breakers",
    "broker_drawdown_states",
)
REQUIRED_ACCOUNT_SCOPED_COLUMNS = {
    "broker_order_executions": "broker_account_id",
    "broker_positions": "broker_account_id",
    "broker_reconciliation_snapshots": "broker_account_id",
    "broker_steering_decisions": "broker_account_id",
    "risk_halt_events": "broker_account_id",
}
REQUIRED_BROKER_POSITION_COLUMNS = (
    "stop_loss_order_id",
    "stop_loss_order_status",
    "stop_loss_order_price",
    "take_profit_order_id",
    "take_profit_order_status",
    "take_profit_order_price",
    "protective_orders_verified_at",
    "protective_orders_source",
)
DEFAULT_ACCOUNT_ID = "alpaca-paper-default"


def run(command: list[str], *, env: dict[str, str]) -> int:
    print("+", " ".join(command), flush=True)
    return subprocess.call(command, env=env)


def verify_broker_account_schema(database_url: str) -> dict[str, object]:
    errors: list[str] = []
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        for table in REQUIRED_BROKER_TABLES:
            if table not in tables:
                errors.append(f"missing table: {table}")
        for table, column in REQUIRED_ACCOUNT_SCOPED_COLUMNS.items():
            if table not in tables:
                errors.append(f"missing table: {table}")
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            if column not in columns:
                errors.append(f"missing column: {table}.{column}")
        if "broker_positions" in tables:
            position_columns = {item["name"] for item in inspector.get_columns("broker_positions")}
            for column in REQUIRED_BROKER_POSITION_COLUMNS:
                if column not in position_columns:
                    errors.append(f"missing column: broker_positions.{column}")
        if "broker_accounts" in tables:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT broker, account_mode, credential_reference "
                        "FROM broker_accounts WHERE broker_account_id = :id"
                    ),
                    {"id": DEFAULT_ACCOUNT_ID},
                ).first()
            expected = ("alpaca", "paper", f"broker_account:{DEFAULT_ACCOUNT_ID}")
            if row is None:
                errors.append(f"missing default broker account: {DEFAULT_ACCOUNT_ID}")
            elif tuple(row) != expected:
                errors.append(f"unexpected default broker account row: {tuple(row)!r}")
    finally:
        engine.dispose()
    return {
        "status": "passed" if not errors else "failed",
        "checked_tables": list(REQUIRED_BROKER_TABLES),
        "checked_columns": dict(REQUIRED_ACCOUNT_SCOPED_COLUMNS),
        "default_account_id": DEFAULT_ACCOUNT_ID,
        "errors": errors,
    }


def postgres_integration_target(env: dict[str, str]) -> str:
    if env.get("POSTGRES_VALIDATION_INCLUDE_DATA_TESTS") == "1":
        return "tests/test_postgres_integration.py"
    return (
        "tests/test_postgres_integration.py::PostgresMigrationIntegrationTest::"
        "test_migrations_upgrade_clean_postgres_database"
    )


def main() -> int:
    database_url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        print("POSTGRES_TEST_DATABASE_URL is not set; skipping Postgres validation.")
        return 0
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    integration_target = postgres_integration_target(env)
    commands = [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "pytest", "-q", integration_target],
    ]
    for command in commands:
        code = run(command, env=env)
        if code != 0:
            return code
    report = verify_broker_account_schema(database_url)
    print(report)
    if report["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
