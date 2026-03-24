from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import Job
from trade_proposer_app.persistence.models import JobRecord, RecommendationRecord, RunRecord, WatchlistRecord


SYSTEM_JOB_PREFIX = "__system__:"


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[Job]:
        rows = self.session.scalars(
            select(JobRecord)
            .where(~JobRecord.name.startswith(SYSTEM_JOB_PREFIX))
            .order_by(JobRecord.name)
        ).all()
        return [self._to_model(row) for row in rows]

    def list_enabled(self) -> list[Job]:
        rows = self.session.scalars(
            select(JobRecord)
            .where(JobRecord.enabled.is_(True))
            .where(~JobRecord.name.startswith(SYSTEM_JOB_PREFIX))
            .order_by(JobRecord.name)
        ).all()
        return [self._to_model(row) for row in rows]

    def get(self, job_id: int) -> Job:
        record = self.session.get(JobRecord, job_id)
        if record is None:
            raise ValueError(f"Job {job_id} not found")
        return self._to_model(record)

    def create(
        self,
        name: str,
        tickers: list[str],
        schedule: str | None,
        enabled: bool = True,
        watchlist_id: int | None = None,
        job_type: JobType = JobType.PROPOSAL_GENERATION,
    ) -> Job:
        normalized_tickers = [ticker for ticker in tickers if ticker]
        self._validate_job_source(job_type, normalized_tickers, watchlist_id)

        if watchlist_id is not None:
            watchlist = self.session.get(WatchlistRecord, watchlist_id)
            if watchlist is None:
                raise ValueError(f"Watchlist {watchlist_id} not found")

        record = JobRecord(
            name=name,
            job_type=job_type.value,
            tickers_csv=",".join(normalized_tickers),
            watchlist_id=watchlist_id,
            schedule=schedule,
            enabled=enabled,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def update(
        self,
        job_id: int,
        name: str,
        tickers: list[str],
        schedule: str | None,
        enabled: bool,
        watchlist_id: int | None = None,
        job_type: JobType = JobType.PROPOSAL_GENERATION,
    ) -> Job:
        record = self.session.get(JobRecord, job_id)
        if record is None:
            raise ValueError(f"Job {job_id} not found")

        normalized_tickers = [ticker for ticker in tickers if ticker]
        self._validate_job_source(job_type, normalized_tickers, watchlist_id)

        if watchlist_id is not None:
            watchlist = self.session.get(WatchlistRecord, watchlist_id)
            if watchlist is None:
                raise ValueError(f"Watchlist {watchlist_id} not found")

        record.name = name
        record.job_type = job_type.value
        record.tickers_csv = ",".join(normalized_tickers)
        record.watchlist_id = watchlist_id
        record.schedule = schedule
        record.enabled = enabled
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def delete(self, job_id: int) -> None:
        record = self.session.get(JobRecord, job_id)
        if record is None:
            raise ValueError(f"Job {job_id} not found")

        run_ids = list(
            self.session.scalars(
                select(RunRecord.id)
                .where(RunRecord.job_id == job_id)
            ).all()
        )
        if run_ids:
            self.session.execute(delete(RecommendationRecord).where(RecommendationRecord.run_id.in_(run_ids)))
            self.session.execute(delete(RunRecord).where(RunRecord.id.in_(run_ids)))

        self.session.execute(delete(JobRecord).where(JobRecord.id == job_id))
        self.session.commit()

    def mark_enqueued(self, job_id: int) -> Job:
        record = self.session.get(JobRecord, job_id)
        if record is None:
            raise ValueError(f"Job {job_id} not found")
        record.last_enqueued_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def resolve_tickers(self, job_id: int) -> list[str]:
        record = self.session.get(JobRecord, job_id)
        if record is None:
            raise ValueError(f"Job {job_id} not found")
        if record.watchlist_id is not None:
            watchlist = self.session.get(WatchlistRecord, record.watchlist_id)
            if watchlist is None:
                raise ValueError(f"Watchlist {record.watchlist_id} not found")
            tickers = [ticker for ticker in watchlist.tickers_csv.split(",") if ticker]
        else:
            tickers = [ticker for ticker in record.tickers_csv.split(",") if ticker]

        if not tickers:
            raise ValueError("job has no effective tickers configured")
        return tickers

    def get_or_create_system_job(self, name: str, job_type: JobType) -> Job:
        normalized_name = f"{SYSTEM_JOB_PREFIX}{name.strip()}"
        record = self.session.scalars(
            select(JobRecord).where(JobRecord.name == normalized_name).limit(1)
        ).first()
        if record is None:
            record = JobRecord(
                name=normalized_name,
                job_type=job_type.value,
                tickers_csv="",
                watchlist_id=None,
                schedule=None,
                enabled=False,
            )
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
        return self._to_model(record)

    @staticmethod
    def _validate_job_source(job_type: JobType, tickers: list[str], watchlist_id: int | None) -> None:
        has_tickers = bool(tickers)
        has_watchlist = watchlist_id is not None
        if job_type == JobType.PROPOSAL_GENERATION:
            if has_tickers == has_watchlist:
                raise ValueError("job must use exactly one source: either manual tickers or a watchlist")
            return
        if has_tickers or has_watchlist:
            raise ValueError("non-proposal jobs must not define tickers or a watchlist source")

    @staticmethod
    def _to_model(record: JobRecord) -> Job:
        watchlist = record.watchlist
        return Job(
            id=record.id,
            name=record.name,
            job_type=JobType(record.job_type or JobType.PROPOSAL_GENERATION.value),
            tickers=[ticker for ticker in record.tickers_csv.split(",") if ticker],
            watchlist_id=record.watchlist_id,
            watchlist_name=watchlist.name if watchlist is not None else None,
            watchlist_description=watchlist.description if watchlist is not None else "",
            watchlist_region=watchlist.region if watchlist is not None else "",
            watchlist_exchange=watchlist.exchange if watchlist is not None else "",
            watchlist_timezone=watchlist.timezone if watchlist is not None else "",
            watchlist_default_horizon=(StrategyHorizon(watchlist.default_horizon) if watchlist is not None else None),
            watchlist_allow_shorts=watchlist.allow_shorts if watchlist is not None else True,
            watchlist_optimize_evaluation_timing=watchlist.optimize_evaluation_timing if watchlist is not None else False,
            enabled=record.enabled,
            cron=record.schedule,
            last_enqueued_at=record.last_enqueued_at,
        )
