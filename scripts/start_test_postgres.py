#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

DEFAULT_CONTAINER = "aurelio-postgres-test"
DEFAULT_IMAGE = "postgres:16-alpine"
DEFAULT_PORT = 55432
DEFAULT_DB = "aurelio_test"
DEFAULT_USER = "aurelio"
DEFAULT_PASSWORD = "aurelio_test_password"


@dataclass(frozen=True)
class PostgresConfig:
    container: str
    image: str
    port: int
    database: str
    user: str
    password: str

    @property
    def url(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@127.0.0.1:{self.port}/{self.database}"


def run(
    command: list[str], *, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker executable was not found"
    try:
        run(["docker", "ps", "--format", "{{.Names}}"], capture=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        return False, stderr or stdout or "docker is not usable by this user"
    return True, ""


def container_exists(name: str) -> bool:
    result = run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"], capture=True
    )
    return name in {line.strip() for line in result.stdout.splitlines()}


def container_running(name: str) -> bool:
    result = run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"], capture=True
    )
    return name in {line.strip() for line in result.stdout.splitlines()}


def start_container(config: PostgresConfig) -> None:
    if container_running(config.container):
        return
    if container_exists(config.container):
        run(["docker", "start", config.container])
        return
    run(
        [
            "docker",
            "run",
            "--name",
            config.container,
            "-e",
            f"POSTGRES_USER={config.user}",
            "-e",
            f"POSTGRES_PASSWORD={config.password}",
            "-e",
            f"POSTGRES_DB={config.database}",
            "-p",
            f"127.0.0.1:{config.port}:5432",
            "-d",
            config.image,
        ]
    )


def wait_until_ready(config: PostgresConfig, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        probe = run(
            [
                "docker",
                "exec",
                config.container,
                "pg_isready",
                "-U",
                config.user,
                "-d",
                config.database,
            ],
            check=False,
            capture=True,
        )
        if probe.returncode == 0:
            return
        last_error = (probe.stderr or probe.stdout or "").strip()
        time.sleep(0.5)
    raise RuntimeError(
        f"Postgres container did not become ready within {timeout_seconds}s: {last_error}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start Aurelio's local Postgres validation container."
    )
    parser.add_argument(
        "--container", default=os.environ.get("AURELIO_TEST_POSTGRES_CONTAINER", DEFAULT_CONTAINER)
    )
    parser.add_argument(
        "--image", default=os.environ.get("AURELIO_TEST_POSTGRES_IMAGE", DEFAULT_IMAGE)
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("AURELIO_TEST_POSTGRES_PORT", DEFAULT_PORT))
    )
    parser.add_argument(
        "--database", default=os.environ.get("AURELIO_TEST_POSTGRES_DB", DEFAULT_DB)
    )
    parser.add_argument(
        "--user", default=os.environ.get("AURELIO_TEST_POSTGRES_USER", DEFAULT_USER)
    )
    parser.add_argument(
        "--password", default=os.environ.get("AURELIO_TEST_POSTGRES_PASSWORD", DEFAULT_PASSWORD)
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--print-export", action="store_true", help="Only print the export command after startup."
    )
    args = parser.parse_args()
    config = PostgresConfig(
        container=args.container,
        image=args.image,
        port=args.port,
        database=args.database,
        user=args.user,
        password=args.password,
    )
    available, reason = docker_available()
    if not available:
        print(f"Docker is required but unavailable: {reason}", file=sys.stderr)
        print(
            "Grant this user access to /var/run/docker.sock, run this script with an "
            "authorized Docker user, or provide POSTGRES_TEST_DATABASE_URL for an existing "
            "Postgres database.",
            file=sys.stderr,
        )
        return 2
    start_container(config)
    wait_until_ready(config, args.timeout)
    export = f"export POSTGRES_TEST_DATABASE_URL='{config.url}'"
    if args.print_export:
        print(export)
    else:
        print("Postgres test container is ready.")
        print(export)
        print("Run: .venv/bin/python scripts/check_postgres_validation.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
