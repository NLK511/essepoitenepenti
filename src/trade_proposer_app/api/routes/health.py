from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppPreflightReport, PreflightCheck
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.preflight import AppPreflightService

router = APIRouter(tags=["health"])


def _create_preflight_service(session: Session) -> AppPreflightService:
    social_settings = SettingsRepository(session).get_social_settings()
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


def _augment_report_with_snapshot_checks(report: AppPreflightReport, session: Session) -> AppPreflightReport:
    context_repository = ContextSnapshotRepository(session)
    latest_macro_context = context_repository.get_latest_macro_context_snapshot()
    latest_industry_context = next(iter(context_repository.list_industry_context_snapshots(limit=1)), None)
    runs_repository = RunRepository(session)
    active_workers = runs_repository.list_active_workers(stale_seconds=settings.worker_heartbeat_interval_seconds * 2)
    extra_checks: list[PreflightCheck] = []

    worker_status = "ok" if active_workers else "warning"
    extra_checks.append(
        PreflightCheck(
            name="worker:heartbeat",
            status=worker_status,
            message=f"{len(active_workers)} workers active" if active_workers else "No active workers detected",
            details=[f"worker_id={w.worker_id}, hostname={w.hostname}, pid={w.pid}" for w in active_workers]
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
    if any(check.status == "failed" for check in merged_checks):
        status = "failed"
    elif any(check.status == "warning" for check in merged_checks):
        status = "warning"
    return AppPreflightReport(
        status=status,
        checked_at=report.checked_at,
        engine=report.engine,
        checks=merged_checks,
    )


@router.get("/health")
async def health(session: Session = Depends(get_db_session)) -> dict[str, object]:
    report = _augment_report_with_snapshot_checks(_create_preflight_service(session).run(), session)
    status = "ok" if report.status == "ok" else "degraded"
    context_checks = {check.name: check for check in report.checks if check.name.startswith("context_snapshot:")}
    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "preflight": {
            "status": report.status,
            "engine": report.engine,
            "checked_at": report.checked_at.isoformat(),
        },
        "context_snapshots": {
            "macro": context_checks.get("context_snapshot:macro").model_dump() if context_checks.get("context_snapshot:macro") else None,
            "industry": context_checks.get("context_snapshot:industry").model_dump() if context_checks.get("context_snapshot:industry") else None,
        },
        "workers": {
            "status": next((c.status for c in report.checks if c.name == "worker:heartbeat"), "unknown"),
            "count": len(next((c.details or [] for c in report.checks if c.name == "worker:heartbeat"), [])),
            "details": next((c.details or [] for c in report.checks if c.name == "worker:heartbeat"), []),
        },
    }


@router.get("/health/preflight")
async def preflight_health(session: Session = Depends(get_db_session)) -> AppPreflightReport:
    return _augment_report_with_snapshot_checks(_create_preflight_service(session).run(), session)

