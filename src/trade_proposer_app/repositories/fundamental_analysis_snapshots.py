from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import FundamentalAnalysisSnapshotRecord


class FundamentalAnalysisSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_snapshot(
        self,
        *,
        ticker: str,
        as_of: datetime,
        source_set: list[str],
        coverage_status: str,
        freshness_status: str,
        payload: dict[str, Any],
        warnings: list[str],
        missing_inputs: list[str],
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        record = FundamentalAnalysisSnapshotRecord(
            ticker=self._ticker(ticker),
            as_of=self._dt(as_of) or datetime.now(timezone.utc),
            source_set_json=self._dump(source_set),
            coverage_status=str(coverage_status or "degraded"),
            freshness_status=str(freshness_status or "unknown"),
            payload_json=self._dump(payload),
            warnings_json=self._dump(warnings),
            missing_inputs_json=self._dump(missing_inputs),
            job_id=job_id,
            run_id=run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dict(record)

    def get_latest_for_ticker(self, ticker: str) -> dict[str, Any] | None:
        return self._first(
            select(FundamentalAnalysisSnapshotRecord)
            .where(FundamentalAnalysisSnapshotRecord.ticker == self._ticker(ticker))
            .order_by(FundamentalAnalysisSnapshotRecord.as_of.desc(), FundamentalAnalysisSnapshotRecord.id.desc())
        )

    def get_latest_at_or_before(self, ticker: str, as_of: datetime) -> dict[str, Any] | None:
        normalized_as_of = self._dt(as_of) or datetime.now(timezone.utc)
        return self._first(
            select(FundamentalAnalysisSnapshotRecord)
            .where(FundamentalAnalysisSnapshotRecord.ticker == self._ticker(ticker))
            .where(FundamentalAnalysisSnapshotRecord.as_of <= normalized_as_of)
            .order_by(FundamentalAnalysisSnapshotRecord.as_of.desc(), FundamentalAnalysisSnapshotRecord.id.desc())
        )

    def list_latest_by_tickers(self, tickers: list[str], as_of: datetime | None = None) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            snapshot = self.get_latest_at_or_before(ticker, as_of) if as_of is not None else self.get_latest_for_ticker(ticker)
            if snapshot is not None:
                result[self._ticker(ticker)] = snapshot
        return result

    def list_stale_monitored_tickers(self, monitored_tickers: list[str], stale_before: datetime) -> list[str]:
        stale: list[str] = []
        for ticker in sorted({self._ticker(value) for value in monitored_tickers if self._ticker(value)}):
            latest = self.get_latest_for_ticker(ticker)
            if latest is None or self._dt(latest.get("as_of")) < self._dt(stale_before):
                stale.append(ticker)
        return stale

    def _first(self, query) -> dict[str, Any] | None:
        record = self.session.scalars(query).first()
        return self._to_dict(record) if record is not None else None

    @classmethod
    def _to_dict(cls, record: FundamentalAnalysisSnapshotRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "ticker": record.ticker,
            "as_of": cls._dt(record.as_of),
            "source_set": cls._loads_list(record.source_set_json),
            "coverage_status": record.coverage_status,
            "freshness_status": record.freshness_status,
            "payload": cls._loads_dict(record.payload_json),
            "warnings": cls._loads_list(record.warnings_json),
            "missing_inputs": cls._loads_list(record.missing_inputs_json),
            "job_id": record.job_id,
            "run_id": record.run_id,
            "created_at": cls._dt(record.created_at),
            "updated_at": cls._dt(record.updated_at),
        }

    @staticmethod
    def _ticker(value: str) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=str)

    @staticmethod
    def _loads_dict(raw: str | None) -> dict[str, Any]:
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _loads_list(raw: str | None) -> list[Any]:
        try:
            parsed = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
