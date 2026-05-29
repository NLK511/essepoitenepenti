#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys


def run(command: list[str], *, env: dict[str, str]) -> int:
    print("+", " ".join(command), flush=True)
    return subprocess.call(command, env=env)


def main() -> int:
    database_url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        print("POSTGRES_TEST_DATABASE_URL is not set; skipping Postgres validation.")
        return 0
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    commands = [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "pytest", "-q", "tests/test_postgres_integration.py"],
    ]
    for command in commands:
        code = run(command, env=env)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
