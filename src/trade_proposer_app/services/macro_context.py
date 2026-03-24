from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import MacroContextSnapshot, SentimentSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.services.news import NewsIngestionService

MACRO_THEME_MAP: dict[str, tuple[str, list[str], list[str]]] = {
    "us_monetary_policy": (
        "U.S. monetary policy",
        ["fed", "fomc", "powell", "rate cut", "rate hike", "policy easing", "policy tightening"],
        ["rates", "policy"],
    ),
    "inflation": (
        "Inflation",
        ["inflation", "cpi", "ppi", "sticky prices", "disinflation"],
        ["inflation"],
    ),
    "bond_yields": (
        "Bond yields",
        ["yield", "treasury", "10-year", "2-year", "bond market"],
        ["rates", "yield_pressure"],
    ),
    "energy_oil": (
        "Oil and energy",
        ["oil", "crude", "opec", "energy prices", "brent", "wti"],
        ["commodities"],
    ),
    "growth_recession": (
        "Growth and recession risk",
        ["recession", "slowdown", "growth scare", "soft landing", "hard landing"],
        ["growth"],
    ),
    "risk_off": (
        "Risk-off tone",
        ["risk off", "flight to safety", "selloff", "defensive"],
        ["risk_off"],
    ),
    "european_monetary_policy": (
        "European monetary policy",
        ["ecb", "european central bank", "eurozone rates", "european monetary policy", "lagarde"],
        ["europe", "rates"],
    ),
    "geopolitics": (
        "Geopolitical risk",
        ["war", "military tensions", "geopolitical tensions", "missile", "sanctions", "conflict"],
        ["geopolitics", "risk_off"],
    ),
}

DEFAULT_MACRO_NEWS_QUERIES = [
    "Federal Reserve OR FOMC OR Powell",
    "inflation OR CPI OR PPI",
    "Treasury yields OR bond market",
    "ECB OR eurozone rates OR Lagarde",
    "war OR sanctions OR geopolitical tensions OR oil",
]


class MacroContextService:
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
    ) -> MacroContextSnapshot:
        previous = self.repository.get_latest_macro_context_snapshot()
        signals = _load_json(getattr(snapshot, "signals_json", None), {})
        diagnostics = _load_json(getattr(snapshot, "diagnostics_json", None), {})
        source_breakdown = _load_json(getattr(snapshot, "source_breakdown_json", None), {})
        social_items = signals.get("social_items") if isinstance(signals, dict) else []
        supporting_social_items = social_items if isinstance(social_items, list) else []

        news_bundle, news_sentiment = self._load_news_evidence()
        primary_news_items = news_sentiment.get("news_items", []) if isinstance(news_sentiment, dict) else []
        news_items = primary_news_items if isinstance(primary_news_items, list) else []

        active_themes = self._extract_themes(news_items, supporting_social_items)
        warnings: list[str] = []
        missing_inputs: list[str] = []
        feed_errors = list(news_bundle.feed_errors) if news_bundle is not None else []

        if not news_items:
            warnings.append("macro context was built without primary news evidence; social evidence was used only as a secondary fallback")
            missing_inputs.append("primary_news_evidence")
        if feed_errors:
            warnings.append("macro context primary-news ingestion reported provider issues")
        if not supporting_social_items:
            missing_inputs.append("supporting_social_evidence")

        sentiment_score = float(getattr(snapshot, "score", 0.0) or 0.0)
        sentiment_label = str(getattr(snapshot, "label", "NEUTRAL") or "NEUTRAL")
        regime_tags = self._regime_tags(active_themes, sentiment_score, sentiment_label)
        saliency_score = self._saliency_score(active_themes, len(news_items), len(supporting_social_items), abs(sentiment_score))
        confidence_percent = self._confidence_percent(active_themes, len(news_items), len(supporting_social_items), diagnostics, feed_errors)
        summary_text = self._summary_text(previous, active_themes, news_items, supporting_social_items, warnings)
        status = "warning" if warnings else "ok"

        context = MacroContextSnapshot(
            computed_at=datetime.now(timezone.utc),
            status=status,
            summary_text=summary_text,
            saliency_score=saliency_score,
            confidence_percent=confidence_percent,
            active_themes=active_themes,
            regime_tags=regime_tags,
            warnings=list(dict.fromkeys(warnings)),
            missing_inputs=list(dict.fromkeys(missing_inputs)),
            source_breakdown={
                "sentiment_snapshot_id": getattr(snapshot, "id", None),
                "sentiment_label": sentiment_label,
                "sentiment_score": sentiment_score,
                "primary_news_item_count": len(news_items),
                "supporting_social_item_count": len(supporting_social_items),
                "primary_news_providers": list(dict.fromkeys(news_bundle.feeds_used)) if news_bundle is not None else [],
                "primary_news_feed_errors": feed_errors,
                "upstream": source_breakdown if isinstance(source_breakdown, dict) else {},
            },
            metadata={
                "subject_key": getattr(snapshot, "subject_key", None),
                "subject_label": getattr(snapshot, "subject_label", None),
                "query_diagnostics": diagnostics.get("query_diagnostics", {}) if isinstance(diagnostics, dict) else {},
                "news_coverage_insights": news_sentiment.get("coverage_insights", []) if isinstance(news_sentiment, dict) else [],
                "top_news_titles": [self._item_text(item)[:140] for item in news_items[:5]],
                "top_social_titles": [self._item_text(item)[:140] for item in supporting_social_items[:5]],
                "news_queries": list(DEFAULT_MACRO_NEWS_QUERIES),
            },
            run_id=run_id,
            job_id=job_id,
        )
        return self.repository.create_macro_context_snapshot(context)

    def _load_news_evidence(self) -> tuple[object | None, dict[str, object]]:
        if self.news_service is None:
            return None, {}
        bundle = self.news_service.fetch_topics("Global Macro", DEFAULT_MACRO_NEWS_QUERIES)
        analyzed = self.news_service.analyze_bundle(bundle)
        sentiment = analyzed.get("sentiment", {}) if isinstance(analyzed, dict) else {}
        return bundle, sentiment if isinstance(sentiment, dict) else {}

    def _extract_themes(self, news_items: list[object], social_items: list[object]) -> list[dict[str, object]]:
        themes: list[dict[str, object]] = []
        for key, (label, phrases, regime_tags) in MACRO_THEME_MAP.items():
            news_hits, news_samples = self._evidence_hits(news_items, phrases)
            social_hits, social_samples = self._evidence_hits(social_items, phrases)
            total_hits = (news_hits * 2) + social_hits
            if total_hits == 0:
                continue
            evidence_samples = news_samples + [sample for sample in social_samples if sample not in news_samples]
            themes.append(
                {
                    "key": key,
                    "label": label,
                    "news_evidence_count": news_hits,
                    "social_evidence_count": social_hits,
                    "evidence_count": total_hits,
                    "saliency_weight": round(min(1.0, 0.25 + (news_hits * 0.18) + (social_hits * 0.08)), 3),
                    "regime_tags": regime_tags,
                    "evidence_samples": evidence_samples[:4],
                }
            )
        themes.sort(
            key=lambda item: (
                int(item.get("news_evidence_count", 0)),
                int(item.get("social_evidence_count", 0)),
                float(item.get("saliency_weight", 0.0)),
            ),
            reverse=True,
        )
        return themes[:5]

    def _evidence_hits(self, items: list[object], phrases: list[str]) -> tuple[int, list[str]]:
        hit_count = 0
        evidence: list[str] = []
        for raw_item in items:
            text = self._item_text(raw_item).lower()
            if not text:
                continue
            if any(phrase in text for phrase in phrases):
                hit_count += 1
                sample = self._item_text(raw_item)[:160]
                if sample and sample not in evidence and len(evidence) < 3:
                    evidence.append(sample)
        return hit_count, evidence

    def _regime_tags(self, active_themes: list[dict[str, object]], score: float, label: str) -> list[str]:
        tags: list[str] = []
        for theme in active_themes:
            raw_tags = theme.get("regime_tags")
            if isinstance(raw_tags, list):
                for tag in raw_tags:
                    if isinstance(tag, str):
                        tags.append(tag)
        if label == "NEGATIVE" and "risk_off" not in tags:
            tags.append("risk_off")
        if score > 0.15:
            tags.append("risk_on")
        return list(dict.fromkeys(tags))

    @staticmethod
    def _saliency_score(
        active_themes: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        sentiment_magnitude: float,
    ) -> float:
        score = 0.12 + (len(active_themes) * 0.14) + (min(news_item_count, 6) * 0.07) + (min(social_item_count, 4) * 0.03) + (sentiment_magnitude * 0.15)
        return round(min(1.0, score), 3)

    @staticmethod
    def _confidence_percent(
        active_themes: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        diagnostics: dict[str, object],
        feed_errors: list[str],
    ) -> float:
        social_provider_count = len(diagnostics.get("providers", [])) if isinstance(diagnostics, dict) and isinstance(diagnostics.get("providers"), list) else 0
        confidence = 24.0 + (len(active_themes) * 9.0) + (min(news_item_count, 6) * 7.0) + (min(social_item_count, 4) * 2.5) + (social_provider_count * 2.0)
        if news_item_count == 0:
            confidence -= 18.0
        if feed_errors:
            confidence -= min(12.0, len(feed_errors) * 4.0)
        return round(max(5.0, min(92.0, confidence)), 1)

    @staticmethod
    def _summary_text(
        previous: MacroContextSnapshot | None,
        active_themes: list[dict[str, object]],
        news_items: list[object],
        social_items: list[object],
        warnings: list[str],
    ) -> str:
        theme_labels = [str(item.get("label", "")).strip() for item in active_themes if item.get("label")]
        focus = ", ".join(theme_labels[:2]) if theme_labels else "no dominant macro theme"
        if previous and previous.summary_text and theme_labels:
            return f"Backdrop stays centered on {focus}. This run is now anchored mainly by primary news evidence, with social evidence used for secondary confirmation."
        if theme_labels and news_items:
            return f"Macro context is currently led by {focus}, with primary news evidence carrying most of the saliency signal in this run."
        if theme_labels and social_items:
            return f"Macro context points to {focus}, but primary-news evidence was thin so the run leans more on social confirmation than desired."
        if warnings:
            return "Macro context evidence is light in this run, so the output is mainly a continuity placeholder rather than a strong regime call."
        return "Macro context remains mixed without one clearly dominant theme."

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
