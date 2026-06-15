from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_etoro_release_readiness.py"
spec = importlib.util.spec_from_file_location("check_etoro_release_readiness", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
readiness = importlib.util.module_from_spec(spec)
sys.modules["check_etoro_release_readiness"] = readiness
spec.loader.exec_module(readiness)


def test_build_commands_include_required_release_validation_steps() -> None:
    commands = readiness.build_commands(skip_frontend=False, skip_postgres=False)
    names = [command.name for command in commands]
    focused = next(command for command in commands if command.name == "broker_risk_focused_pytest")

    assert "full_pytest" in names
    assert "broker_risk_focused_pytest" in names
    assert "migration_pytest" in names
    assert "postgres_validation" in names
    assert "tests/test_etoro_live_gates.py" in focused.command
    assert "tests/test_etoro_live_manual_actions_api.py" in focused.command
    assert "tests/test_broker_accounts_api.py" in focused.command


def test_missing_external_artifacts_fail_closed() -> None:
    assert readiness.missing_artifacts({}) == list(readiness.REQUIRED_ARTIFACT_ENV_VARS)
    assert readiness.main(["--dry-run", "--skip-frontend", "--skip-postgres"]) == 2


def test_dry_run_can_be_used_for_local_non_release_checks(monkeypatch) -> None:
    monkeypatch.delenv("ETORO_READONLY_VALIDATION_ARTIFACT_ID", raising=False)
    monkeypatch.delenv("ETORO_DEMO_VALIDATION_ARTIFACT_ID", raising=False)
    monkeypatch.delenv("ETORO_LIVE_SHADOW_EVIDENCE_ID", raising=False)

    assert (
        readiness.main(
            [
                "--dry-run",
                "--skip-frontend",
                "--skip-postgres",
                "--allow-missing-external-artifacts",
            ]
        )
        == 0
    )


def test_release_artifact_environment_satisfies_gate() -> None:
    env = {
        "ETORO_READONLY_VALIDATION_ARTIFACT_ID": "readonly-1",
        "ETORO_DEMO_VALIDATION_ARTIFACT_ID": "demo-1",
        "ETORO_LIVE_SHADOW_EVIDENCE_ID": "shadow-1",
    }

    assert readiness.missing_artifacts(env) == []


def test_release_report_contains_artifacts_validation_results_and_micro_size_defaults() -> None:
    env = {
        "ETORO_READONLY_VALIDATION_ARTIFACT_ID": "readonly-1",
        "ETORO_DEMO_VALIDATION_ARTIFACT_ID": "demo-1",
        "ETORO_LIVE_SHADOW_EVIDENCE_ID": "shadow-1",
    }

    report = readiness.build_release_report(
        env=env,
        missing=[],
        results=[
            readiness.ValidationResult(
                name="broker_risk_focused_pytest",
                command="python -m pytest -q tests/test_etoro_live_gates.py",
                status="passed",
                exit_code=0,
            )
        ],
        status="passed",
    )

    assert report["status"] == "passed"
    assert report["required_artifacts"]["ETORO_DEMO_VALIDATION_ARTIFACT_ID"] == "demo-1"
    assert report["validations"][0]["status"] == "passed"
    assert report["live_micro_size_defaults"] == {
        "max_notional_usd": 25,
        "max_daily_order_count": 1,
        "leverage": 1,
        "allowlist_required": True,
    }


def test_dry_run_writes_release_report(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ETORO_READONLY_VALIDATION_ARTIFACT_ID", raising=False)
    monkeypatch.delenv("ETORO_DEMO_VALIDATION_ARTIFACT_ID", raising=False)
    monkeypatch.delenv("ETORO_LIVE_SHADOW_EVIDENCE_ID", raising=False)
    output = tmp_path / "release-readiness.json"

    code = readiness.main(
        [
            "--dry-run",
            "--skip-frontend",
            "--skip-postgres",
            "--allow-missing-external-artifacts",
            "--report-output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run"
    assert payload["missing_artifacts"] == list(readiness.REQUIRED_ARTIFACT_ENV_VARS)
    assert payload["validations"][0]["status"] == "dry_run"
