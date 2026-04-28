#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import (
    IndustryContextRefreshPayload,
    MacroContextRefreshPayload,
    ProviderCredential,
)
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.news import NewsAPIProvider, NewsIngestionService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_NEWS_LIMIT = 12
DEFAULT_REQUEST_MODE = "replay"
DEFAULT_MACRO_SUBJECT_KEY = "global_macro"
DEFAULT_MACRO_SUBJECT_LABEL = "Global Macro"
DEFAULT_INTER_REQUEST_DELAY_SECONDS = 0.15
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 20.0
DEFAULT_MAX_CONSECUTIVE_RATE_LIMIT_ERRORS = 6


def is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "429" in message or "rate limit" in message or "too many requests" in message


def parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError("dates must use YYYY-MM-DD or DD/MM/YYYY")


def iter_business_days(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def default_backfill_range(reference_date: date | None = None) -> tuple[date, date]:
    """Return the latest completed Monday-Friday window as a date range."""

    today = reference_date or datetime.now(timezone.utc).date()
    weekday = today.weekday()
    # Latest fully completed business day.
    if weekday == 0:
        end_date = today - timedelta(days=3)
    elif weekday in (1, 2, 3, 4):
        end_date = today - timedelta(days=1)
    elif weekday == 5:
        end_date = today - timedelta(days=1)
    else:
        end_date = today - timedelta(days=2)

    business_days = [end_date]
    cursor = end_date
    while len(business_days) < 5:
        cursor -= timedelta(days=1)
        if cursor.weekday() < 5:
            business_days.append(cursor)

    return min(business_days), max(business_days)


def resolve_newsapi_api_key(session: Session | None = None, *, api_key_override: str | None = None) -> str:
    override = (api_key_override or "").strip()
    if override:
        return override

    for env_name in ("NEWSAPI_API_KEY", "NEWS_API_KEY"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return env_value

    if session is not None:
        settings_repo = SettingsRepository(session)
        credential = settings_repo.get_provider_credential_map().get("newsapi")
        if credential and credential.api_key:
            return credential.api_key.strip()

    raise ValueError(
        "missing NewsAPI api key; pass --newsapi-api-key, set NEWSAPI_API_KEY, or store a newsapi provider credential"
    )


def build_newsapi_service(*, api_key: str, max_articles: int = DEFAULT_NEWS_LIMIT) -> NewsIngestionService:
    credential = ProviderCredential(provider="newsapi", api_key=api_key, api_secret="")
    provider = NewsAPIProvider(credential)
    return NewsIngestionService([provider], max_articles=max_articles, historical_news=None)


def build_context_services(
    session: Session,
    *,
    newsapi_api_key: str | None = None,
    news_limit: int = DEFAULT_NEWS_LIMIT,
) -> tuple[MacroContextService, IndustryContextService, TickerTaxonomyService]:
    api_key = resolve_newsapi_api_key(session, api_key_override=newsapi_api_key)
    news_service = build_newsapi_service(api_key=api_key, max_articles=news_limit)
    repository = ContextSnapshotRepository(session)
    taxonomy_service = TickerTaxonomyService()
    macro_service = MacroContextService(
        repository,
        news_service=news_service,
        summary_service=None,
        taxonomy_service=taxonomy_service,
    )
    industry_service = IndustryContextService(
        repository,
        news_service=news_service,
        summary_service=None,
        taxonomy_service=taxonomy_service,
    )
    return macro_service, industry_service, taxonomy_service


def run_context_backfill(
    session: Session,
    start_date: date,
    end_date: date,
    *,
    request_mode: str = DEFAULT_REQUEST_MODE,
    newsapi_api_key: str | None = None,
    news_limit: int = DEFAULT_NEWS_LIMIT,
    industry_keys: Iterable[str] | None = None,
    macro_service: MacroContextService | None = None,
    industry_service: IndustryContextService | None = None,
    taxonomy_service: TickerTaxonomyService | None = None,
    inter_request_delay_seconds: float = DEFAULT_INTER_REQUEST_DELAY_SECONDS,
    rate_limit_backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
    max_consecutive_rate_limit_errors: int = DEFAULT_MAX_CONSECUTIVE_RATE_LIMIT_ERRORS,
    sleep_fn=time_module.sleep,
) -> dict[str, int]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    if macro_service is None or industry_service is None or taxonomy_service is None:
        built_macro_service, built_industry_service, built_taxonomy_service = build_context_services(
            session,
            newsapi_api_key=newsapi_api_key,
            news_limit=news_limit,
        )
        macro_service = macro_service or built_macro_service
        industry_service = industry_service or built_industry_service
        taxonomy_service = taxonomy_service or built_taxonomy_service

    assert macro_service is not None
    assert industry_service is not None
    assert taxonomy_service is not None

    selected_industry_keys = {key.strip().lower() for key in (industry_keys or []) if key and key.strip()}
    profiles = taxonomy_service.list_industry_profiles()
    if selected_industry_keys:
        profiles = [profile for profile in profiles if str(profile.get("subject_key", "")).lower() in selected_industry_keys]

    totals = {
        "days": 0,
        "macro_snapshots": 0,
        "industry_snapshots": 0,
        "warnings": 0,
        "rate_limit_errors": 0,
        "aborted_for_rate_limit": 0,
    }

    macro_window_hours = 24
    industry_window_hours = 24
    macro_ttl_hours = 6
    industry_ttl_hours = 8
    consecutive_rate_limit_errors = 0

    for day in iter_business_days(start_date, end_date):
        totals["days"] += 1
        as_of = datetime.combine(day, time(23, 59, 59, tzinfo=timezone.utc))
        window_start = as_of - timedelta(hours=macro_window_hours)
        logger.info("Backfilling context for %s", day.isoformat())

        macro_payload = MacroContextRefreshPayload(
            subject_key=DEFAULT_MACRO_SUBJECT_KEY,
            subject_label=DEFAULT_MACRO_SUBJECT_LABEL,
            computed_at=as_of,
            expires_at=as_of + timedelta(hours=macro_ttl_hours),
            coverage={
                "backfill": True,
                "provider": "newsapi",
                "request_mode": request_mode,
                "window_start": window_start.isoformat(),
                "window_end": as_of.isoformat(),
            },
            source_breakdown={
                "news": {"score": 0.0, "item_count": 0},
                "social": {"score": 0.0, "item_count": 0},
            },
            diagnostics={
                "backfill": True,
                "provider": "newsapi",
                "request_mode": request_mode,
            },
            summary_text="",
        )

        try:
            macro_snapshot = macro_service.create_from_refresh_payload(macro_payload, request_mode=request_mode)
            totals["macro_snapshots"] += 1
            logger.info("  macro snapshot saved (id=%s)", getattr(macro_snapshot, "id", None))
            consecutive_rate_limit_errors = 0
        except Exception as exc:  # noqa: BLE001
            totals["warnings"] += 1
            logger.exception("  failed to backfill macro context for %s: %s", day.isoformat(), exc)
            if is_rate_limit_error(exc):
                totals["rate_limit_errors"] += 1
                consecutive_rate_limit_errors += 1
                if consecutive_rate_limit_errors >= max_consecutive_rate_limit_errors:
                    totals["aborted_for_rate_limit"] = 1
                    logger.warning(
                        "Stopping backfill after %s consecutive rate-limit errors", consecutive_rate_limit_errors
                    )
                    return totals
                sleep_seconds = rate_limit_backoff_seconds * consecutive_rate_limit_errors
                logger.warning("Rate limited; backing off for %.1f seconds", sleep_seconds)
                sleep_fn(sleep_seconds)
            else:
                consecutive_rate_limit_errors = 0

        if inter_request_delay_seconds > 0:
            sleep_fn(inter_request_delay_seconds)

        for profile in profiles:
            subject_key = str(profile.get("subject_key") or "").strip()
            if not subject_key:
                continue
            subject_label = str(profile.get("subject_label") or profile.get("industry") or subject_key).strip() or subject_key
            tracked_tickers = profile.get("tickers", []) if isinstance(profile.get("tickers", []), list) else []
            query_terms = profile.get("queries", []) if isinstance(profile.get("queries", []), list) else []
            payload = IndustryContextRefreshPayload(
                subject_key=subject_key,
                subject_label=subject_label,
                computed_at=as_of,
                expires_at=as_of + timedelta(hours=industry_ttl_hours),
                coverage={
                    "backfill": True,
                    "provider": "newsapi",
                    "request_mode": request_mode,
                    "tracked_tickers": tracked_tickers,
                    "query_count": len(query_terms),
                    "window_start": (as_of - timedelta(hours=industry_window_hours)).isoformat(),
                    "window_end": as_of.isoformat(),
                },
                source_breakdown={
                    "news": {"score": 0.0, "item_count": 0},
                    "social": {"score": 0.0, "item_count": 0},
                },
                diagnostics={
                    "backfill": True,
                    "provider": "newsapi",
                    "request_mode": request_mode,
                    "queries": query_terms,
                },
                summary_text="",
            )
            try:
                industry_snapshot = industry_service.create_from_refresh_payload(payload, request_mode=request_mode)
                totals["industry_snapshots"] += 1
                logger.info("  industry snapshot saved: %s (id=%s)", subject_key, getattr(industry_snapshot, "id", None))
                consecutive_rate_limit_errors = 0
            except Exception as exc:  # noqa: BLE001
                totals["warnings"] += 1
                logger.exception("  failed to backfill industry context for %s/%s: %s", day.isoformat(), subject_key, exc)
                if is_rate_limit_error(exc):
                    totals["rate_limit_errors"] += 1
                    consecutive_rate_limit_errors += 1
                    if consecutive_rate_limit_errors >= max_consecutive_rate_limit_errors:
                        totals["aborted_for_rate_limit"] = 1
                        logger.warning(
                            "Stopping backfill after %s consecutive rate-limit errors", consecutive_rate_limit_errors
                        )
                        return totals
                    sleep_seconds = rate_limit_backoff_seconds * consecutive_rate_limit_errors
                    logger.warning("Rate limited; backing off for %.1f seconds", sleep_seconds)
                    sleep_fn(sleep_seconds)
                else:
                    consecutive_rate_limit_errors = 0
            if inter_request_delay_seconds > 0:
                sleep_fn(inter_request_delay_seconds)

    return totals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconstruct macro and industry context snapshots from historical NewsAPI data.")
    parser.add_argument(
        "--start-date",
        type=parse_date,
        help="Inclusive start date (YYYY-MM-DD or DD/MM/YYYY). Defaults to the latest completed business week.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_date,
        help="Inclusive end date (YYYY-MM-DD or DD/MM/YYYY). Defaults to the latest completed business week.",
    )
    parser.add_argument(
        "--newsapi-api-key",
        help="Override the NewsAPI key. If omitted, the script uses the stored newsapi credential or NEWSAPI_API_KEY.",
    )
    parser.add_argument(
        "--news-limit",
        type=int,
        default=DEFAULT_NEWS_LIMIT,
        help=f"Maximum articles per NewsAPI query (default: {DEFAULT_NEWS_LIMIT}).",
    )
    parser.add_argument(
        "--request-mode",
        choices=("live", "replay"),
        default=DEFAULT_REQUEST_MODE,
        help="News request mode passed to the context builders (default: replay).",
    )
    parser.add_argument(
        "--industry-key",
        action="append",
        dest="industry_keys",
        help="Optional industry key to limit the backfill scope. Repeatable.",
    )
    parser.add_argument(
        "--inter-request-delay-seconds",
        type=float,
        default=DEFAULT_INTER_REQUEST_DELAY_SECONDS,
        help=f"Sleep between snapshot attempts to reduce burst rate (default: {DEFAULT_INTER_REQUEST_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--rate-limit-backoff-seconds",
        type=float,
        default=DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
        help=f"Base backoff applied after each rate-limit error (default: {DEFAULT_RATE_LIMIT_BACKOFF_SECONDS}).",
    )
    parser.add_argument(
        "--max-consecutive-rate-limit-errors",
        type=int,
        default=DEFAULT_MAX_CONSECUTIVE_RATE_LIMIT_ERRORS,
        help=f"Abort the backfill after this many consecutive rate-limit errors (default: {DEFAULT_MAX_CONSECUTIVE_RATE_LIMIT_ERRORS}).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    start_date = args.start_date
    end_date = args.end_date
    if (start_date is None) != (end_date is None):
        parser.error("--start-date and --end-date must be provided together")
    if start_date is None or end_date is None:
        start_date, end_date = default_backfill_range()

    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    logger.info("Using database URL: %s", db_url)
    logger.info("Backfill window: %s -> %s", start_date.isoformat(), end_date.isoformat())
    engine = create_engine(db_url, future=True)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    try:
        with SessionFactory() as session:
            totals = run_context_backfill(
                session,
                start_date,
                end_date,
                request_mode=args.request_mode,
                newsapi_api_key=args.newsapi_api_key,
                news_limit=args.news_limit,
                industry_keys=args.industry_keys,
                inter_request_delay_seconds=args.inter_request_delay_seconds,
                rate_limit_backoff_seconds=args.rate_limit_backoff_seconds,
                max_consecutive_rate_limit_errors=args.max_consecutive_rate_limit_errors,
            )
            logger.info(
                "Backfill complete: days=%s macro_snapshots=%s industry_snapshots=%s warnings=%s rate_limit_errors=%s aborted_for_rate_limit=%s",
                totals["days"],
                totals["macro_snapshots"],
                totals["industry_snapshots"],
                totals["warnings"],
                totals["rate_limit_errors"],
                totals["aborted_for_rate_limit"],
            )
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
