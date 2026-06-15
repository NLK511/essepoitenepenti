#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"

REQUIRED_ARTIFACT_ENV_VARS = (
    "ETORO_READONLY_VALIDATION_ARTIFACT_ID",
    "ETORO_DEMO_VALIDATION_ARTIFACT_ID",
    "ETORO_LIVE_SHADOW_EVIDENCE_ID",
)

FOCUSED_BROKER_RISK_TESTS = (
    "tests/test_broker_accounts.py",
    "tests/test_broker_accounts_api.py",
    "tests/test_broker_adapter_contract.py",
    "tests/test_broker_adapter_factory.py",
    "tests/test_multi_broker_fanout.py",
    "tests/test_multi_broker_risk.py",
    "tests/test_broker_drawdown_state.py",
    "tests/test_broker_circuit_breaker.py",
    "tests/test_broker_account_safety.py",
    "tests/test_broker_reconciliation_multi_account.py",
    "tests/test_etoro_client_readonly.py",
    "tests/test_etoro_demo_execution.py",
    "tests/test_etoro_instrument_metadata.py",
    "tests/test_etoro_live_gates.py",
    "tests/test_etoro_live_manual_actions_api.py",
    "tests/test_etoro_permissions.py",
    "tests/test_etoro_secret_redaction.py",
)


@dataclass(frozen=True)
class ValidationCommand:
    name: str
    command: tuple[str, ...]
    cwd: Path = ROOT

    def display(self) -> str:
        prefix = "" if self.cwd == ROOT else f"(cd {self.cwd.relative_to(ROOT)} && "
        suffix = "" if self.cwd == ROOT else ")"
        return f"{prefix}{' '.join(self.command)}{suffix}"


@dataclass(frozen=True)
class ValidationResult:
    name: str
    command: str
    status: str
    exit_code: int | None = None


def build_commands(*, skip_frontend: bool, skip_postgres: bool) -> list[ValidationCommand]:
    commands = [
        ValidationCommand("full_pytest", (sys.executable, "-m", "pytest", "-q")),
        ValidationCommand(
            "broker_risk_focused_pytest",
            (sys.executable, "-m", "pytest", "-q", *FOCUSED_BROKER_RISK_TESTS),
        ),
        ValidationCommand(
            "migration_pytest",
            (sys.executable, "-m", "pytest", "-q", "tests/test_migrations.py"),
        ),
        ValidationCommand(
            "broker_migration_backfill",
            (sys.executable, "scripts/check_broker_migration_backfill.py"),
        ),
    ]
    if not skip_postgres:
        commands.append(
            ValidationCommand(
                "postgres_validation",
                (sys.executable, "scripts/check_postgres_validation.py"),
            )
        )
    if not skip_frontend and (FRONTEND_DIR / "package.json").exists():
        commands.append(ValidationCommand("frontend_check", ("npm", "run", "check"), FRONTEND_DIR))
    return commands


def missing_artifacts(env: dict[str, str]) -> list[str]:
    return [name for name in REQUIRED_ARTIFACT_ENV_VARS if not env.get(name, "").strip()]


def run_command(command: ValidationCommand, *, env: dict[str, str]) -> int:
    print(f"+ {command.display()}", flush=True)
    return subprocess.call(command.command, cwd=command.cwd, env=env)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the eToro/multi-broker release readiness checklist."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print checks without executing commands."
    )
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend type check.")
    parser.add_argument(
        "--skip-postgres", action="store_true", help="Skip Postgres validation command."
    )
    parser.add_argument(
        "--allow-missing-external-artifacts",
        action="store_true",
        help="Do not fail when eToro read-only/demo/live-shadow artifact ids are absent.",
    )
    parser.add_argument(
        "--report-output",
        help="Write a JSON release-readiness report to this path.",
    )
    return parser.parse_args(argv)


def build_release_report(
    *,
    env: dict[str, str],
    missing: list[str],
    results: list[ValidationResult],
    status: str,
) -> dict[str, object]:
    return {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "required_artifacts": {name: env.get(name, "") for name in REQUIRED_ARTIFACT_ENV_VARS},
        "missing_artifacts": missing,
        "validations": [result.__dict__ for result in results],
        "live_micro_size_defaults": {
            "max_notional_usd": 25,
            "max_daily_order_count": 1,
            "leverage": 1,
            "allowlist_required": True,
        },
    }


def write_report(path: str | None, report: dict[str, object]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote release-readiness report to {output}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    env = os.environ.copy()
    missing = missing_artifacts(env)
    commands = build_commands(skip_frontend=args.skip_frontend, skip_postgres=args.skip_postgres)
    results: list[ValidationResult] = []
    if missing:
        print("Missing required external validation artifacts:")
        for name in missing:
            print(f"- {name}")
        if not args.allow_missing_external_artifacts:
            print("Use --allow-missing-external-artifacts only for non-release local dry runs.")
            write_report(
                args.report_output,
                build_release_report(env=env, missing=missing, results=results, status="failed"),
            )
            return 2
    else:
        print("External eToro validation artifact ids are present.")

    if args.dry_run:
        print("Dry run; commands that would execute:")
        for command in commands:
            print(f"+ {command.display()}")
            results.append(
                ValidationResult(name=command.name, command=command.display(), status="dry_run")
            )
        write_report(
            args.report_output,
            build_release_report(env=env, missing=missing, results=results, status="dry_run"),
        )
        return 0

    for command in commands:
        code = run_command(command, env=env)
        results.append(
            ValidationResult(
                name=command.name,
                command=command.display(),
                status="passed" if code == 0 else "failed",
                exit_code=code,
            )
        )
        if code != 0:
            print(f"Validation step failed: {command.name} exited with {code}")
            write_report(
                args.report_output,
                build_release_report(env=env, missing=missing, results=results, status="failed"),
            )
            return code
    report = build_release_report(env=env, missing=missing, results=results, status="passed")
    write_report(args.report_output, report)
    print("eToro release readiness validation completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
