from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import IndustryContextSnapshot, SupportSnapshot
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
from trade_proposer_app.services.summary import SummaryResult, SummaryService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService

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
        summary_service: SummaryService | None = None,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.repository = repository
        self.news_service = news_service
        self.summary_service = summary_service
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def create_from_support_snapshot(
        self,
        snapshot: SupportSnapshot,
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
        ontology_profile = self.taxonomy_service.get_industry_definition(industry_key or industry_label)
        sector_definition = self.taxonomy_service.get_sector_definition(ontology_profile.get("sector", ""))
        ontology_relationships = self.taxonomy_service.list_relationships(industry_key or industry_label, direction="outbound")
        matched_ontology_relationships = self._matched_ontology_relationships(
            industry_label,
            ontology_relationships,
            news_items,
            active_drivers,
            linked_macro_events,
        )
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
        triaged_evidence = self._triaged_news_items(news_items, active_drivers, linked_macro_events)
        fallback_summary = self._fallback_summary_text(
            previous,
            industry_label,
            active_drivers,
            lifecycle_summary,
            linked_macro_themes,
            matched_ontology_relationships,
            news_items,
            supporting_social_items,
        )
        summary_result = self._summarize_context(
            previous=previous,
            industry_label=industry_label,
            active_drivers=active_drivers,
            linked_macro_events=linked_macro_events,
            lifecycle_summary=lifecycle_summary,
            news_items=news_items,
            supporting_social_items=supporting_social_items,
            primary_coverage_quality=primary_coverage_quality,
            warnings=warnings,
            ontology_profile=ontology_profile,
            sector_definition=sector_definition,
            matched_ontology_relationships=matched_ontology_relationships,
            fallback_summary=fallback_summary,
        )
        summary_text = summary_result.summary or fallback_summary
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
                "support_snapshot_id": getattr(snapshot, "id", None),
                "support_label": getattr(snapshot, "label", None),
                "support_score": getattr(snapshot, "score", None),
                "primary_news_item_count": len(news_items),
                "supporting_social_item_count": len(supporting_social_items),
                "tracked_tickers": tracked_tickers,
                "primary_news_providers": list(dict.fromkeys(news_bundle.feeds_used)) if news_bundle is not None else [],
                "primary_news_feed_errors": feed_errors,
                "primary_news_source_priorities": summarize_source_priorities(news_items, source_type="news"),
                "primary_news_publishers": publisher_summary(news_items),
                "primary_news_coverage_quality": primary_coverage_quality,
                "ontology_relationship_count": len(ontology_relationships),
                "matched_ontology_relationship_count": len(matched_ontology_relationships),
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
                "triaged_primary_evidence": triaged_evidence,
                "linked_macro_event_labels": top_event_labels(linked_macro_events),
                "ontology_profile": ontology_profile,
                "sector_definition": sector_definition,
                "ontology_relationships": ontology_relationships,
                "matched_ontology_relationships": matched_ontology_relationships,
                "taxonomy_source_mode": self.taxonomy_service.taxonomy_overview().get("source_mode"),
                "context_summary_method": summary_result.method,
                "context_summary_backend": summary_result.backend,
                "context_summary_model": summary_result.model,
                "context_summary_error": summary_result.llm_error,
                "context_summary_duration_seconds": summary_result.duration_seconds,
                "context_summary_metadata": summary_result.metadata,
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

    def _summarize_context(
        self,
        *,
        previous: IndustryContextSnapshot | None,
        industry_label: str,
        active_drivers: list[dict[str, object]],
        linked_macro_events: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        news_items: list[object],
        supporting_social_items: list[object],
        primary_coverage_quality: str,
        warnings: list[str],
        ontology_profile: dict[str, object],
        sector_definition: dict[str, object],
        matched_ontology_relationships: list[dict[str, str]],
        fallback_summary: str,
    ) -> SummaryResult:
        if self.summary_service is None or not active_drivers:
            return SummaryResult(
                summary=fallback_summary,
                method="news_digest",
                backend="news_digest",
                model=None,
                llm_error=None,
                metadata={"reason": "summary service unavailable"},
                duration_seconds=None,
            )
        prompt = self._build_context_summary_prompt(
            previous=previous,
            industry_label=industry_label,
            active_drivers=active_drivers,
            linked_macro_events=linked_macro_events,
            lifecycle_summary=lifecycle_summary,
            news_items=news_items,
            supporting_social_items=supporting_social_items,
            primary_coverage_quality=primary_coverage_quality,
            warnings=warnings,
            ontology_profile=ontology_profile,
            sector_definition=sector_definition,
            matched_ontology_relationships=matched_ontology_relationships,
        )
        return self.summary_service.summarize_prompt(
            prompt,
            fallback_summary=fallback_summary,
            fallback_metadata={
                "summary_kind": "industry_context",
                "industry_label": industry_label,
                "salient_driver_count": len(active_drivers),
                "linked_macro_event_count": len(linked_macro_events),
                "triaged_news_item_count": len(self._triaged_news_items(news_items, active_drivers, linked_macro_events)),
            },
        )

    def _build_context_summary_prompt(
        self,
        *,
        previous: IndustryContextSnapshot | None,
        industry_label: str,
        active_drivers: list[dict[str, object]],
        linked_macro_events: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        news_items: list[object],
        supporting_social_items: list[object],
        primary_coverage_quality: str,
        warnings: list[str],
        ontology_profile: dict[str, object],
        sector_definition: dict[str, object],
        matched_ontology_relationships: list[dict[str, str]],
    ) -> str:
        driver_lines = []
        for index, event in enumerate(active_drivers[:3], start=1):
            channels = event.get("transmission_channels") if isinstance(event.get("transmission_channels"), list) else []
            driver_lines.append(
                f"{index}. {event.get('label', 'Unknown driver')} | state={event.get('persistence_state', 'unknown')} | saliency={event.get('saliency_weight', 0.0)} | source={event.get('source_priority', 'other')} | window={event.get('window_hint', 'unknown')} | direction={event.get('evidence_direction', 'mixed')} | channels={', '.join(str(channel) for channel in channels[:3]) or 'unknown'}"
            )
        macro_lines = []
        for index, event in enumerate(linked_macro_events[:2], start=1):
            macro_lines.append(
                f"{index}. {event.get('label', 'Unknown macro link')} | state={event.get('persistence_state', 'unknown')} | saliency={event.get('saliency_weight', 0.0)} | window={event.get('window_hint', 'unknown')}"
            )
        triaged_news = self._triaged_news_items(news_items, active_drivers, linked_macro_events)
        news_lines = []
        for index, item in enumerate(triaged_news[:6], start=1):
            news_lines.append(
                f"{index}. [{item['source_priority']}] {item['publisher']}: {item['title']}"
                + (f" — {item['summary']}" if item['summary'] else "")
            )
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))
        previous_top_labels = top_event_labels(previous.active_drivers) if previous is not None else []
        previous_macro_links = previous.linked_macro_themes if previous is not None else []
        previous_summary = ""
        if previous is not None and isinstance(previous.summary_text, str):
            previous_summary = previous.summary_text.strip()[:320]
        delta_lines = [
            f"new drivers: {', '.join(str(label) for label in lifecycle_summary.get('new_event_labels', [])) or 'none'}",
            f"escalating drivers: {', '.join(str(label) for label in lifecycle_summary.get('escalating_event_labels', [])) or 'none'}",
            f"fading drivers: {', '.join(str(label) for label in lifecycle_summary.get('fading_event_labels', [])) or 'none'}",
            f"contradictory drivers: {', '.join(contradiction_labels) if contradiction_labels else 'none'}",
        ]
        ontology_lines = [
            f"sector: {sector_definition.get('label') or ontology_profile.get('sector') or 'none'}",
            f"peer industries: {', '.join(str(value) for value in ontology_profile.get('peer_industries', [])) or 'none'}",
            f"risk flags: {', '.join(str(value) for value in ontology_profile.get('risk_flags', [])) or 'none'}",
            f"transmission channels: {', '.join(str(value) for value in ontology_profile.get('transmission_channels', [])) or 'none'}",
        ]
        matched_relationship_lines = [
            f"- {item.get('type', 'linked_to')} {item.get('target_label', item.get('target', 'unknown target'))} via {item.get('channel', 'unknown channel')} ({item.get('strength', 'unspecified')} strength)"
            + (f" — {item.get('note')}" if item.get('note') else "")
            for item in matched_ontology_relationships[:4]
        ]
        prompt_parts = [
            f"Write a short operator-facing industry context summary for {industry_label} in 2-4 sentences.",
            "Focus on the top salient industry drivers, not just one event.",
            "Ground the summary in the highest-quality fetched sources first. Use social evidence only as secondary support.",
            "Say what the main drivers are, how they matter over the next few trading days to weeks, and whether macro read-through is reinforcing or offsetting them.",
            "Use the previous snapshot only to explain continuity or change. Do not let old framing override current evidence.",
            "If evidence is contradictory or degraded, say that plainly.",
            "Do not use hype. Do not invent facts beyond the evidence below.",
            "",
            f"Primary news coverage quality: {primary_coverage_quality}",
            f"Warnings: {'; '.join(warnings) if warnings else 'none'}",
            f"Contradictions: {', '.join(contradiction_labels) if contradiction_labels else 'none'}",
            f"Supporting social item count: {len(supporting_social_items)}",
            "",
            "Previous snapshot context:",
            f"previous top drivers: {', '.join(previous_top_labels) if previous_top_labels else 'none'}",
            f"previous linked macro themes: {', '.join(str(label) for label in previous_macro_links) if previous_macro_links else 'none'}",
            f"previous summary: {previous_summary or 'none'}",
            "",
            "Change since previous snapshot:",
            *delta_lines,
            "",
            "Top industry drivers:",
            *(driver_lines or ["none"]),
            "",
            "Linked macro read-through:",
            *(macro_lines or ["none"]),
            "",
            "Ontology context:",
            *ontology_lines,
            "",
            "Matched ontology relationships:",
            *(matched_relationship_lines or ["none"]),
            "",
            "Triaged high-quality source items:",
            *(news_lines or ["none"]),
            "",
            "Summary:",
        ]
        return "\n".join(prompt_parts)

    def _triaged_news_items(
        self,
        news_items: list[object],
        active_drivers: list[dict[str, object]],
        linked_macro_events: list[dict[str, object]],
    ) -> list[dict[str, str]]:
        definition_map = {definition.key: definition for definition in [*INDUSTRY_EVENT_DEFINITIONS, *MACRO_LINK_DEFINITIONS]}
        prioritized_events = [*active_drivers[:3], *linked_macro_events[:2]]
        ranked: list[tuple[tuple[float, float, int], dict[str, str]]] = []
        for raw_item in news_items:
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title", "") or "").strip()
            summary = str(raw_item.get("summary", "") or "").strip()
            publisher = str(raw_item.get("publisher", "") or "").strip()
            source_priority = self._source_priority_for_item(raw_item)
            priority_score = {"official": 4.0, "trade": 3.0, "major": 2.0, "other": 1.0}.get(source_priority, 0.0)
            text = f"{title} {summary}".lower()
            event_hits = 0
            saliency_score = 0.0
            for event in prioritized_events:
                key = str(event.get("key", "") or "")
                definition = definition_map.get(key)
                if definition is None:
                    continue
                if any(phrase.lower() in text for phrase in definition.phrases):
                    event_hits += 1
                    saliency_score += float(event.get("saliency_weight", 0.0) or 0.0)
            ranked.append(
                (
                    (priority_score, saliency_score, event_hits),
                    {
                        "title": title,
                        "summary": summary,
                        "publisher": publisher or "unknown publisher",
                        "source_priority": source_priority,
                    },
                )
            )
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked[:6]]

    def _matched_ontology_relationships(
        self,
        industry_label: str,
        relationships: list[dict[str, Any]],
        news_items: list[object],
        active_drivers: list[dict[str, object]],
        linked_macro_events: list[dict[str, object]],
    ) -> list[dict[str, str]]:
        evidence_text = " ".join(self._item_text(item).lower() for item in news_items if self._item_text(item).strip())
        active_driver_channels = {
            str(channel).strip().lower()
            for event in active_drivers
            for channel in (event.get("transmission_channels") if isinstance(event.get("transmission_channels"), list) else [])
            if str(channel).strip()
        }
        active_driver_keys = {str(event.get("key", "")).strip().lower() for event in active_drivers if str(event.get("key", "")).strip()}
        macro_channels = {
            str(channel).strip().lower()
            for event in linked_macro_events
            for channel in (event.get("transmission_channels") if isinstance(event.get("transmission_channels"), list) else [])
            if str(channel).strip()
        }
        macro_keys = {str(event.get("key", "")).strip().lower() for event in linked_macro_events if str(event.get("key", "")).strip()}
        matched: list[dict[str, str]] = []
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            target = str(relationship.get("target", "")).strip()
            target_kind = str(relationship.get("target_kind", "industry")).strip() or "industry"
            target_label = str(relationship.get("target_label", "")).strip() or target.replace("_", " ")
            if target_kind == "industry" and target:
                target_label = self.taxonomy_service.get_industry_definition(target).get("label") or target_label
            elif target_kind == "sector" and target:
                target_label = self.taxonomy_service.get_sector_definition(target).get("label") or target_label
            elif target_kind == "theme" and target:
                target_label = self.taxonomy_service.get_theme_definition(target).get("label") or target_label
            elif target_kind == "macro_channel" and target:
                target_label = self.taxonomy_service.get_macro_channel_definition(target).get("label") or target_label
            tokens = self._relationship_tokens(relationship, target_label)
            channel = str(relationship.get("channel", "")).strip()
            channel_key = channel.lower()
            target_key = target.lower()
            relevance_hits = 0
            if any(token in evidence_text for token in tokens):
                relevance_hits += 1
            if channel_key and (channel_key in active_driver_channels or channel_key in macro_channels):
                relevance_hits += 1
            if target_kind == "macro_channel" and target_key and target_key in macro_keys:
                relevance_hits += 1
            if target_kind == "theme" and target_key and target_key in active_driver_keys:
                relevance_hits += 1
            if relevance_hits <= 0:
                continue
            matched.append(
                {
                    "source": str(relationship.get("source", industry_label)).strip(),
                    "source_label": str(relationship.get("source_label", industry_label)).strip() or industry_label,
                    "type": str(relationship.get("type", "linked_to")).strip() or "linked_to",
                    "type_label": str(relationship.get("type_label", relationship.get("type", "linked to"))).strip() or "linked to",
                    "target": target,
                    "target_kind": target_kind,
                    "target_kind_label": str(relationship.get("target_kind_label", target_kind.replace("_", " "))).strip() or target_kind.replace("_", " "),
                    "target_label": str(target_label).strip() or target,
                    "channel": channel or "unknown channel",
                    "channel_label": str(relationship.get("channel_label", channel.replace("_", " "))).strip() if channel else "unknown channel",
                    "strength": str(relationship.get("strength", "")).strip() or "unspecified",
                    "note": str(relationship.get("note", "")).strip(),
                    "relevance_hits": relevance_hits,
                }
            )
        return matched[:6]

    @staticmethod
    def _relationship_tokens(relationship: dict[str, Any], target_label: str) -> list[str]:
        raw_terms = [
            str(relationship.get("target", "")).replace("_", " "),
            str(target_label),
            str(relationship.get("channel", "")).replace("_", " "),
            str(relationship.get("channel_label", "")),
            str(relationship.get("type_label", "")),
            str(relationship.get("note", "")),
        ]
        tokens: list[str] = []
        for term in raw_terms:
            for token in term.lower().replace("/", " ").replace("-", " ").split():
                cleaned = token.strip()
                if not cleaned:
                    continue
                if len(cleaned) >= 3 or cleaned == "ai":
                    if cleaned not in tokens:
                        tokens.append(cleaned)
        return tokens

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
    def _fallback_summary_text(
        previous: IndustryContextSnapshot | None,
        industry_label: str,
        active_drivers: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        linked_macro_themes: list[str],
        matched_ontology_relationships: list[dict[str, str]],
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
        relationship_note = ""
        if matched_ontology_relationships:
            top_relationship = matched_ontology_relationships[0]
            relationship_note = f" Ontology read-through most clearly points to {top_relationship.get('type', 'linked_to')} {top_relationship.get('target_label', top_relationship.get('target', 'known transmission path'))} via {top_relationship.get('channel', 'known channel')}."
        if contradiction_labels and driver_labels:
            return f"{industry_label} remains centered on {focus}, but conflicting industry evidence is visible around {', '.join(contradiction_labels[:2])}.{relationship_note}"
        if escalating_labels:
            return f"{industry_label} is led by {focus}, with escalation now most visible in {', '.join(escalating_labels[:2])}; macro read-through still points to {macro}.{relationship_note}"
        if previous and previous.summary_text and new_labels:
            return f"{industry_label} still leans on {focus}, but fresh attention is shifting toward {', '.join(new_labels[:2])}; macro read-through remains {macro}.{relationship_note}"
        if fading_labels and driver_labels:
            return f"{industry_label} context still points to {focus}, but some earlier pressure is fading around {', '.join(fading_labels[:2])}.{relationship_note}"
        if driver_labels and news_items:
            return f"{industry_label} context is led by {focus}, while macro transmission points to {macro}; primary news is carrying most of the evidence in this run.{relationship_note}"
        if driver_labels and social_items:
            return f"{industry_label} context still points to {focus}, but primary industry news was thin so the run leans more on social confirmation than desired.{relationship_note}"
        if previous and previous.summary_text:
            return f"{industry_label} context is broadly unchanged, but this run did not surface a clearly dominant fresh driver."
        return f"{industry_label} context is currently light on salient evidence, so the output mainly records continuity and known macro links."

    @staticmethod
    def _source_priority_for_item(raw_item: dict[str, object]) -> str:
        publisher = raw_item.get("publisher")
        normalized = str(publisher or "").strip().lower()
        if any(hint in normalized for hint in ("sec", "fda", "federal reserve", "treasury", "department of", "european commission")):
            return "official"
        if any(hint in normalized for hint in ("digitimes", "semianalysis", "freightwaves", "fierce", "endpoints", "stat", "the information", "industry dive")):
            return "trade"
        if any(hint in normalized for hint in ("reuters", "bloomberg", "financial times", "wall street journal", "wsj", "cnbc", "associated press", "ap", "nikkei", "barron's")):
            return "major"
        return "other"

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
