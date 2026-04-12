import logging
import traceback
from datetime import datetime, timedelta, timezone
from time import sleep

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.runs import enqueue_enabled_jobs


logger = logging.getLogger(__name__)


POLL_SECONDS = 30


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


def run_once(now: datetime | None = None) -> int:
    count = enqueue_enabled_jobs(now=now)
    logger.info("scheduler enqueue pass finished: enqueued=%s", count)
    _write_scheduler_heartbeat(now=now, last_successful_enqueue_count=count)
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
