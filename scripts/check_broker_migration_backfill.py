#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_TABLES = (
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


@dataclass(frozen=True)
class BrokerMigrationBackfillReport:
    status: str
    database_url: str
    checked_tables: list[str]
    checked_columns: dict[str, str]
    default_account_id: str
    errors: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "database_url": self.database_url,
            "checked_tables": self.checked_tables,
            "checked_columns": self.checked_columns,
            "default_account_id": self.default_account_id,
            "errors": self.errors,
        }


def run_alembic_upgrade(database_url: str) -> int:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    print(f"+ DATABASE_URL={database_url} {sys.executable} -m alembic upgrade head", flush=True)
    return subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env)


def verify_sqlite_database(db_path: Path, *, database_url: str) -> BrokerMigrationBackfillReport:
    errors: list[str] = []
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        tables = _table_names(cursor)
        for table in REQUIRED_TABLES:
            if table not in tables:
                errors.append(f"missing table: {table}")
        for table, column in REQUIRED_ACCOUNT_SCOPED_COLUMNS.items():
            columns = _column_names(cursor, table)
            if column not in columns:
                errors.append(f"missing column: {table}.{column}")
        position_columns = _column_names(cursor, "broker_positions")
        for column in REQUIRED_BROKER_POSITION_COLUMNS:
            if column not in position_columns:
                errors.append(f"missing column: broker_positions.{column}")
        if "broker_accounts" in tables:
            cursor.execute(
                "SELECT broker, account_mode, credential_reference FROM broker_accounts WHERE broker_account_id = ?",
                (DEFAULT_ACCOUNT_ID,),
            )
            row = cursor.fetchone()
            if row is None:
                errors.append(f"missing default broker account: {DEFAULT_ACCOUNT_ID}")
            elif row != ("alpaca", "paper", f"broker_account:{DEFAULT_ACCOUNT_ID}"):
                errors.append(f"unexpected default broker account row: {row!r}")
    finally:
        connection.close()
    return BrokerMigrationBackfillReport(
        status="passed" if not errors else "failed",
        database_url=database_url,
        checked_tables=list(REQUIRED_TABLES),
        checked_columns=dict(REQUIRED_ACCOUNT_SCOPED_COLUMNS),
        default_account_id=DEFAULT_ACCOUNT_ID,
        errors=errors,
    )


def _table_names(cursor: sqlite3.Cursor) -> set[str]:
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row[0]) for row in cursor.fetchall()}


def _column_names(cursor: sqlite3.Cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cursor.fetchall()}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test broker-account migration/backfill on a fresh SQLite database."
    )
    parser.add_argument("--database-path", help="Optional SQLite database path to create/upgrade.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.database_path:
        db_path = Path(args.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{db_path}"
        code = run_alembic_upgrade(database_url)
        if code != 0:
            return code
        report = verify_sqlite_database(db_path, database_url=database_url)
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "broker-migration-smoke.db"
            database_url = f"sqlite:///{db_path}"
            code = run_alembic_upgrade(database_url)
            if code != 0:
                return code
            report = verify_sqlite_database(db_path, database_url=database_url)
    for error in report.errors:
        print(f"ERROR: {error}")
    print(report.to_dict())
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
