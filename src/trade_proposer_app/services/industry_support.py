from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from trade_proposer_app.domain.models import SupportSnapshot
import json
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService

INDUSTRY_TTL_HOURS = 8


class IndustrySupportRefreshService:
    def __init__(
        self,
        *,
        social_service: SocialIngestionService | None = None,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.social_service = social_service
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def refresh_all(self, *, job_id: int | None = None, run_id: int | None = None) -> list[SupportSnapshot]:
        snapshots = []
        for profile in self.taxonomy_service.list_industry_profiles():
            snapshot = self.refresh_industry(
                subject_key=profile["subject_key"],
                subject_label=profile["subject_label"],
                queries=profile.get("queries", []),
                tickers=profile.get("tickers", []),
                job_id=job_id,
                run_id=run_id,
            )
            snapshots.append(snapshot)
        return snapshots

    def refresh_industry(
        self,
        *,
        subject_key: str,
        subject_label: str,
        queries: list[str],
        tickers: list[str] | None = None,
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> SupportSnapshot:
        social_result = (
            self.social_service.analyze_subject(
                subject_key=subject_key,
                subject_label=subject_label,
                queries=queries or [subject_label],
                scope_tag="industry",
            )
            if self.social_service is not None
            else {"sentiment": {}, "bundle": None}
        )
        social_sentiment = social_result.get("sentiment", {})
        social_score = float(social_sentiment.get("score", 0.0) or 0.0)
        social_count = int(social_sentiment.get("item_count", 0) or 0)
        bundle = social_result.get("bundle")

        score = social_score
        label = social_sentiment.get("label") or "NEUTRAL"
        computed_at = datetime.now(timezone.utc)
        expires_at = computed_at + timedelta(hours=INDUSTRY_TTL_HOURS)

        snapshot = SupportSnapshot(
            scope="industry",
            subject_key=subject_key,
            subject_label=subject_label,
            score=score,
            label=label,
            computed_at=computed_at,
            expires_at=expires_at,
            coverage_json=json.dumps({
                "social_count": social_count,
                "news_count": 0,
                "ttl_hours": INDUSTRY_TTL_HOURS,
                "tracked_tickers": tickers or [],
                "query_count": len(queries or []),
            }),
            source_breakdown_json=json.dumps({
                "news": {"score": 0.0, "item_count": 0},
                "social": {"score": social_score, "item_count": social_count},
            }),
            drivers_json=json.dumps([]),
            signals_json=json.dumps({
                "social_items": social_sentiment.get("items", []),
                "scope_breakdown": social_sentiment.get("scope_breakdown", {}),
            }),
            diagnostics_json=json.dumps({
                "warnings": social_sentiment.get("coverage_insights", []),
                "providers": (getattr(bundle, "feeds_used", []) if bundle is not None else []),
                "query_diagnostics": (getattr(bundle, "query_diagnostics", {}) if bundle is not None else {}),
                "queries": queries or [subject_label],
            }),
            summary_text="",
            job_id=job_id,
            run_id=run_id,
        )
        return snapshot


IndustrySupportRefreshService = IndustrySupportRefreshService
