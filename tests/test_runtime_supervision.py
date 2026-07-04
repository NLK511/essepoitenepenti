from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.runtime_processes import RuntimeProcessRepository
from trade_proposer_app.services.runtime_supervision import RuntimeSupervisionService


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_runtime_supervision_records_process_start_and_heartbeat() -> None:
    session = _session()
    try:
        service = RuntimeSupervisionService(session)
        process = service.register_process_start(
            role="api",
            instance_id="api-test",
            metadata={"api_key": "secret", "safe": "value"},
        )
        assert process.instance_id == "api-test"

        updated = service.heartbeat(instance_id="api-test", status="healthy")
        assert updated is not None
        assert updated.status == "healthy"

        processes = RuntimeProcessRepository(session).list_active_processes(stale_after_seconds=90)
        assert [item.instance_id for item in processes] == ["api-test"]
        assert processes[0].metadata["api_key"] == "[redacted]"
        assert processes[0].metadata["safe"] == "value"
    finally:
        session.close()


def test_runtime_supervision_infers_unclean_restart_for_stale_previous_process() -> None:
    previous_stale = settings.runtime_process_stale_after_seconds
    settings.runtime_process_stale_after_seconds = 30
    session = _session()
    try:
        service = RuntimeSupervisionService(session)
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service.register_process_start(role="scheduler", instance_id="scheduler-old", now=old)
        service.register_process_start(role="scheduler", instance_id="scheduler-new")

        events = service.runtime_events(limit=20)
        inferred = [event for event in events if event["event_type"] == "unclean_restart_inferred"]
        assert len(inferred) == 1
        assert inferred[0]["payload"]["previous_instance_id"] == "scheduler-old"
    finally:
        settings.runtime_process_stale_after_seconds = previous_stale
        session.close()


def test_runtime_supervision_does_not_infer_unclean_restart_after_graceful_shutdown() -> None:
    previous_stale = settings.runtime_process_stale_after_seconds
    settings.runtime_process_stale_after_seconds = 30
    session = _session()
    try:
        service = RuntimeSupervisionService(session)
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service.register_process_start(role="worker", instance_id="worker-old", now=old)
        service.graceful_shutdown(instance_id="worker-old", now=old + timedelta(seconds=5))
        service.register_process_start(role="worker", instance_id="worker-new")

        assert not [
            event
            for event in service.runtime_events(limit=20)
            if event["event_type"] == "unclean_restart_inferred"
        ]
    finally:
        settings.runtime_process_stale_after_seconds = previous_stale
        session.close()
