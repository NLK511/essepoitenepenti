from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppPreflightReport, PreflightCheck
from trade_proposer_app.domain.statuses import (
    is_failed_preflight_status,
    is_warning_preflight_status,
)
from trade_proposer_app.persistence.models import BrokerCircuitBreakerRecord
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.preflight import AppPreflightService
from trade_proposer_app.services.runtime_supervision import RuntimeSupervisionService
from trade_proposer_app.services.settings_domains import SettingsDomainService

router = APIRouter(tags=["health"])


def _create_preflight_service(session: Session) -> AppPreflightService:
    social_settings = SettingsDomainService(session).operator_settings().social
    try:
        return AppPreflightService(social_settings)
    except TypeError:
        return AppPreflightService()


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _augment_report_with_snapshot_checks(
    report: AppPreflightReport, session: Session
) -> AppPreflightReport:
    context_repository = ContextSnapshotRepository(session)
    latest_macro_context = context_repository.get_latest_macro_context_snapshot()
    latest_industry_context = next(
        iter(context_repository.list_industry_context_snapshots(limit=1)), None
    )
    runs_repository = RunRepository(session)
    active_workers = runs_repository.list_active_workers(
        stale_seconds=settings.worker_heartbeat_interval_seconds * 2
    )
    extra_checks: list[PreflightCheck] = []

    worker_status = "ok" if active_workers else "warning"
    extra_checks.append(
        PreflightCheck(
            name="worker:heartbeat",
            status=worker_status,
            message=f"{len(active_workers)} workers active"
            if active_workers
            else "No active workers detected",
            details=[
                f"worker_id={w.worker_id}, hostname={w.hostname}, pid={w.pid}"
                for w in active_workers
            ],
        )
    )

    for name, label, snapshot in (
        ("context_snapshot:macro", "macro context", latest_macro_context),
        ("context_snapshot:industry", "industry context", latest_industry_context),
    ):
        if snapshot is None:
            extra_checks.append(
                PreflightCheck(
                    name=name,
                    status="warning",
                    message=f"No {label} snapshot has been computed yet",
                )
            )
            continue

        computed_at = _normalize_datetime(getattr(snapshot, "computed_at", None))
        expires_at = _normalize_datetime(getattr(snapshot, "expires_at", None))
        checked_at = _normalize_datetime(report.checked_at) or report.checked_at

        if expires_at is not None and checked_at is not None and expires_at < checked_at:
            extra_checks.append(
                PreflightCheck(
                    name=name,
                    status="warning",
                    message=f"Latest {label} snapshot is expired",
                    details=[
                        f"snapshot_id={snapshot.id}",
                        f"computed_at={computed_at.isoformat() if computed_at else 'unknown'}",
                        f"expires_at={expires_at.isoformat()}",
                    ],
                )
            )
            continue
        extra_checks.append(
            PreflightCheck(
                name=name,
                status="ok",
                message=f"Latest {label} snapshot is fresh",
                details=[
                    f"snapshot_id={snapshot.id}",
                    f"computed_at={computed_at.isoformat() if computed_at else 'unknown'}",
                    f"expires_at={expires_at.isoformat() if expires_at else 'none'}",
                ],
            )
        )

    merged_checks = [*report.checks, *extra_checks]
    status = "ok"
    if any(is_failed_preflight_status(check.status) for check in merged_checks):
        status = "failed"
    elif any(is_warning_preflight_status(check.status) for check in merged_checks):
        status = "warning"
    return AppPreflightReport(
        status=status,
        checked_at=report.checked_at,
        engine=report.engine,
        checks=merged_checks,
    )


@router.get("/health")
async def health(session: Session = Depends(get_db_session)) -> dict[str, object]:
    database_status = "ok"
    try:
        session.connection()
    except Exception:
        database_status = "failed"
    status = "ok" if database_status == "ok" else "degraded"
    return {
        "status": status,
        "api": "ok",
        "database": database_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/preflight")
async def preflight_health(session: Session = Depends(get_db_session)) -> AppPreflightReport:
    return _augment_report_with_snapshot_checks(_create_preflight_service(session).run(), session)


@router.get("/health/runtime")
async def runtime_health(session: Session = Depends(get_db_session)) -> dict[str, object]:
    runtime = RuntimeSupervisionService(session).runtime_summary()
    runs = RunRepository(session)
    scheduler_settings = SettingsDomainService(session).scheduler_settings()
    active_workers = runs.list_active_workers(
        stale_seconds=settings.worker_heartbeat_interval_seconds * 2
    )
    setting_map = SettingsDomainService(session).repository.get_setting_map()
    global_halt_enabled = (
        str(setting_map.get("broker_global_halt_enabled", "false")).lower() == "true"
    )
    active_circuit_breaker_count = len(
        session.scalars(
            select(BrokerCircuitBreakerRecord).where(BrokerCircuitBreakerRecord.active.is_(True))
        ).all()
    )
    return {
        "status": "warning" if runtime["counts"]["stale"] else "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime,
        "worker_health": {
            "active_worker_count": len(active_workers),
            "workers": [
                {
                    "worker_id": worker.worker_id,
                    "hostname": worker.hostname,
                    "pid": worker.pid,
                    "status": worker.status,
                    "active_run_id": worker.active_run_id,
                    "last_heartbeat_at": worker.last_heartbeat_at.isoformat(),
                }
                for worker in active_workers
            ],
        },
        "scheduler_health": {
            "last_poll_at": scheduler_settings.last_poll_at,
            "last_success_at": scheduler_settings.last_success_at,
            "last_enqueue_count": scheduler_settings.last_enqueue_count or "",
            "last_error": scheduler_settings.last_error or "",
        },
        "run_health": {
            "queued_run_count": runs.count_runs_by_status("queued"),
            "running_run_count": runs.count_runs_by_status("running"),
            "stale_running_run_count": runs.count_stale_running_runs(
                stale_after_seconds=settings.run_stale_after_seconds,
                now=datetime.now(timezone.utc),
            ),
        },
        "broker_safety": {
            "global_halt_enabled": global_halt_enabled,
            "active_circuit_breaker_count": active_circuit_breaker_count,
        },
    }


@router.get("/health/runtime/events")
async def runtime_health_events(
    limit: int = 100, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    return {
        "events": RuntimeSupervisionService(session).runtime_events(limit=limit),
    }
