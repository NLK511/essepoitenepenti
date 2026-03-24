from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.snapshot_summary import SnapshotSummaryContext, build_snapshot_summary

MACRO_SUBJECT_KEY = "global_macro"
MACRO_SUBJECT_LABEL = "Global Macro"
MACRO_TTL_HOURS = 6
MACRO_QUERIES = [
    "fed",
    "inflation",
    "treasury yields",
    "oil",
    "recession",
    "risk off",
    "european monetary policy",
    "ecb",
    "european central bank",
    "eurozone rates",
    "war",
    "military tensions",
    "geopolitical tensions",
]


class MacroSentimentService:
    def __init__(
        self,
        repository: SentimentSnapshotRepository,
        *,
        social_service: SocialIngestionService | None = None,
        news_service: NewsIngestionService | None = None,
    ) -> None:
        self.repository = repository
        self.social_service = social_service
        self.news_service = news_service

    def refresh(self, *, job_id: int | None = None, run_id: int | None = None) -> dict[str, Any]:
        previous_snapshot = self.repository.get_latest_snapshot("macro", MACRO_SUBJECT_KEY)
        social_result = (
            self.social_service.analyze_subject(
                subject_key=MACRO_SUBJECT_KEY,
                subject_label=MACRO_SUBJECT_LABEL,
                queries=MACRO_QUERIES,
                scope_tag="macro",
            )
            if self.social_service is not None
            else {"sentiment": {}, "bundle": None}
        )
        social_sentiment = social_result.get("sentiment", {})
        social_score = float(social_sentiment.get("score", 0.0) or 0.0)
        social_count = int(social_sentiment.get("item_count", 0) or 0)

        score = social_score
        label = social_sentiment.get("label") or "NEUTRAL"
        coverage = {
            "social_count": social_count,
            "news_count": 0,
            "ttl_hours": MACRO_TTL_HOURS,
        }
        source_breakdown = {
            "news": {"score": 0.0, "item_count": 0},
            "social": {"score": social_score, "item_count": social_count},
        }
        drivers: list[str] = []
        if social_count == 0:
            drivers.append("macro refresh completed without social macro matches; snapshot is neutral unless other providers are added")
        bundle = social_result.get("bundle")
        diagnostics = {
            "warnings": social_sentiment.get("coverage_insights", []),
            "providers": (getattr(bundle, "feeds_used", []) if bundle is not None else []),
            "query_diagnostics": (getattr(bundle, "query_diagnostics", {}) if bundle is not None else {}),
        }
        summary_text = build_snapshot_summary(
            SnapshotSummaryContext(
                scope="macro",
                subject_label=MACRO_SUBJECT_LABEL,
                score=score,
                label=label,
                drivers=drivers,
                coverage_insights=list(social_sentiment.get("coverage_insights", [])),
                previous_snapshot=previous_snapshot,
            )
        )
        computed_at = datetime.now(timezone.utc)
        expires_at = computed_at + timedelta(hours=MACRO_TTL_HOURS)
        snapshot = self.repository.create_snapshot(
            scope="macro",
            subject_key=MACRO_SUBJECT_KEY,
            subject_label=MACRO_SUBJECT_LABEL,
            score=score,
            label=label,
            computed_at=computed_at,
            expires_at=expires_at,
            coverage=coverage,
            source_breakdown=source_breakdown,
            drivers=drivers,
            signals={
                "social_items": social_sentiment.get("items", []),
                "scope_breakdown": social_sentiment.get("scope_breakdown", {}),
            },
            diagnostics=diagnostics,
            summary_text=summary_text,
            job_id=job_id,
            run_id=run_id,
        )
        return {
            "snapshot": snapshot,
            "summary": {
                "scope": "macro",
                "subject_key": MACRO_SUBJECT_KEY,
                "subject_label": MACRO_SUBJECT_LABEL,
                "score": score,
                "label": label,
                "summary_text": summary_text,
                "previous_snapshot_id": previous_snapshot.id if previous_snapshot is not None else None,
                "expires_at": expires_at.isoformat(),
            },
        }
