from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppPreflightReport, PreflightCheck
from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.preflight import AppPreflightService

router = APIRouter(tags=["health"])


def _create_preflight_service(session: Session) -> AppPreflightService:
    social_settings = SettingsRepository(session).get_social_settings()
    try:
        return AppPreflightService(social_settings)
    except TypeError:
        return AppPreflightService()


def _augment_report_with_snapshot_checks(report: AppPreflightReport, session: Session) -> AppPreflightReport:
    repository = SentimentSnapshotRepository(session)
    latest_macro = repository.get_latest_snapshot("macro", "global_macro")
    latest_industry = next(iter(repository.list_recent_snapshots(scope="industry", limit=1)), None)
    extra_checks: list[PreflightCheck] = []

    for name, label, snapshot in (
        ("sentiment_snapshot:macro", "macro", latest_macro),
        ("sentiment_snapshot:industry", "industry", latest_industry),
    ):
        if snapshot is None:
            extra_checks.append(
                PreflightCheck(
                    name=name,
                    status="warning",
                    message=f"No {label} support snapshot has been computed yet",
                )
            )
            continue
        if snapshot.expires_at is not None and snapshot.expires_at < report.checked_at:
            extra_checks.append(
                PreflightCheck(
                    name=name,
                    status="warning",
                    message=f"Latest {label} support snapshot is expired",
                    details=[
                        f"snapshot_id={snapshot.id}",
                        f"computed_at={snapshot.computed_at.isoformat()}",
                        f"expires_at={snapshot.expires_at.isoformat()}",
                    ],
                )
            )
            continue
        extra_checks.append(
            PreflightCheck(
                name=name,
                status="ok",
                message=f"Latest {label} support snapshot is fresh",
                details=[
                    f"snapshot_id={snapshot.id}",
                    f"computed_at={snapshot.computed_at.isoformat()}",
                    f"expires_at={snapshot.expires_at.isoformat() if snapshot.expires_at else 'none'}",
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
    snapshot_checks = {check.name: check for check in report.checks if check.name.startswith("sentiment_snapshot:")}
    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "preflight": {
            "status": report.status,
            "engine": report.engine,
            "checked_at": report.checked_at.isoformat(),
        },
        "sentiment_snapshots": {
            "macro": snapshot_checks.get("sentiment_snapshot:macro").model_dump() if snapshot_checks.get("sentiment_snapshot:macro") else None,
            "industry": snapshot_checks.get("sentiment_snapshot:industry").model_dump() if snapshot_checks.get("sentiment_snapshot:industry") else None,
        },
    }


@router.get("/health/preflight")
async def preflight_health(session: Session = Depends(get_db_session)) -> AppPreflightReport:
    return _augment_report_with_snapshot_checks(_create_preflight_service(session).run(), session)

