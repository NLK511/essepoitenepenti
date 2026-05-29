from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.services.provider_observability import ProviderObservabilityService


def test_provider_observability_emits_normalized_failure_event() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    try:
        event = ProviderObservabilityService(ObservabilityEventRepository(session)).record(
            "failed",
            provider="alpaca",
            source_type="news",
            ticker="aapl",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
            mode="live",
            attempt=2,
            duration_ms=125.5,
            reason="timeout",
            correlation_id="corr-1",
        )

        assert event["event_type"] == "provider.request_failed"
        assert event["severity"] == "warning"
        assert event["source"] == "provider"
        assert event["correlation_id"] == "corr-1"
        assert event["payload"]["provider"] == "alpaca"
        assert event["payload"]["source_type"] == "news"
        assert event["payload"]["ticker"] == "AAPL"
        assert event["payload"]["reason"] == "timeout"
    finally:
        session.close()
        engine.dispose()
