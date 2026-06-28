import json
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import HistoricalReplayBatch, HistoricalReplaySlice
from trade_proposer_app.persistence.models import HistoricalReplayBatchRecord, HistoricalReplaySliceRecord


class HistoricalReplayRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_batch(
        self,
        *,
        name: str,
        mode: str,
        universe_mode: str,
        universe_preset: str | None,
        tickers: list[str],
        entry_timing: str,
        price_provider: str,
        price_source_tier: str,
        bar_timeframe: str,
        as_of_start: datetime,
        as_of_end: datetime,
        cadence: str,
        config: dict[str, object] | None = None,
        status: str = "planned",
        job_id: int | None = None,
    ) -> HistoricalReplayBatch:
        record = HistoricalReplayBatchRecord(
            name=name,
            status=status,
            mode=mode,
            universe_mode=universe_mode,
            universe_preset=universe_preset,
            tickers_json=self._serialize_list(tickers),
            entry_timing=entry_timing,
            price_provider=price_provider,
            price_source_tier=price_source_tier,
            bar_timeframe=bar_timeframe,
            as_of_start=self._normalize(as_of_start),
            as_of_end=self._normalize(as_of_end),
            cadence=cadence,
            config_json=self._serialize(config or {}),
            job_id=job_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_batch_model(record)

    def list_batches(self) -> list[HistoricalReplayBatch]:
        rows = self.session.scalars(
            select(HistoricalReplayBatchRecord).order_by(HistoricalReplayBatchRecord.created_at.desc())
        ).all()
        return [self._to_batch_model(row) for row in rows]

    def get_batch(self, batch_id: int) -> HistoricalReplayBatch:
        record = self.session.get(HistoricalReplayBatchRecord, batch_id)
        if record is None:
            raise ValueError(f"Historical replay batch {batch_id} not found")
        return self._to_batch_model(record)

    def update_batch_status(
        self,
        batch_id: int,
        *,
        status: str,
        summary: dict[str, object] | None = None,
        artifact: dict[str, object] | None = None,
        error_message: str | None = None,
        job_id: int | None = None,
    ) -> HistoricalReplayBatch:
        record = self.session.get(HistoricalReplayBatchRecord, batch_id)
        if record is None:
            raise ValueError(f"Historical replay batch {batch_id} not found")
        record.status = status
        if summary is not None:
            record.summary_json = self._serialize(summary)
        if artifact is not None:
            record.artifact_json = self._serialize(artifact)
        if error_message is not None:
            record.error_message = error_message
        if job_id is not None:
            record.job_id = job_id
        if status in {"completed", "failed", "completed_with_warnings"}:
            record.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return self._to_batch_model(record)

    def create_daily_slices(self, batch_id: int) -> list[HistoricalReplaySlice]:
        batch = self.get_batch(batch_id)
        batch_record = self.session.get(HistoricalReplayBatchRecord, batch_id)
        if batch.cadence != "daily":
            raise ValueError("only daily cadence is currently supported")
        existing = self.list_slices(batch_id)
        if existing:
            return existing
        cursor_date = batch.as_of_start.date()
        end_date = batch.as_of_end.date()
        created: list[HistoricalReplaySlice] = []
        while cursor_date <= end_date:
            if self._is_market_open_date(cursor_date, batch=batch, tickers_json=batch_record.tickers_json if batch_record is not None else "[]"):
                slice_as_of = datetime.combine(cursor_date, time(23, 59, 59), tzinfo=timezone.utc)
                record = HistoricalReplaySliceRecord(
                    replay_batch_id=batch_id,
                    as_of=self._normalize(slice_as_of),
                    status="planned",
                )
                self.session.add(record)
                self.session.flush()
                created.append(self._to_slice_model(record))
            cursor_date = cursor_date + timedelta(days=1)
        self.session.commit()
        return created

    @classmethod
    def _is_market_open_date(cls, value: date, *, batch: HistoricalReplayBatch | None = None, tickers_json: str = "[]") -> bool:
        if value.weekday() >= 5:
            return False
        if batch is not None and cls._uses_us_market_calendar(batch, tickers_json=tickers_json):
            return value not in cls._observed_us_market_holidays(value.year)
        return True

    @staticmethod
    def _uses_us_market_calendar(batch: HistoricalReplayBatch, *, tickers_json: str) -> bool:
        if batch.universe_preset and batch.universe_preset.startswith("us_"):
            return True
        try:
            raw_tickers = json.loads(tickers_json or "[]")
        except json.JSONDecodeError:
            raw_tickers = []
        tickers = [str(ticker).strip().upper() for ticker in raw_tickers if str(ticker).strip()]
        return bool(tickers) and all("." not in ticker for ticker in tickers)

    @classmethod
    def _observed_us_market_holidays(cls, year: int) -> set[date]:
        holidays = {
            cls._observed_fixed_holiday(year, 1, 1),
            cls._nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
            cls._nth_weekday(year, 2, 0, 3),  # Presidents' Day
            cls._good_friday(year),
            cls._last_weekday(year, 5, 0),  # Memorial Day
            cls._observed_fixed_holiday(year, 6, 19),
            cls._observed_fixed_holiday(year, 7, 4),
            cls._nth_weekday(year, 9, 0, 1),  # Labor Day
            cls._nth_weekday(year, 11, 3, 4),  # Thanksgiving
            cls._observed_fixed_holiday(year, 12, 25),
        }
        return {item for item in holidays if item.year == year}

    @staticmethod
    def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
        actual = date(year, month, day)
        if actual.weekday() == 5:
            return actual - timedelta(days=1)
        if actual.weekday() == 6:
            return actual + timedelta(days=1)
        return actual

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
        cursor = date(year, month, 1)
        while cursor.weekday() != weekday:
            cursor += timedelta(days=1)
        return cursor + timedelta(days=7 * (nth - 1))

    @staticmethod
    def _last_weekday(year: int, month: int, weekday: int) -> date:
        if month == 12:
            cursor = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            cursor = date(year, month + 1, 1) - timedelta(days=1)
        while cursor.weekday() != weekday:
            cursor -= timedelta(days=1)
        return cursor

    @classmethod
    def _good_friday(cls, year: int) -> date:
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        left = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * left) // 451
        easter_month = (h + left - 7 * m + 114) // 31
        easter_day = ((h + left - 7 * m + 114) % 31) + 1
        return date(year, easter_month, easter_day) - timedelta(days=2)

    def list_slices(self, batch_id: int) -> list[HistoricalReplaySlice]:
        rows = self.session.scalars(
            select(HistoricalReplaySliceRecord)
            .where(HistoricalReplaySliceRecord.replay_batch_id == batch_id)
            .order_by(HistoricalReplaySliceRecord.as_of.asc())
        ).all()
        return [self._to_slice_model(row) for row in rows]

    def get_slice(self, slice_id: int) -> HistoricalReplaySlice:
        record = self.session.get(HistoricalReplaySliceRecord, slice_id)
        if record is None:
            raise ValueError(f"Historical replay slice {slice_id} not found")
        return self._to_slice_model(record)

    def attach_slice_run(self, slice_id: int, *, job_id: int, run_id: int, status: str = "queued") -> HistoricalReplaySlice:
        record = self.session.get(HistoricalReplaySliceRecord, slice_id)
        if record is None:
            raise ValueError(f"Historical replay slice {slice_id} not found")
        record.job_id = job_id
        record.run_id = run_id
        record.status = status
        self.session.commit()
        self.session.refresh(record)
        return self._to_slice_model(record)

    def update_slice_status(
        self,
        slice_id: int,
        *,
        status: str,
        input_summary: dict[str, object] | None = None,
        output_summary: dict[str, object] | None = None,
        timing: dict[str, object] | None = None,
        error_message: str | None = None,
    ) -> HistoricalReplaySlice:
        record = self.session.get(HistoricalReplaySliceRecord, slice_id)
        if record is None:
            raise ValueError(f"Historical replay slice {slice_id} not found")
        record.status = status
        if input_summary is not None:
            record.input_summary_json = self._serialize(input_summary)
        if output_summary is not None:
            record.output_summary_json = self._serialize(output_summary)
        if timing is not None:
            record.timing_json = self._serialize(timing)
        if error_message is not None:
            record.error_message = error_message
        self.session.commit()
        self.session.refresh(record)
        return self._to_slice_model(record)

    def summarize_batch(self, batch_id: int) -> dict[str, object]:
        rows = self.session.execute(
            select(HistoricalReplaySliceRecord.status, func.count(HistoricalReplaySliceRecord.id))
            .where(HistoricalReplaySliceRecord.replay_batch_id == batch_id)
            .group_by(HistoricalReplaySliceRecord.status)
        ).all()
        counts = {status: count for status, count in rows}
        total = sum(counts.values())
        return {
            "slice_count": total,
            "status_counts": counts,
            "queued_count": counts.get("queued", 0),
            "running_count": counts.get("running", 0),
            "completed_count": counts.get("completed", 0),
            "failed_count": counts.get("failed", 0),
            "planned_count": counts.get("planned", 0),
        }

    def refresh_batch_status(self, batch_id: int) -> HistoricalReplayBatch:
        batch = self.get_batch(batch_id)
        summary = self.summarize_batch(batch_id)
        counts = summary.get("status_counts", {})
        total = int(summary.get("slice_count", 0) or 0)
        completed = int(counts.get("completed", 0) or 0)
        failed = int(counts.get("failed", 0) or 0)
        running = int(counts.get("running", 0) or 0)
        queued = int(counts.get("queued", 0) or 0)

        status = batch.status
        if total == 0 or int(counts.get("planned", 0) or 0) == total:
            status = "planned"
        elif running > 0:
            status = "running"
        elif queued > 0:
            status = "queued"
        elif completed + failed == total:
            status = "failed" if failed == total else ("completed_with_warnings" if failed > 0 else "completed")

        return self.update_batch_status(batch_id, status=status, summary=summary)

    @staticmethod
    def _serialize(payload: dict[str, object]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)

    @staticmethod
    def _serialize_list(payload: list[object]) -> str:
        return json.dumps(payload, indent=2)

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _to_batch_model(cls, record: HistoricalReplayBatchRecord) -> HistoricalReplayBatch:
        return HistoricalReplayBatch(
            id=record.id,
            name=record.name,
            status=record.status,
            mode=record.mode,
            universe_mode=getattr(record, "universe_mode", "explicit"),
            universe_preset=getattr(record, "universe_preset", None),
            tickers_json=getattr(record, "tickers_json", "[]") or "[]",
            entry_timing=getattr(record, "entry_timing", "next_open"),
            price_provider=getattr(record, "price_provider", "yahoo"),
            price_source_tier=getattr(record, "price_source_tier", "research"),
            bar_timeframe=getattr(record, "bar_timeframe", "1d"),
            as_of_start=cls._normalize(record.as_of_start),
            as_of_end=cls._normalize(record.as_of_end),
            cadence=record.cadence,
            config_json=record.config_json or "{}",
            summary_json=record.summary_json or "{}",
            artifact_json=record.artifact_json or "{}",
            error_message=record.error_message or None,
            job_id=record.job_id,
            started_at=cls._normalize(record.started_at) if record.started_at else None,
            completed_at=cls._normalize(record.completed_at) if record.completed_at else None,
            created_at=cls._normalize(record.created_at),
            updated_at=cls._normalize(record.updated_at),
        )

    @classmethod
    def _to_slice_model(cls, record: HistoricalReplaySliceRecord) -> HistoricalReplaySlice:
        return HistoricalReplaySlice(
            id=record.id,
            replay_batch_id=record.replay_batch_id,
            job_id=record.job_id,
            run_id=record.run_id,
            as_of=cls._normalize(record.as_of),
            status=record.status,
            error_message=record.error_message or None,
            input_summary_json=record.input_summary_json or "{}",
            output_summary_json=record.output_summary_json or "{}",
            timing_json=record.timing_json or "{}",
            created_at=cls._normalize(record.created_at),
            updated_at=cls._normalize(record.updated_at),
        )


HistoricalReplayRepository = HistoricalReplayRepository
