import logging
import traceback
from datetime import datetime, timedelta, timezone
from time import sleep

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.builders import create_order_execution_service
from trade_proposer_app.services.order_execution import OrderExecutionService
from trade_proposer_app.services.runs import enqueue_enabled_jobs


logger = logging.getLogger(__name__)


POLL_SECONDS = 30
BROKER_ORDER_SYNC_INTERVAL_MINUTES = 120
BROKER_ORDER_SYNC_LAST_AT_KEY = "broker_order_sync_last_at"
BROKER_ORDER_SYNC_LAST_COUNT_KEY = "broker_order_sync_last_count"
BROKER_ORDER_SYNC_LAST_ERROR_KEY = "broker_order_sync_last_error"


def _write_scheduler_heartbeat(now: datetime | None = None, *, last_successful_enqueue_count: int | None = None, last_error: str | None = None) -> None:
    session = SessionLocal()
    try:
        repository = SettingsRepository(session)
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        repository.set_settings({
            "scheduler_last_poll_at": timestamp,
            "scheduler_last_success_at": timestamp if last_error is None else repository.get_setting_map().get("scheduler_last_success_at", ""),
            "scheduler_last_enqueue_count": "" if last_successful_enqueue_count is None else str(int(last_successful_enqueue_count)),
            "scheduler_last_error": last_error or "",
        })
    finally:
        session.close()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _sync_broker_orders_if_due(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    if not OrderExecutionService._is_market_open(current):
        return 0
    session = SessionLocal()
    try:
        repository = SettingsRepository(session)
        setting_map = repository.get_setting_map()
        last_sync = _parse_datetime(setting_map.get(BROKER_ORDER_SYNC_LAST_AT_KEY))
        if last_sync is not None and (current - last_sync).total_seconds() < BROKER_ORDER_SYNC_INTERVAL_MINUTES * 60:
            return 0
        service = create_order_execution_service(session)
        outcome = service.sync_open_executions()
        repository.set_settings(
            {
                BROKER_ORDER_SYNC_LAST_AT_KEY: current.isoformat(),
                BROKER_ORDER_SYNC_LAST_COUNT_KEY: str(int(outcome.summary["synced_count"])),
                BROKER_ORDER_SYNC_LAST_ERROR_KEY: "",
            }
        )
        logger.info("broker order sync finished: synced=%s skipped=%s failed=%s", outcome.summary["synced_count"], outcome.summary["skipped_count"], outcome.summary["failed_count"])
        return int(outcome.summary["synced_count"])
    except Exception as exc:  # pragma: no cover - defensive logging for live daemon usage
        logger.exception("broker order sync failed: %s", exc)
        repository.set_settings(
            {
                BROKER_ORDER_SYNC_LAST_AT_KEY: current.isoformat(),
                BROKER_ORDER_SYNC_LAST_ERROR_KEY: str(exc),
            }
        )
        return 0
    finally:
        session.close()


def run_once(now: datetime | None = None) -> int:
    count = enqueue_enabled_jobs(now=now)
    logger.info("scheduler enqueue pass finished: enqueued=%s", count)
    _write_scheduler_heartbeat(now=now, last_successful_enqueue_count=count)
    _sync_broker_orders_if_due(now=now)
    return count


def _seconds_until_next_poll(now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    next_minute = (current + timedelta(minutes=1)).replace(second=0, microsecond=0)
    seconds = (next_minute - current).total_seconds() + 1.0
    return max(1.0, min(float(POLL_SECONDS), seconds))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger.info("scheduler started: polling for due jobs")
    while True:
        try:
            run_once()
        except Exception as exc:  # pragma: no cover - defensive logging for live daemon usage
            logger.exception("scheduler enqueue pass failed: %s", exc)
            _write_scheduler_heartbeat(last_error=str(exc))
            traceback.print_exc()
        sleep(_seconds_until_next_poll())


if __name__ == "__main__":
    main()
