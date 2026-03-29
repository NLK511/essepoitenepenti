#!/usr/bin/env python3
"""Reset encrypted provider credentials stored in PostgreSQL.

Usage:
  DATABASE_URL=postgresql+psycopg://... python scripts/reset_provider_credentials.py

Optional:
  --provider openai        Delete only one provider row instead of all rows.
  --provider openai --provider anthropic
  --yes                    Skip the confirmation prompt.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, delete
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from trade_proposer_app.persistence.models import ProviderCredentialRecord


def _database_backend(database_url: str) -> str:
    lower = database_url.lower()
    if lower.startswith("postgresql") or lower.startswith("postgres:"):
        return "postgresql"
    if lower.startswith("sqlite"):
        return "sqlite"
    return "other"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset provider credentials stored in the database.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="Database URL to use. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=[],
        help="Delete only the specified provider credential row. May be repeated.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = args.database_url.strip()
    if not database_url:
        print("ERROR: DATABASE_URL is not set and --database-url was not provided.", file=sys.stderr)
        return 2

    backend = _database_backend(database_url)
    if backend != "postgresql":
        print(f"ERROR: this reset script is intended for PostgreSQL, got {database_url!r}", file=sys.stderr)
        return 2

    targets = [provider.strip() for provider in args.provider if provider.strip()]
    if targets:
        target_desc = ", ".join(targets)
        message = f"This will delete provider credential row(s) for: {target_desc}"
    else:
        message = "This will delete ALL provider credential rows"

    print(message)
    print(f"Database: {database_url}")
    if not args.yes:
        response = input("Proceed? [y/N] ").strip().lower()
        if response not in {"y", "yes"}:
            print("Aborted.")
            return 1

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            if targets:
                result = connection.execute(
                    delete(ProviderCredentialRecord).where(ProviderCredentialRecord.provider.in_(targets))
                )
            else:
                result = connection.execute(delete(ProviderCredentialRecord))

            print(f"Deleted {result.rowcount or 0} credential row(s).")
    except SQLAlchemyError as exc:
        print(f"ERROR: failed to reset provider credentials: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
