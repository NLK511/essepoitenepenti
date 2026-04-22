from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import desc, inspect, insert, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationSignalGatingTuningRun
from trade_proposer_app.persistence.models import RecommendationSignalGatingTuningRunRecord


class RecommendationSignalGatingTuningRunRepository:
    _FIELDS_IN_STORAGE_ORDER = (
        "id",
        "objective_name",
        "status",
        "applied",
        "filters_json",
        "sample_count",
        "resolved_sample_count",
        "benchmark_sample_count",
        "scoreable_sample_count",
        "candidate_count",
        "baseline_threshold",
        "baseline_score",
        "best_threshold",
        "best_score",
        "winning_config_json",
        "candidate_results_json",
        "summary_json",
        "artifact_json",
        "error_message",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    )

    _LEGACY_OPTIONAL_COLUMNS = {"benchmark_sample_count", "scoreable_sample_count"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self._table_columns = self._load_table_columns()

    def create_run(self, run: RecommendationSignalGatingTuningRun) -> RecommendationSignalGatingTuningRun:
        values = self._run_to_values(run)
        payload = self._filter_payload(values, include_optional=True)
        inserted_id = self._insert_run_row(payload)
        if inserted_id is None:
            payload = self._filter_payload(values, include_optional=False)
            inserted_id = self._insert_run_row(payload)
        if inserted_id is None:
            raise RuntimeError("failed to create signal gating tuning run")
        stored = self._fetch_run_by_id(int(inserted_id))
        if stored is None:
            raise RuntimeError("signal gating tuning run was created but could not be loaded")
        return stored

    def list_runs(self, limit: int = 20) -> list[RecommendationSignalGatingTuningRun]:
        return self._fetch_runs(limit=limit)

    def get_latest_run(self) -> RecommendationSignalGatingTuningRun | None:
        rows = self._fetch_runs(limit=1)
        return rows[0] if rows else None

    def get_latest_applied_run(self) -> RecommendationSignalGatingTuningRun | None:
        rows = self._fetch_runs(where_clause=RecommendationSignalGatingTuningRunRecord.applied.is_(True), limit=1)
        return rows[0] if rows else None

    def _load_table_columns(self) -> set[str]:
        bind = self.session.get_bind()
        if bind is None:
            return set()
        try:
            if getattr(bind.dialect, "name", "") == "sqlite":
                rows = self.session.execute(text(f"PRAGMA table_info({RecommendationSignalGatingTuningRunRecord.__tablename__})")).mappings().all()
                return {row["name"] for row in rows}
            inspector = inspect(bind)
            return {column["name"] for column in inspector.get_columns(RecommendationSignalGatingTuningRunRecord.__tablename__)}
        except Exception:
            return set()

    def _run_to_values(self, run: RecommendationSignalGatingTuningRun) -> dict[str, object]:
        return {
            "id": run.id,
            "objective_name": run.objective_name,
            "status": run.status,
            "applied": run.applied,
            "filters_json": self._dump(run.filters),
            "sample_count": run.sample_count,
            "resolved_sample_count": run.resolved_sample_count,
            "benchmark_sample_count": run.benchmark_sample_count,
            "scoreable_sample_count": run.scoreable_sample_count,
            "candidate_count": run.candidate_count,
            "baseline_threshold": run.baseline_threshold,
            "baseline_score": run.baseline_score,
            "best_threshold": run.best_threshold,
            "best_score": run.best_score,
            "winning_config_json": self._dump(run.winning_config),
            "candidate_results_json": self._dump(run.candidate_results),
            "summary_json": self._dump(run.summary),
            "artifact_json": self._dump(run.artifact),
            "error_message": run.error_message or "",
            "started_at": self._normalize_datetime(run.started_at),
            "completed_at": self._normalize_datetime(run.completed_at),
            "created_at": self._normalize_datetime(run.created_at),
            "updated_at": self._normalize_datetime(run.updated_at),
        }

    def _filter_payload(self, values: dict[str, object], *, include_optional: bool) -> dict[str, object]:
        excluded = {"id"}
        if not include_optional:
            excluded.update(self._LEGACY_OPTIONAL_COLUMNS)
        return {key: value for key, value in values.items() if key in self._table_columns and key not in excluded}

    def _insert_run_row(self, payload: dict[str, object]) -> int | None:
        if not payload:
            return None
        columns = list(payload.keys())
        column_sql = ", ".join(columns)
        placeholder_sql = ", ".join(f":{column}" for column in columns)
        statement = text(
            f"INSERT INTO {RecommendationSignalGatingTuningRunRecord.__tablename__} ({column_sql}) VALUES ({placeholder_sql}) RETURNING id"
        )
        try:
            result = self.session.execute(statement, payload)
            inserted_id = result.scalar_one_or_none()
            self.session.commit()
            return int(inserted_id) if inserted_id is not None else None
        except OperationalError:
            self.session.rollback()
            return None

    @classmethod
    def _looks_like_missing_optional_columns(cls, exc: OperationalError) -> bool:
        message = str(exc).lower()
        return any(column in message for column in cls._LEGACY_OPTIONAL_COLUMNS)

    def _selected_run_columns(self, *, include_optional: bool = True) -> list[object]:
        columns: list[object] = []
        for field_name in self._FIELDS_IN_STORAGE_ORDER:
            if not include_optional and field_name in self._LEGACY_OPTIONAL_COLUMNS:
                continue
            if field_name in self._table_columns:
                columns.append(getattr(RecommendationSignalGatingTuningRunRecord, field_name))
        return columns

    def _order_by_columns(self, *, prefer_completed: bool = False) -> list[object]:
        columns: list[object] = []
        preferred = ("completed_at", "created_at", "id") if prefer_completed else ("created_at", "id")
        for field_name in preferred:
            if field_name in self._table_columns:
                columns.append(desc(getattr(RecommendationSignalGatingTuningRunRecord, field_name)))
        return columns

    def _fetch_runs(self, *, where_clause=None, limit: int = 20) -> list[RecommendationSignalGatingTuningRun]:
        for include_optional in (True, False):
            columns = self._selected_run_columns(include_optional=include_optional)
            if not columns:
                return []
            query = select(*columns)
            if where_clause is not None and "applied" in self._table_columns:
                query = query.where(where_clause)
            order_by = self._order_by_columns(prefer_completed=where_clause is not None)
            if order_by:
                query = query.order_by(*order_by)
            query = query.limit(limit)
            try:
                rows = self.session.execute(query).mappings().all()
            except OperationalError as exc:
                if include_optional and self._looks_like_missing_optional_columns(exc):
                    self.session.rollback()
                    continue
                raise
            return [self._to_model(row) for row in rows]
        return []

    def _fetch_run_by_id(self, run_id: int) -> RecommendationSignalGatingTuningRun | None:
        if "id" not in self._table_columns:
            return None
        for include_optional in (True, False):
            columns = self._selected_run_columns(include_optional=include_optional)
            if not columns:
                return None
            query = select(*columns).where(getattr(RecommendationSignalGatingTuningRunRecord, "id") == run_id).limit(1)
            try:
                row = self.session.execute(query).mappings().first()
            except OperationalError as exc:
                if include_optional and self._looks_like_missing_optional_columns(exc):
                    self.session.rollback()
                    continue
                raise
            return self._to_model(row) if row is not None else None
        return None

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=RecommendationSignalGatingTuningRunRepository._json_default)

    @staticmethod
    def _json_default(value: object) -> object:
        if isinstance(value, datetime):
            normalized = RecommendationSignalGatingTuningRunRepository._normalize_datetime(value)
            return normalized.isoformat() if normalized is not None else None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    def _to_model(self, record: dict[str, object]) -> RecommendationSignalGatingTuningRun:
        return RecommendationSignalGatingTuningRun(
            id=self._get_int(record, "id"),
            objective_name=self._get_str(record, "objective_name", "signal_gating_tuning_raw_grid"),
            status=self._get_str(record, "status", "completed"),
            applied=self._get_bool(record, "applied", False),
            filters=self._load_json(self._get_str(record, "filters_json", "{}")),
            sample_count=self._get_int(record, "sample_count", 0),
            resolved_sample_count=self._get_int(record, "resolved_sample_count", 0),
            benchmark_sample_count=self._get_int(record, "benchmark_sample_count", 0),
            scoreable_sample_count=self._get_int(record, "scoreable_sample_count", 0),
            candidate_count=self._get_int(record, "candidate_count", 0),
            baseline_threshold=self._get_float(record, "baseline_threshold"),
            baseline_score=self._get_float(record, "baseline_score"),
            best_threshold=self._get_float(record, "best_threshold"),
            best_score=self._get_float(record, "best_score"),
            winning_config=self._load_json(self._get_str(record, "winning_config_json", "{}")),
            candidate_results=self._load_json_list(self._get_str(record, "candidate_results_json", "[]")),
            summary=self._load_json(self._get_str(record, "summary_json", "{}")),
            artifact=self._load_json(self._get_str(record, "artifact_json", "{}")),
            error_message=self._get_str(record, "error_message", None),
            started_at=self._normalize_datetime(self._get_datetime(record, "started_at")),
            completed_at=self._normalize_datetime(self._get_datetime(record, "completed_at")),
            created_at=self._normalize_datetime(self._get_datetime(record, "created_at")) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(self._get_datetime(record, "updated_at")) or datetime.now(timezone.utc),
        )

    @staticmethod
    def _get_str(record: dict[str, object], key: str, default: str | None = None) -> str | None:
        value = record.get(key, default)
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _get_int(record: dict[str, object], key: str, default: int | None = None) -> int:
        value = record.get(key, default)
        if value is None:
            return 0 if default is None else default
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0 if default is None else default

    @staticmethod
    def _get_float(record: dict[str, object], key: str, default: float | None = None) -> float | None:
        value = record.get(key, default)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_bool(record: dict[str, object], key: str, default: bool = False) -> bool:
        value = record.get(key, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_datetime(record: dict[str, object], key: str) -> datetime | None:
        value = record.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed
        return None

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_json_list(raw: str | None) -> list[dict[str, object]]:
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []
