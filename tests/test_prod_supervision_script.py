from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_PROD = ROOT / "scripts" / "start-prod.sh"
SPEC = ROOT / "docs" / "specs" / "production-supervision-spec.md"


def _script() -> str:
    return START_PROD.read_text()


def test_production_supervision_spec_documents_non_fatal_worker_and_scheduler_restarts() -> None:
    text = SPEC.read_text()

    assert "Worker exit is non-fatal to the API" in text
    assert "Scheduler exit is non-fatal to the API" in text
    assert "API exit remains fatal" in text
    assert "PROD_SUPERVISOR_MAX_RESTARTS" in text


def test_start_prod_restarts_worker_instead_of_exiting_immediately() -> None:
    text = _script()

    worker_branch = text.split(
        'if ! kill -0 "$WORKER_PID" 2>/dev/null; then', 1
    )[1].split("fi", 1)[0]

    assert "restart_worker" in worker_branch
    assert "exit 1" not in worker_branch
    assert "worker process exited unexpectedly" in worker_branch


def test_start_prod_restarts_scheduler_instead_of_exiting_immediately() -> None:
    text = _script()

    scheduler_branch = text.split(
        'if ! kill -0 "$SCHEDULER_PID" 2>/dev/null; then', 1
    )[1].split("fi", 1)[0]

    assert "restart_scheduler" in scheduler_branch
    assert "exit 1" not in scheduler_branch
    assert "scheduler process exited unexpectedly" in scheduler_branch


def test_start_prod_keeps_api_exit_fatal() -> None:
    text = _script()

    api_branch = text.split('if ! kill -0 "$API_PID" 2>/dev/null; then', 1)[1].split("fi", 1)[0]

    assert "api process exited unexpectedly" in api_branch
    assert "exit 1" in api_branch


def test_start_prod_has_bounded_restart_policy_and_updates_meta() -> None:
    text = _script()

    assert "PROD_SUPERVISOR_MAX_RESTARTS" in text
    assert "PROD_SUPERVISOR_RESTART_WINDOW_SECONDS" in text
    assert "PROD_SUPERVISOR_RESTART_DELAY_SECONDS" in text
    assert "restart budget exceeded" in text
    assert "write_meta_file" in text
    assert 'echo "$WORKER_PID" > "$WORKER_PID_FILE"' in text
    assert 'echo "$SCHEDULER_PID" > "$SCHEDULER_PID_FILE"' in text
