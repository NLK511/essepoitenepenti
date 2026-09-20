from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_bar_provider_quality.py"
spec = importlib.util.spec_from_file_location("validate_bar_provider_quality", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
validation = importlib.util.module_from_spec(spec)
sys.modules["validate_bar_provider_quality"] = validation
spec.loader.exec_module(validation)


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeBrokerAccountRepository:
    credentials: dict[str, str] = {}
    requested_account_id: str | None = None

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def get_credentials(self, broker_account_id: str) -> dict[str, str]:
        self.__class__.requested_account_id = broker_account_id
        return self.__class__.credentials


def test_resolve_etoro_credentials_prefers_environment() -> None:
    credentials = validation.resolve_etoro_credentials(
        env={"ETORO_API_KEY": "env-api", "ETORO_USER_KEY": "env-user"},
        broker_account_id="etoro-demo-main",
        session_factory=lambda: FakeSession(),
        repository_cls=FakeBrokerAccountRepository,
    )

    assert credentials == {
        "api_key": "env-api",
        "user_key": "env-user",
        "source": "environment",
    }


def test_resolve_etoro_credentials_falls_back_to_broker_account_store() -> None:
    FakeBrokerAccountRepository.credentials = {
        "x_api_key": "stored-api",
        "x_user_key": "stored-user",
    }

    credentials = validation.resolve_etoro_credentials(
        env={},
        broker_account_id="etoro-demo-main",
        session_factory=lambda: FakeSession(),
        repository_cls=FakeBrokerAccountRepository,
    )

    assert credentials == {
        "api_key": "stored-api",
        "user_key": "stored-user",
        "source": "broker_account:etoro-demo-main",
    }
    assert FakeBrokerAccountRepository.requested_account_id == "etoro-demo-main"


def test_resolve_etoro_credentials_reports_missing_sources() -> None:
    FakeBrokerAccountRepository.credentials = {}

    try:
        validation.resolve_etoro_credentials(
            env={},
            broker_account_id="etoro-demo-main",
            session_factory=lambda: FakeSession(),
            repository_cls=FakeBrokerAccountRepository,
        )
    except RuntimeError as exc:
        assert "ETORO_API_KEY/ETORO_USER_KEY" in str(exc)
        assert "broker account etoro-demo-main" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_main_writes_failure_artifact_when_credential_bootstrap_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "etoro-vs-yahoo-1m.json"

    monkeypatch.setattr(
        validation,
        "parse_args",
        lambda: validation.argparse.Namespace(
            tickers="AAPL,MSFT",
            timeframe="1m",
            days=5,
            artifact=artifact_path,
            primary="yahoo",
            candidate="etoro",
            broker_account_id="etoro-demo-main",
            dry_run=False,
        ),
    )

    def fail_credentials(**_kwargs):
        raise RuntimeError("connection to localhost:5432 refused")

    monkeypatch.setattr(validation, "resolve_etoro_credentials", fail_credentials)

    exit_code = validation.main()

    assert exit_code == 1
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failure_stage"] == "credential_resolution"
    assert "localhost:5432 refused" in payload["error"]
    assert payload["comparison_started"] is False
    assert payload["read_only_scope"] == {
        "changed_broker_settings": False,
        "changed_orders": False,
        "changed_provider_priority": False,
        "changed_scheduler_state": False,
        "wrote_canonical_bars": False,
    }
