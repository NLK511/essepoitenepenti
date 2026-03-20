import traceback
from datetime import datetime, timedelta, timezone
from time import sleep

from trade_proposer_app.services.runs import enqueue_enabled_jobs


POLL_SECONDS = 30


def run_once(now: datetime | None = None) -> int:
    count = enqueue_enabled_jobs(now=now)
    print(f"scheduler: enqueued {count} scheduled job(s)")
    return count


def _seconds_until_next_poll(now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    next_minute = (current + timedelta(minutes=1)).replace(second=0, microsecond=0)
    seconds = (next_minute - current).total_seconds() + 1.0
    return max(1.0, min(float(POLL_SECONDS), seconds))


def main() -> None:
    print("scheduler started: polling for due jobs")
    while True:
        try:
            run_once()
        except Exception as exc:  # pragma: no cover - defensive logging for live daemon usage
            print(f"scheduler error: enqueue pass failed: {exc}")
            traceback.print_exc()
        sleep(_seconds_until_next_poll())


if __name__ == "__main__":
    main()
