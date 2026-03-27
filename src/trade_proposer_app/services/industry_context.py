from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import IndustryContextSnapshot, SentimentSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.services.event_extraction import (
    EventDefinition,
    count_events_above_saliency,
    coverage_quality_label,
    event_keys,
    extract_ranked_events,
    publisher_summary,
    source_priority_counts,
    summarize_event_lifecycle,
    summarize_event_scores,
    summarize_source_priorities,
    top_event_labels,
)
from trade_proposer_app.services.news import NewsIngestionService

MACRO_LINK_DEFINITIONS = [
    EventDefinition("inflation", "Inflation", ("inflation",), category="macro_transmission", window_hint="2d_5d", transmission_channels=("input_costs", "pricing_power")),
    EventDefinition("rates", "Rates", ("rate", "rates"), category="macro_transmission", window_hint="1w_plus", transmission_channels=("funding_costs", "valuation_duration")),
    EventDefinition("yield_pressure", "Yield pressure", ("yield",), category="macro_transmission", window_hint="2d_5d", transmission_channels=("valuation_duration", "funding_costs")),
    EventDefinition("energy_costs", "Energy costs", ("oil", "energy prices", "crude"), category="macro_transmission", window_hint="2d_5d", transmission_channels=("transport_costs", "input_costs")),
    EventDefinition("geopolitics", "Geopolitics", ("war", "geopolitical", "sanctions", "conflict"), category="macro_transmission", window_hint="1d", transmission_channels=("supply_chain", "risk_appetite")),
    EventDefinition("trade_policy", "Trade policy", ("tariff", "export controls", "trade policy"), category="macro_transmission", window_hint="1w_plus", transmission_channels=("trade_flows", "supply_chain")),
    EventDefinition("growth_risk", "Growth risk", ("recession", "slowdown"), category="macro_transmission", window_hint="1w_plus", transmission_channels=("cyclical_demand", "enterprise_spend")),
]

INDUSTRY_EVENT_DEFINITIONS = [
    EventDefinition("conference_cycle", "Conference cycle", ("conference", "investor day", "expo"), category="industry_native", window_hint="1d", transmission_channels=("theme_attention", "read_through")),
    EventDefinition("guidance", "Guidance", ("guidance", "outlook"), category="industry_native", window_hint="2d_5d", transmission_channels=("estimate_revision", "sentiment_revision")),
    EventDefinition("pricing", "Pricing", ("pricing", "price increase", "price cuts"), category="industry_native", window_hint="1w_plus", transmission_channels=("margin_profile", "competitive_position")),
    EventDefinition("demand", "Demand", ("demand", "orders", "order growth"), category="industry_native", window_hint="2d_5d", transmission_channels=("revenue_sensitivity", "capacity_utilization")),
    EventDefinition("backlog", "Backlog", ("backlog",), category="industry_native", window_hint="1w_plus", transmission_channels=("revenue_visibility",)),
    EventDefinition("innovation", "Innovation", ("innovation", "breakthrough", "roadmap"), category="industry_native", window_hint="1w_plus", transmission_channels=("product_cycle", "multiple_expansion")),
    EventDefinition("product_cycle", "Product cycle", ("launch", "product", "rollout", "release"), category="industry_native", window_hint="2d_5d", transmission_channels=("product_cycle", "channel_checks")),
    EventDefinition("regulation", "Regulation", ("regulation", "approval", "antitrust", "compliance"), category="industry_native", window_hint="1w_plus", transmission_channels=("regulatory_risk", "market_access")),
    EventDefinition("supply_chain", "Supply chain", ("supply chain", "capacity", "lead time", "factory"), category="industry_native", window_hint="2d_5d", transmission_channels=("supply_chain", "capacity_utilization")),
    EventDefinition("inventory", "Inventory", ("inventory", "stock build", "destocking"), category="industry_native", window_hint="2d_5d", transmission_channels=("channel_inventory", "pricing_pressure")),
    EventDefinition("ai_theme", "AI theme", ("ai", "artificial intelligence", "accelerator"), category="industry_native", window_hint="2d_5d", transmission_channels=("theme_attention", "compute_demand")),
    EventDefinition("semiconductor_theme", "Semiconductor theme", ("chip", "semiconductor", "foundry"), category="industry_native", window_hint="2d_5d", transmission_channels=("compute_demand", "supply_chain")),
    EventDefinition("cloud_theme", "Cloud theme", ("cloud", "hyperscaler"), category="industry_native", window_hint="2d_5d", transmission_channels=("enterprise_spend", "compute_demand")),
]


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

        previous_drivers = previous.active_drivers if previous is not None else []
        active_drivers = extract_ranked_events(
            news_items,
            supporting_social_items,
            INDUSTRY_EVENT_DEFINITIONS,
            previous_events=previous_drivers,
            max_events=5,
        )
        linked_macro_events = extract_ranked_events(
            news_items,
            supporting_social_items,
            MACRO_LINK_DEFINITIONS,
            previous_events=(previous.active_drivers if previous is not None else []),
            max_events=5,
        )
        linked_macro_themes = event_keys(linked_macro_events)
        linked_industry_themes = self._linked_industry_themes(active_drivers)
        lifecycle_summary = summarize_event_lifecycle(active_drivers, previous_events=previous_drivers)
        feed_errors = list(news_bundle.feed_errors) if news_bundle is not None else []
        primary_source_counts = source_priority_counts(news_items, source_type="news")
        primary_coverage_quality = coverage_quality_label(news_items, source_type="news")
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))

        warnings: list[str] = []
        missing_inputs: list[str] = []
        if not news_items:
            warnings.append(f"industry context for {industry_label} was built without primary industry news evidence; social evidence was used only as a secondary fallback")
            missing_inputs.append("primary_industry_news_evidence")
        elif primary_coverage_quality == "low":
            warnings.append(f"industry context for {industry_label} lacks trade, official, or major-source coverage in its primary news evidence")
        if feed_errors:
            warnings.append(f"industry context for {industry_label} encountered provider issues while gathering primary-news evidence")
        if contradiction_labels:
            warnings.append(f"industry context for {industry_label} includes contradictory driver evidence")
        if not supporting_social_items:
            missing_inputs.append("supporting_social_evidence")

        saliency_score = self._saliency_score(active_drivers, len(news_items), len(supporting_social_items), len(linked_macro_themes), primary_source_counts)
        confidence_percent = self._confidence_percent(
            active_drivers,
            len(news_items),
            len(supporting_social_items),
            diagnostics,
            feed_errors,
            primary_source_counts,
            contradiction_count=int(lifecycle_summary.get("contradiction_count", 0) or 0),
        )
        summary_text = self._summary_text(previous, industry_label, active_drivers, lifecycle_summary, linked_macro_themes, news_items, supporting_social_items)
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
                "primary_news_source_priorities": summarize_source_priorities(news_items, source_type="news"),
                "primary_news_publishers": publisher_summary(news_items),
                "primary_news_coverage_quality": primary_coverage_quality,
                "upstream": source_breakdown if isinstance(source_breakdown, dict) else {},
            },
            metadata={
                "query_diagnostics": diagnostics.get("query_diagnostics", {}) if isinstance(diagnostics, dict) else {},
                "queries": query_terms,
                "news_coverage_insights": news_sentiment.get("coverage_insights", []) if isinstance(news_sentiment, dict) else [],
                "top_news_titles": [self._item_text(item)[:140] for item in news_items[:5]],
                "top_social_titles": [self._item_text(item)[:140] for item in supporting_social_items[:5]],
                "top_driver_labels": top_event_labels(active_drivers),
                "driver_event_scores": summarize_event_scores(active_drivers),
                "macro_event_scores": summarize_event_scores(linked_macro_events),
                "salient_driver_count": count_events_above_saliency(active_drivers),
                "event_lifecycle_summary": lifecycle_summary,
                "contradictory_event_labels": contradiction_labels,
                "event_windows": list(lifecycle_summary.get("window_hints", [])),
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
    def _saliency_score(
        active_drivers: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        macro_link_count: int,
        primary_source_counts: dict[str, int],
    ) -> float:
        top_driver_score = max((float(item.get("saliency_weight", 0.0) or 0.0) for item in active_drivers), default=0.0)
        escalating_boost = min(0.1, sum(1 for item in active_drivers if item.get("persistence_state") == "escalating") * 0.05)
        trade_boost = min(0.16, primary_source_counts.get("trade", 0) * 0.08)
        official_boost = min(0.1, primary_source_counts.get("official", 0) * 0.05)
        major_boost = min(0.08, primary_source_counts.get("major", 0) * 0.04)
        score = (
            0.1
            + top_driver_score * 0.4
            + (len(active_drivers) * 0.08)
            + (min(news_item_count, 6) * 0.05)
            + (min(social_item_count, 4) * 0.02)
            + (macro_link_count * 0.04)
            + trade_boost
            + official_boost
            + major_boost
            + escalating_boost
        )
        return round(min(1.0, score), 3)

    @staticmethod
    def _confidence_percent(
        active_drivers: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        diagnostics: dict[str, object],
        feed_errors: list[str],
        primary_source_counts: dict[str, int],
        *,
        contradiction_count: int,
    ) -> float:
        social_provider_count = len(diagnostics.get("providers", [])) if isinstance(diagnostics, dict) and isinstance(diagnostics.get("providers"), list) else 0
        high_saliency_drivers = count_events_above_saliency(active_drivers)
        confidence = (
            24.0
            + (len(active_drivers) * 7.0)
            + (high_saliency_drivers * 6.0)
            + (min(news_item_count, 6) * 6.0)
            + (min(social_item_count, 4) * 1.5)
            + (social_provider_count * 2.0)
            + (primary_source_counts.get("trade", 0) * 5.0)
            + (primary_source_counts.get("official", 0) * 4.0)
            + (primary_source_counts.get("major", 0) * 3.0)
        )
        if any(item.get("persistence_state") == "escalating" for item in active_drivers):
            confidence += 4.0
        if news_item_count == 0:
            confidence -= 18.0
        if primary_source_counts.get("trade", 0) == 0 and primary_source_counts.get("official", 0) == 0 and primary_source_counts.get("major", 0) == 0:
            confidence -= 8.0
        if contradiction_count > 0:
            confidence -= min(10.0, contradiction_count * 4.0)
        if feed_errors:
            confidence -= min(12.0, len(feed_errors) * 4.0)
        return round(max(5.0, min(92.0, confidence)), 1)

    @staticmethod
    def _summary_text(
        previous: IndustryContextSnapshot | None,
        industry_label: str,
        active_drivers: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        linked_macro_themes: list[str],
        news_items: list[object],
        social_items: list[object],
    ) -> str:
        driver_labels = [str(item.get("label", "")).strip() for item in active_drivers if item.get("label")]
        focus = ", ".join(driver_labels[:2]) if driver_labels else "no dominant industry-native driver"
        macro = ", ".join(linked_macro_themes[:2]) if linked_macro_themes else "limited visible macro transmission"
        new_labels = list(lifecycle_summary.get("new_event_labels", []))
        escalating_labels = list(lifecycle_summary.get("escalating_event_labels", []))
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))
        fading_labels = list(lifecycle_summary.get("fading_event_labels", []))
        if contradiction_labels and driver_labels:
            return f"{industry_label} remains centered on {focus}, but conflicting industry evidence is visible around {', '.join(contradiction_labels[:2])}."
        if escalating_labels:
            return f"{industry_label} is led by {focus}, with escalation now most visible in {', '.join(escalating_labels[:2])}; macro read-through still points to {macro}."
        if previous and previous.summary_text and new_labels:
            return f"{industry_label} still leans on {focus}, but fresh attention is shifting toward {', '.join(new_labels[:2])}; macro read-through remains {macro}."
        if fading_labels and driver_labels:
            return f"{industry_label} context still points to {focus}, but some earlier pressure is fading around {', '.join(fading_labels[:2])}."
        if driver_labels and news_items:
            return f"{industry_label} context is led by {focus}, while macro transmission points to {macro}; primary news is carrying most of the evidence in this run."
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
