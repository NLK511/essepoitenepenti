from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import IndustryContextSnapshot, SentimentSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.services.news import NewsIngestionService

MACRO_LINK_THEME_MAP: dict[str, str] = {
    "inflation": "inflation",
    "rate": "rates",
    "yield": "yield_pressure",
    "oil": "energy_costs",
    "war": "geopolitics",
    "geopolitical": "geopolitics",
    "tariff": "trade_policy",
    "recession": "growth_risk",
}

INDUSTRY_THEME_MAP: dict[str, str] = {
    "conference": "conference_cycle",
    "guidance": "guidance",
    "pricing": "pricing",
    "demand": "demand",
    "backlog": "backlog",
    "innovation": "innovation",
    "launch": "product_cycle",
    "product": "product_cycle",
    "regulation": "regulation",
    "approval": "regulation",
    "supply chain": "supply_chain",
    "inventory": "inventory",
    "ai": "ai_theme",
    "chip": "semiconductor_theme",
    "cloud": "cloud_theme",
}


class IndustryContextService:
    def __init__(
        self,
        repository: ContextSnapshotRepository,
        *,
        news_service: NewsIngestionService | None = None,
    ) -> None:
        self.repository = repository
        self.news_service = news_service

    def create_from_sentiment_snapshot(
        self,
        snapshot: SentimentSnapshot,
        *,
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> IndustryContextSnapshot:
        industry_key = str(getattr(snapshot, "subject_key", "") or "")
        industry_label = str(getattr(snapshot, "subject_label", "") or industry_key)
        previous = self.repository.get_latest_industry_context_snapshot(industry_key)
        signals = _load_json(getattr(snapshot, "signals_json", None), {})
        diagnostics = _load_json(getattr(snapshot, "diagnostics_json", None), {})
        source_breakdown = _load_json(getattr(snapshot, "source_breakdown_json", None), {})
        coverage = _load_json(getattr(snapshot, "coverage_json", None), {})
        social_items = signals.get("social_items") if isinstance(signals, dict) else []
        supporting_social_items = social_items if isinstance(social_items, list) else []
        tracked_tickers = coverage.get("tracked_tickers", []) if isinstance(coverage, dict) else []
        query_terms = diagnostics.get("queries", []) if isinstance(diagnostics, dict) else []

        news_bundle, news_sentiment = self._load_news_evidence(industry_label, tracked_tickers, query_terms)
        primary_news_items = news_sentiment.get("news_items", []) if isinstance(news_sentiment, dict) else []
        news_items = primary_news_items if isinstance(primary_news_items, list) else []

        active_drivers = self._extract_active_drivers(news_items, supporting_social_items)
        linked_macro_themes = self._linked_macro_themes(news_items, supporting_social_items)
        linked_industry_themes = self._linked_industry_themes(active_drivers)
        feed_errors = list(news_bundle.feed_errors) if news_bundle is not None else []

        warnings: list[str] = []
        missing_inputs: list[str] = []
        if not news_items:
            warnings.append(f"industry context for {industry_label} was built without primary industry news evidence; social evidence was used only as a secondary fallback")
            missing_inputs.append("primary_industry_news_evidence")
        if feed_errors:
            warnings.append(f"industry context for {industry_label} encountered provider issues while gathering primary-news evidence")
        if not supporting_social_items:
            missing_inputs.append("supporting_social_evidence")

        saliency_score = self._saliency_score(active_drivers, len(news_items), len(supporting_social_items), len(linked_macro_themes))
        confidence_percent = self._confidence_percent(active_drivers, len(news_items), len(supporting_social_items), diagnostics, feed_errors)
        summary_text = self._summary_text(previous, industry_label, active_drivers, linked_macro_themes, news_items, supporting_social_items)
        context = IndustryContextSnapshot(
            industry_key=industry_key,
            industry_label=industry_label,
            computed_at=datetime.now(timezone.utc),
            status="warning" if warnings else "ok",
            summary_text=summary_text,
            direction=self._direction_from_label(str(getattr(snapshot, "label", "NEUTRAL") or "NEUTRAL")),
            saliency_score=saliency_score,
            confidence_percent=confidence_percent,
            active_drivers=active_drivers,
            linked_macro_themes=linked_macro_themes,
            linked_industry_themes=linked_industry_themes,
            warnings=list(dict.fromkeys(warnings)),
            missing_inputs=list(dict.fromkeys(missing_inputs)),
            source_breakdown={
                "sentiment_snapshot_id": getattr(snapshot, "id", None),
                "sentiment_label": getattr(snapshot, "label", None),
                "sentiment_score": getattr(snapshot, "score", None),
                "primary_news_item_count": len(news_items),
                "supporting_social_item_count": len(supporting_social_items),
                "tracked_tickers": tracked_tickers,
                "primary_news_providers": list(dict.fromkeys(news_bundle.feeds_used)) if news_bundle is not None else [],
                "primary_news_feed_errors": feed_errors,
                "upstream": source_breakdown if isinstance(source_breakdown, dict) else {},
            },
            metadata={
                "query_diagnostics": diagnostics.get("query_diagnostics", {}) if isinstance(diagnostics, dict) else {},
                "queries": query_terms,
                "news_coverage_insights": news_sentiment.get("coverage_insights", []) if isinstance(news_sentiment, dict) else [],
                "top_news_titles": [self._item_text(item)[:140] for item in news_items[:5]],
                "top_social_titles": [self._item_text(item)[:140] for item in supporting_social_items[:5]],
            },
            run_id=run_id,
            job_id=job_id,
        )
        return self.repository.create_industry_context_snapshot(context)

    def _load_news_evidence(
        self,
        industry_label: str,
        tracked_tickers: list[object],
        query_terms: list[object],
    ) -> tuple[object | None, dict[str, object]]:
        if self.news_service is None:
            return None, {}
        normalized_tickers = [str(ticker).strip().upper() for ticker in tracked_tickers if str(ticker).strip()]
        if normalized_tickers:
            bundle = self.news_service.fetch_many(normalized_tickers, per_symbol_limit=3)
        else:
            queries = [str(query).strip() for query in query_terms if str(query).strip()]
            bundle = self.news_service.fetch_topics(industry_label, queries or [industry_label], per_query_limit=3)
        analyzed = self.news_service.analyze_bundle(bundle)
        sentiment = analyzed.get("sentiment", {}) if isinstance(analyzed, dict) else {}
        return bundle, sentiment if isinstance(sentiment, dict) else {}

    def _extract_active_drivers(self, news_items: list[object], social_items: list[object]) -> list[dict[str, object]]:
        counts: dict[str, dict[str, object]] = {}
        self._accumulate_driver_hits(counts, news_items, source="news")
        self._accumulate_driver_hits(counts, social_items, source="social")
        results = []
        for key, payload in counts.items():
            results.append(
                {
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "news_evidence_count": payload.get("news_evidence_count", 0),
                    "social_evidence_count": payload.get("social_evidence_count", 0),
                    "evidence_count": (int(payload.get("news_evidence_count", 0)) * 2) + int(payload.get("social_evidence_count", 0)),
                    "evidence_samples": payload.get("evidence_samples", []),
                }
            )
        results.sort(
            key=lambda item: (
                int(item.get("news_evidence_count", 0)),
                int(item.get("social_evidence_count", 0)),
                int(item.get("evidence_count", 0)),
            ),
            reverse=True,
        )
        return results[:5]

    def _accumulate_driver_hits(self, counts: dict[str, dict[str, object]], items: list[object], *, source: str) -> None:
        for raw_item in items:
            text = self._item_text(raw_item).lower()
            if not text:
                continue
            matched: set[str] = set()
            for phrase, key in INDUSTRY_THEME_MAP.items():
                if phrase in text:
                    matched.add(key)
            for key in matched:
                entry = counts.setdefault(
                    key,
                    {
                        "key": key,
                        "news_evidence_count": 0,
                        "social_evidence_count": 0,
                        "evidence_samples": [],
                    },
                )
                counter_key = "news_evidence_count" if source == "news" else "social_evidence_count"
                entry[counter_key] = int(entry[counter_key]) + 1
                sample = self._item_text(raw_item)[:160]
                samples = entry["evidence_samples"]
                if sample and isinstance(samples, list) and sample not in samples and len(samples) < 4:
                    samples.append(sample)

    def _linked_macro_themes(self, news_items: list[object], social_items: list[object]) -> list[str]:
        linked: list[str] = []
        for raw_item in [*news_items, *social_items]:
            text = self._item_text(raw_item).lower()
            if not text:
                continue
            for phrase, key in MACRO_LINK_THEME_MAP.items():
                if phrase in text:
                    linked.append(key)
        return list(dict.fromkeys(linked))[:5]

    @staticmethod
    def _linked_industry_themes(active_drivers: list[dict[str, object]]) -> list[str]:
        return [str(item.get("key")) for item in active_drivers if item.get("key")]

    @staticmethod
    def _direction_from_label(label: str) -> str:
        normalized = (label or "").strip().upper()
        if normalized == "POSITIVE":
            return "positive"
        if normalized == "NEGATIVE":
            return "negative"
        return "neutral"

    @staticmethod
    def _saliency_score(active_drivers: list[dict[str, object]], news_item_count: int, social_item_count: int, macro_link_count: int) -> float:
        score = 0.14 + (len(active_drivers) * 0.13) + (min(news_item_count, 6) * 0.07) + (min(social_item_count, 4) * 0.025) + (macro_link_count * 0.05)
        return round(min(1.0, score), 3)

    @staticmethod
    def _confidence_percent(
        active_drivers: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        diagnostics: dict[str, object],
        feed_errors: list[str],
    ) -> float:
        social_provider_count = len(diagnostics.get("providers", [])) if isinstance(diagnostics, dict) and isinstance(diagnostics.get("providers"), list) else 0
        confidence = 26.0 + (len(active_drivers) * 8.0) + (min(news_item_count, 6) * 7.0) + (min(social_item_count, 4) * 2.0) + (social_provider_count * 2.0)
        if news_item_count == 0:
            confidence -= 18.0
        if feed_errors:
            confidence -= min(12.0, len(feed_errors) * 4.0)
        return round(max(5.0, min(92.0, confidence)), 1)

    @staticmethod
    def _summary_text(
        previous: IndustryContextSnapshot | None,
        industry_label: str,
        active_drivers: list[dict[str, object]],
        linked_macro_themes: list[str],
        news_items: list[object],
        social_items: list[object],
    ) -> str:
        driver_labels = [str(item.get("label", "")).strip() for item in active_drivers if item.get("label")]
        focus = ", ".join(driver_labels[:2]) if driver_labels else "no dominant industry-native driver"
        macro = ", ".join(linked_macro_themes[:2]) if linked_macro_themes else "limited visible macro transmission"
        if previous and previous.summary_text and driver_labels and news_items:
            return f"{industry_label} remains driven by {focus}, with macro read-through still centered on {macro} and primary industry news carrying most of the evidence in this run."
        if driver_labels and news_items:
            return f"{industry_label} context is led by {focus}, while macro transmission points to {macro}; primary industry news is the main evidence layer in this run."
        if driver_labels and social_items:
            return f"{industry_label} context still points to {focus}, but primary industry news was thin so the run leans more on social confirmation than desired."
        if previous and previous.summary_text:
            return f"{industry_label} context is broadly unchanged, but this run did not surface a clearly dominant fresh driver."
        return f"{industry_label} context is currently light on salient evidence, so the output mainly records continuity and known macro links."

    @staticmethod
    def _item_text(raw_item: object) -> str:
        if not isinstance(raw_item, dict):
            return ""
        title = raw_item.get("title")
        body = raw_item.get("body")
        summary = raw_item.get("summary")
        parts = [part.strip() for part in [title, body, summary] if isinstance(part, str) and part.strip()]
        return " — ".join(parts)



def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
