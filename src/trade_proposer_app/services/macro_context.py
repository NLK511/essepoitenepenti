from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import MacroContextSnapshot, SentimentSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.services.event_extraction import (
    EventDefinition,
    count_events_above_saliency,
    coverage_quality_label,
    extract_event_tags,
    extract_ranked_events,
    publisher_summary,
    source_priority_counts,
    summarize_event_lifecycle,
    summarize_event_scores,
    summarize_source_priorities,
    top_event_labels,
)
from trade_proposer_app.services.news import NewsIngestionService

MACRO_THEME_DEFINITIONS = [
    EventDefinition(
        key="us_monetary_policy",
        label="U.S. monetary policy",
        phrases=("fed", "fomc", "powell", "rate cut", "rate hike", "policy easing", "policy tightening"),
        tags=("rates", "policy"),
        category="policy",
        window_hint="1w_plus",
        transmission_channels=("rates", "valuation_duration", "funding_costs"),
        beneficiary_tags=("financials",),
        loser_tags=("long_duration", "rate_sensitive"),
    ),
    EventDefinition(
        key="inflation",
        label="Inflation",
        phrases=("inflation", "cpi", "ppi", "sticky prices", "disinflation"),
        tags=("inflation",),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("input_costs", "rates", "consumer_pressure"),
        beneficiary_tags=("pricing_power",),
        loser_tags=("margin_pressure",),
    ),
    EventDefinition(
        key="bond_yields",
        label="Bond yields",
        phrases=("yield", "treasury", "10-year", "2-year", "bond market"),
        tags=("rates", "yield_pressure"),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("rates", "valuation_duration", "funding_costs"),
        beneficiary_tags=("financials",),
        loser_tags=("long_duration",),
    ),
    EventDefinition(
        key="energy_oil",
        label="Oil and energy",
        phrases=("oil", "crude", "opec", "energy prices", "brent", "wti"),
        tags=("commodities",),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("commodity_input_costs", "energy_revenue", "transport_costs"),
        beneficiary_tags=("energy",),
        loser_tags=("airlines", "chemicals", "consumer"),
    ),
    EventDefinition(
        key="growth_recession",
        label="Growth and recession risk",
        phrases=("recession", "slowdown", "growth scare", "soft landing", "hard landing"),
        tags=("growth",),
        category="macro",
        window_hint="1w_plus",
        transmission_channels=("cyclical_demand", "credit_risk", "beta"),
        beneficiary_tags=("defensive",),
        loser_tags=("cyclical",),
    ),
    EventDefinition(
        key="risk_off",
        label="Risk-off tone",
        phrases=("risk off", "flight to safety", "selloff", "defensive"),
        tags=("risk_off",),
        category="market_regime",
        window_hint="1d",
        transmission_channels=("risk_appetite", "beta", "liquidity"),
        beneficiary_tags=("defensive",),
        loser_tags=("high_beta",),
    ),
    EventDefinition(
        key="european_monetary_policy",
        label="European monetary policy",
        phrases=("ecb", "european central bank", "eurozone rates", "european monetary policy", "lagarde"),
        tags=("europe", "rates"),
        category="policy",
        window_hint="1w_plus",
        transmission_channels=("euro_rates", "european_demand", "funding_costs"),
        beneficiary_tags=("euro_banks",),
        loser_tags=("real_estate", "euro_cyclicals"),
    ),
    EventDefinition(
        key="geopolitics",
        label="Geopolitical risk",
        phrases=("war", "military tensions", "geopolitical tensions", "missile", "sanctions", "conflict"),
        tags=("geopolitics", "risk_off"),
        category="macro_shock",
        window_hint="1d",
        transmission_channels=("commodity_risk", "supply_chain", "risk_appetite"),
        beneficiary_tags=("defense", "energy"),
        loser_tags=("travel", "global_supply_chain"),
    ),
]

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

        previous_events = previous.active_themes if previous is not None else []
        active_themes = extract_ranked_events(
            news_items,
            supporting_social_items,
            MACRO_THEME_DEFINITIONS,
            previous_events=previous_events,
            max_events=5,
        )
        lifecycle_summary = summarize_event_lifecycle(active_themes, previous_events=previous_events)
        warnings: list[str] = []
        missing_inputs: list[str] = []
        feed_errors = list(news_bundle.feed_errors) if news_bundle is not None else []
        primary_source_counts = source_priority_counts(news_items, source_type="news")
        primary_coverage_quality = coverage_quality_label(news_items, source_type="news")
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))

        if not news_items:
            warnings.append("macro context was built without primary news evidence; social evidence was used only as a secondary fallback")
            missing_inputs.append("primary_news_evidence")
        elif primary_coverage_quality == "low":
            warnings.append("macro context primary-news evidence lacks official or major-source coverage, so saliency confidence is capped")
        if feed_errors:
            warnings.append("macro context primary-news ingestion reported provider issues")
        if contradiction_labels:
            warnings.append("macro context contains contradictory evidence across active events")
        if not supporting_social_items:
            missing_inputs.append("supporting_social_evidence")

        sentiment_score = float(getattr(snapshot, "score", 0.0) or 0.0)
        sentiment_label = str(getattr(snapshot, "label", "NEUTRAL") or "NEUTRAL")
        regime_tags = self._regime_tags(active_themes, sentiment_score, sentiment_label)
        saliency_score = self._saliency_score(active_themes, len(news_items), len(supporting_social_items), abs(sentiment_score), primary_source_counts)
        confidence_percent = self._confidence_percent(
            active_themes,
            len(news_items),
            len(supporting_social_items),
            diagnostics,
            feed_errors,
            primary_source_counts,
            contradiction_count=int(lifecycle_summary.get("contradiction_count", 0) or 0),
        )
        summary_text = self._summary_text(previous, active_themes, lifecycle_summary, news_items, supporting_social_items, warnings)
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
                "primary_news_source_priorities": summarize_source_priorities(news_items, source_type="news"),
                "primary_news_publishers": publisher_summary(news_items),
                "primary_news_coverage_quality": primary_coverage_quality,
                "upstream": source_breakdown if isinstance(source_breakdown, dict) else {},
            },
            metadata={
                "subject_key": getattr(snapshot, "subject_key", None),
                "subject_label": getattr(snapshot, "subject_label", None),
                "query_diagnostics": diagnostics.get("query_diagnostics", {}) if isinstance(diagnostics, dict) else {},
                "news_coverage_insights": news_sentiment.get("coverage_insights", []) if isinstance(news_sentiment, dict) else [],
                "top_news_titles": [self._item_text(item)[:140] for item in news_items[:5]],
                "top_social_titles": [self._item_text(item)[:140] for item in supporting_social_items[:5]],
                "top_event_labels": top_event_labels(active_themes),
                "salient_event_scores": summarize_event_scores(active_themes),
                "salient_event_count": count_events_above_saliency(active_themes),
                "event_regime_tags": extract_event_tags(active_themes),
                "event_lifecycle_summary": lifecycle_summary,
                "contradictory_event_labels": contradiction_labels,
                "event_windows": list(lifecycle_summary.get("window_hints", [])),
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
        primary_source_counts: dict[str, int],
    ) -> float:
        top_event_score = max((float(item.get("saliency_weight", 0.0) or 0.0) for item in active_themes), default=0.0)
        escalating_boost = min(0.1, sum(1 for item in active_themes if item.get("persistence_state") == "escalating") * 0.05)
        official_boost = min(0.14, primary_source_counts.get("official", 0) * 0.07)
        major_boost = min(0.08, primary_source_counts.get("major", 0) * 0.04)
        score = (
            0.08
            + top_event_score * 0.42
            + (len(active_themes) * 0.08)
            + (min(news_item_count, 6) * 0.05)
            + (min(social_item_count, 4) * 0.02)
            + official_boost
            + major_boost
            + escalating_boost
            + (sentiment_magnitude * 0.12)
        )
        return round(min(1.0, score), 3)

    @staticmethod
    def _confidence_percent(
        active_themes: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        diagnostics: dict[str, object],
        feed_errors: list[str],
        primary_source_counts: dict[str, int],
        *,
        contradiction_count: int,
    ) -> float:
        social_provider_count = len(diagnostics.get("providers", [])) if isinstance(diagnostics, dict) and isinstance(diagnostics.get("providers"), list) else 0
        high_saliency_events = count_events_above_saliency(active_themes)
        confidence = (
            22.0
            + (len(active_themes) * 7.0)
            + (high_saliency_events * 6.0)
            + (min(news_item_count, 6) * 6.0)
            + (min(social_item_count, 4) * 1.5)
            + (social_provider_count * 2.0)
            + (primary_source_counts.get("official", 0) * 5.0)
            + (primary_source_counts.get("major", 0) * 3.0)
            + (primary_source_counts.get("trade", 0) * 3.0)
        )
        if any(item.get("persistence_state") == "escalating" for item in active_themes):
            confidence += 4.0
        if news_item_count == 0:
            confidence -= 18.0
        if primary_source_counts.get("official", 0) == 0 and primary_source_counts.get("major", 0) == 0:
            confidence -= 8.0
        if contradiction_count > 0:
            confidence -= min(10.0, contradiction_count * 4.0)
        if feed_errors:
            confidence -= min(12.0, len(feed_errors) * 4.0)
        return round(max(5.0, min(92.0, confidence)), 1)

    @staticmethod
    def _summary_text(
        previous: MacroContextSnapshot | None,
        active_themes: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        news_items: list[object],
        social_items: list[object],
        warnings: list[str],
    ) -> str:
        theme_labels = [str(item.get("label", "")).strip() for item in active_themes if item.get("label")]
        focus = ", ".join(theme_labels[:2]) if theme_labels else "no dominant macro theme"
        new_labels = list(lifecycle_summary.get("new_event_labels", []))
        escalating_labels = list(lifecycle_summary.get("escalating_event_labels", []))
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))
        fading_labels = list(lifecycle_summary.get("fading_event_labels", []))
        if contradiction_labels and theme_labels:
            return f"Macro context centers on {focus}. Fresh evidence is present, but contradictions remain around {', '.join(contradiction_labels[:2])}."
        if escalating_labels:
            return f"Macro context centers on {focus}. The key update is escalation in {', '.join(escalating_labels[:2])}, keeping transmission pressure active."
        if previous and previous.summary_text and new_labels:
            return f"Backdrop still leans on {focus}, with fresh macro attention shifting toward {', '.join(new_labels[:2])}."
        if fading_labels and theme_labels:
            return f"Macro context still points to {focus}, but some earlier pressure is fading around {', '.join(fading_labels[:2])}."
        if theme_labels and news_items:
            return f"Macro context is currently led by {focus}, with primary news doing most of the regime-identification work in this run."
        if theme_labels and social_items:
            return f"Macro context points to {focus}, but primary-news evidence was thin so this run leans more on social confirmation than desired."
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
