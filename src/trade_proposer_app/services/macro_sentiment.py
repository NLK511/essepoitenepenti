from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.social import SocialIngestionService

MACRO_SUBJECT_KEY = "global_macro"
MACRO_SUBJECT_LABEL = "Global Macro"
MACRO_TTL_HOURS = 6


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
        social_result = self.social_service.analyze_subject(
            subject_key=MACRO_SUBJECT_KEY,
            subject_label=MACRO_SUBJECT_LABEL,
            queries=["fed", "inflation", "treasury yields", "oil", "recession", "risk off"],
            scope_tag="macro",
        ) if self.social_service is not None else {"sentiment": {}, "bundle": None}
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
        drivers = []
        if social_count == 0:
            drivers.append("macro refresh completed without social macro matches; snapshot is neutral unless other providers are added")
        diagnostics = {
            "warnings": social_sentiment.get("coverage_insights", []),
            "providers": (social_result.get("bundle").feeds_used if social_result.get("bundle") is not None else []),
        }
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
                "expires_at": expires_at.isoformat(),
            },
        }
