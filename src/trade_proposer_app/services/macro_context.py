from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from trade_proposer_app.domain.models import MacroContextRefreshPayload, MacroContextSnapshot
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
from trade_proposer_app.services.summary import SummaryResult, SummaryService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService

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
        key="inflation_cooling",
        label="Inflation cooling",
        phrases=("disinflation", "cooling inflation", "cooler cpi", "cooler ppi", "easing prices"),
        tags=("inflation",),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("rates", "consumer_pressure"),
        beneficiary_tags=("long_duration", "consumer"),
        loser_tags=("pricing_power",),
    ),
    EventDefinition(
        key="inflation_sticky",
        label="Sticky inflation",
        phrases=("inflation", "cpi", "ppi", "sticky prices", "hotter inflation"),
        tags=("inflation",),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("input_costs", "rates", "consumer_pressure"),
        beneficiary_tags=("pricing_power",),
        loser_tags=("margin_pressure",),
    ),
    EventDefinition(
        key="bond_yield_drop",
        label="Bond yields easing",
        phrases=("yields fell", "yield drop", "treasury rally", "bond rally", "lower yields"),
        tags=("rates", "yield_pressure"),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("rates", "valuation_duration", "funding_costs"),
        beneficiary_tags=("long_duration",),
        loser_tags=("financials",),
    ),
    EventDefinition(
        key="bond_yield_spike",
        label="Bond yields rising",
        phrases=("yield", "treasury", "10-year", "2-year", "bond selloff", "higher yields", "yield jump"),
        tags=("rates", "yield_pressure"),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("rates", "valuation_duration", "funding_costs"),
        beneficiary_tags=("financials",),
        loser_tags=("long_duration",),
    ),
    EventDefinition(
        key="oil_supply_relief",
        label="Oil supply relief",
        phrases=("oil fell", "crude fell", "output increase", "opec supply", "supply relief", "lower energy prices"),
        tags=("commodities",),
        category="macro",
        window_hint="2d_5d",
        transmission_channels=("commodity_input_costs", "transport_costs"),
        beneficiary_tags=("airlines", "consumer"),
        loser_tags=("energy",),
    ),
    EventDefinition(
        key="oil_supply_risk",
        label="Oil supply risk",
        phrases=("oil", "crude", "opec", "energy prices", "brent", "wti", "supply disruption", "oil spike"),
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
        key="geopolitical_deescalation",
        label="Geopolitical de-escalation",
        phrases=("ceasefire", "truce", "de-escalation", "talks resume", "diplomatic progress", "relief after comments"),
        tags=("geopolitics",),
        category="macro_shock",
        window_hint="1d",
        transmission_channels=("commodity_risk", "risk_appetite"),
        beneficiary_tags=("travel", "consumer", "global_supply_chain"),
        loser_tags=("defense", "energy"),
    ),
    EventDefinition(
        key="geopolitical_escalation",
        label="Geopolitical escalation",
        phrases=("war", "military tensions", "geopolitical tensions", "missile", "sanctions", "conflict", "strike", "retaliation"),
        tags=("geopolitics", "risk_off"),
        category="macro_shock",
        window_hint="1d",
        transmission_channels=("commodity_risk", "supply_chain", "risk_appetite"),
        beneficiary_tags=("defense", "energy"),
        loser_tags=("travel", "global_supply_chain"),
    ),
]

DEFAULT_MACRO_NEWS_QUERIES = [
    "Federal Reserve OR FOMC OR Powell OR rate cut OR rate hike",
    "inflation OR CPI OR PPI OR disinflation OR cooling prices",
    "Treasury yields OR bond market OR higher yields OR lower yields",
    "ECB OR eurozone rates OR Lagarde",
    "war OR sanctions OR geopolitical tensions OR missile OR retaliation OR ceasefire OR truce OR diplomatic progress",
    "oil OR crude OR OPEC OR supply disruption OR output increase OR energy prices",
]


class MacroContextService:
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

    def create_from_refresh_payload(
        self,
        payload: MacroContextRefreshPayload,
        *,
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> MacroContextSnapshot:
        effective_now = payload.computed_at or datetime.now(timezone.utc)
        previous = self.repository.get_latest_macro_context_snapshot_before(effective_now)
        signals = dict(getattr(payload, "signals", {}) or {})
        diagnostics = dict(getattr(payload, "diagnostics", {}) or {})
        source_breakdown = dict(getattr(payload, "source_breakdown", {}) or {})
        social_items = signals.get("social_items") if isinstance(signals, dict) else []
        supporting_social_items = social_items if isinstance(social_items, list) else []

        news_bundle, news_sentiment = self._load_news_evidence(as_of=effective_now)
        primary_news_items = news_sentiment.get("news_items", []) if isinstance(news_sentiment, dict) else []
        news_items = primary_news_items if isinstance(primary_news_items, list) else []

        previous_events = previous.active_themes if previous is not None else []
        active_themes = self._with_channel_details(
            extract_ranked_events(
                news_items,
                supporting_social_items,
                MACRO_THEME_DEFINITIONS,
                previous_events=previous_events,
                max_events=5,
            )
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

        support_score = float(getattr(payload, "score", 0.0) or 0.0)
        support_label = str(getattr(payload, "label", "NEUTRAL") or "NEUTRAL")
        regime_tags = self._regime_tags(active_themes, support_score, support_label)
        saliency_score = self._saliency_score(active_themes, len(news_items), len(supporting_social_items), abs(support_score), primary_source_counts)
        confidence_percent = self._confidence_percent(
            active_themes,
            len(news_items),
            len(supporting_social_items),
            diagnostics,
            feed_errors,
            primary_source_counts,
            contradiction_count=int(lifecycle_summary.get("contradiction_count", 0) or 0),
        )
        fallback_summary = self._fallback_summary_text(previous, active_themes, lifecycle_summary, news_items, supporting_social_items, warnings)
        summary_result = self._summarize_context(
            previous=previous,
            active_themes=active_themes,
            lifecycle_summary=lifecycle_summary,
            news_items=news_items,
            supporting_social_items=supporting_social_items,
            primary_coverage_quality=primary_coverage_quality,
            warnings=warnings,
            fallback_summary=fallback_summary,
        )
        summary_text = summary_result.summary or fallback_summary
        status = "warning" if warnings else "ok"
        triaged_evidence = self._triaged_news_items(news_items, active_themes)

        context = MacroContextSnapshot(
            computed_at=effective_now,
            expires_at=getattr(payload, "expires_at", None),
            status=status,
            summary_text=summary_text,
            saliency_score=saliency_score,
            confidence_percent=confidence_percent,
            active_themes=active_themes,
            regime_tags=regime_tags,
            warnings=list(dict.fromkeys(warnings)),
            missing_inputs=list(dict.fromkeys(missing_inputs)),
            source_breakdown={
                "context_refresh_subject_key": getattr(payload, "subject_key", None),
                "context_label": support_label,
                "context_score": support_score,
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
                "subject_key": getattr(payload, "subject_key", None),
                "subject_label": getattr(payload, "subject_label", None),
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
                "triaged_primary_evidence": triaged_evidence,
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
        return self.repository.create_macro_context_snapshot(context)


    def _channel_details(self, values: list[object]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            definition = self.taxonomy_service.get_transmission_channel_definition(value)
            key = str(definition.get("key", value)).strip() or value.strip()
            if key in seen:
                continue
            seen.add(key)
            label = str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " ")
            details.append({"key": key, "label": label})
        return details

    def _with_channel_details(self, events: list[dict[str, object]]) -> list[dict[str, object]]:
        enriched: list[dict[str, object]] = []
        for event in events:
            payload = dict(event)
            channels = payload.get("transmission_channels") if isinstance(payload.get("transmission_channels"), list) else []
            payload["transmission_channel_details"] = self._channel_details(channels)
            enriched.append(payload)
        return enriched

    def _load_news_evidence(self, *, as_of: datetime | None = None) -> tuple[object | None, dict[str, object]]:
        if self.news_service is None:
            return None, {}
        
        effective_now = as_of or datetime.now(timezone.utc)
        start_at = effective_now - timedelta(hours=24)
        
        bundle = self.news_service.fetch_topics("Global Macro", DEFAULT_MACRO_NEWS_QUERIES, start_at=start_at, end_at=effective_now)
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
        theme_factor = min(1.0, math.log1p(len(active_themes)) / math.log(6.0)) if active_themes else 0.0
        news_factor = min(1.0, math.log1p(news_item_count) / math.log(7.0)) if news_item_count > 0 else 0.0
        social_factor = min(1.0, math.log1p(social_item_count) / math.log(5.0)) if social_item_count > 0 else 0.0
        source_quality = min(
            1.0,
            (
                (primary_source_counts.get("official", 0) * 1.0)
                + (primary_source_counts.get("major", 0) * 0.7)
                + (primary_source_counts.get("trade", 0) * 0.45)
            )
            / 3.0,
        )
        escalating_factor = min(1.0, sum(1 for item in active_themes if item.get("persistence_state") == "escalating") / 2.0)
        raw_score = (
            top_event_score * 0.52
            + theme_factor * 0.13
            + news_factor * 0.12
            + social_factor * 0.05
            + source_quality * 0.10
            + escalating_factor * 0.04
            + min(1.0, sentiment_magnitude) * 0.04
        )
        return round(min(0.98, 1.0 - math.exp(-(raw_score * 1.35))), 3)

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
        average_saliency = (
            sum(float(item.get("saliency_weight", 0.0) or 0.0) for item in active_themes) / len(active_themes)
            if active_themes
            else 0.0
        )
        theme_factor = min(1.0, math.log1p(len(active_themes)) / math.log(6.0)) if active_themes else 0.0
        news_factor = min(1.0, math.log1p(news_item_count) / math.log(9.0)) if news_item_count > 0 else 0.0
        social_factor = min(1.0, math.log1p(social_item_count) / math.log(5.0)) if social_item_count > 0 else 0.0
        source_quality = min(
            1.0,
            (
                (primary_source_counts.get("official", 0) * 1.0)
                + (primary_source_counts.get("major", 0) * 0.7)
                + (primary_source_counts.get("trade", 0) * 0.4)
            )
            / 3.0,
        )
        saliency_factor = min(1.0, (average_saliency * 0.7) + (min(3, high_saliency_events) / 3.0 * 0.3))
        escalating_factor = 1.0 if any(item.get("persistence_state") == "escalating" for item in active_themes) else 0.0
        provider_factor = min(1.0, social_provider_count / 3.0)

        confidence = (
            18.0
            + theme_factor * 14.0
            + news_factor * 18.0
            + social_factor * 5.0
            + source_quality * 18.0
            + saliency_factor * 16.0
            + escalating_factor * 5.0
            + provider_factor * 3.0
        )
        if news_item_count == 0:
            confidence -= 18.0
        if primary_source_counts.get("official", 0) == 0 and primary_source_counts.get("major", 0) == 0:
            confidence -= 10.0
        if contradiction_count > 0:
            confidence -= min(22.0, contradiction_count * 7.0)
        if feed_errors:
            confidence -= min(18.0, len(feed_errors) * 6.0)
        return round(max(0.0, min(97.0, confidence)), 1)

    @classmethod
    def _fallback_summary_text(
        cls,
        previous: MacroContextSnapshot | None,
        active_themes: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        news_items: list[object],
        social_items: list[object],
        warnings: list[str],
    ) -> str:
        top_theme = active_themes[0] if active_themes else None
        if not isinstance(top_theme, dict):
            if warnings:
                return "Macro context evidence is light in this run, so the output is mainly a continuity placeholder rather than a strong regime call."
            return "Macro context remains mixed without one clearly dominant theme."

        top_label = str(top_theme.get("label", "")).strip() or "an unclear macro theme"
        state = cls._describe_state(str(top_theme.get("persistence_state", "unknown") or "unknown"))
        why = cls._describe_channels(top_theme.get("transmission_channels"))
        window = cls._describe_window(str(top_theme.get("window_hint", "unknown") or "unknown"))
        source = cls._describe_source_priority(str(top_theme.get("source_priority", "other") or "other"))
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))
        escalating_labels = list(lifecycle_summary.get("escalating_event_labels", []))
        new_labels = [label for label in lifecycle_summary.get("new_event_labels", []) if label != top_label]
        fading_labels = list(lifecycle_summary.get("fading_event_labels", []))

        catalyst = str(top_theme.get("catalyst_type", "other") or "other").replace("_", " ")
        interpretation = str(top_theme.get("market_interpretation", "unknown") or "unknown").replace("_", " ")
        change_reason = str(top_theme.get("state_change_reason", "") or "").strip()
        overview = f"Top macro event: {top_label}. It looks {state}, is being driven mainly by {catalyst}, and matters mainly through {why} over {window}."
        evidence = f"Evidence is led by {source} coverage"
        if news_items:
            evidence += f" across {len(news_items)} primary news item{'s' if len(news_items) != 1 else ''}"
        elif social_items:
            evidence += ", but this run had to lean on social confirmation more than desired"
        else:
            evidence += ", but this run has very thin direct evidence"
        evidence += "."

        updates: list[str] = []
        if contradiction_labels:
            updates.append(f"There is still conflicting evidence around {', '.join(contradiction_labels[:2])}")
        elif top_label in escalating_labels:
            updates.append(f"{top_label} is the main escalation in this run")
        elif new_labels:
            updates.append(f"Fresh attention is also shifting toward {', '.join(new_labels[:2])}")
        elif top_label in fading_labels:
            updates.append(f"The earlier pressure around {top_label} is fading")
        elif previous and previous.summary_text:
            updates.append("This remains broadly consistent with the prior macro snapshot")

        if warnings and not contradiction_labels:
            updates.append("Coverage is still degraded enough that the overview should be read with caution")

        interpretation_line = ""
        if interpretation != "unknown":
            interpretation_line = f" The current market read looks more {interpretation}."
        reason_line = f" {change_reason}" if change_reason else ""

        if updates:
            return f"{overview} {evidence}{interpretation_line} {' '.join(updates)}.{reason_line}"
        return f"{overview} {evidence}{interpretation_line}{reason_line}"

    def _summarize_context(
        self,
        *,
        previous: MacroContextSnapshot | None,
        active_themes: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        news_items: list[object],
        supporting_social_items: list[object],
        primary_coverage_quality: str,
        warnings: list[str],
        fallback_summary: str,
    ) -> SummaryResult:
        if self.summary_service is None or not active_themes:
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
            active_themes=active_themes,
            lifecycle_summary=lifecycle_summary,
            news_items=news_items,
            supporting_social_items=supporting_social_items,
            primary_coverage_quality=primary_coverage_quality,
            warnings=warnings,
        )
        return self.summary_service.summarize_prompt(
            prompt,
            fallback_summary=fallback_summary,
            fallback_metadata={
                "summary_kind": "macro_context",
                "salient_event_count": len(active_themes),
                "triaged_news_item_count": len(self._triaged_news_items(news_items, active_themes)),
            },
        )

    def _build_context_summary_prompt(
        self,
        *,
        previous: MacroContextSnapshot | None,
        active_themes: list[dict[str, object]],
        lifecycle_summary: dict[str, object],
        news_items: list[object],
        supporting_social_items: list[object],
        primary_coverage_quality: str,
        warnings: list[str],
    ) -> str:
        top_events = []
        for index, event in enumerate(active_themes[:3], start=1):
            channels = event.get("transmission_channels") if isinstance(event.get("transmission_channels"), list) else []
            top_events.append(
                f"{index}. {event.get('label', 'Unknown event')} | state={event.get('persistence_state', 'unknown')} | transition={event.get('state_transition', 'unknown')} | catalyst={event.get('catalyst_type', 'other')} | interpretation={event.get('market_interpretation', 'unknown')} | saliency={event.get('saliency_weight', 0.0)} | source={event.get('source_priority', 'other')} | window={event.get('window_hint', 'unknown')} | direction={event.get('evidence_direction', 'mixed')} | actor={event.get('trigger_actor', 'unknown')} | channels={', '.join(str(channel) for channel in channels[:3]) or 'unknown'} | why={event.get('state_change_reason', 'n/a')}"
            )
        triaged_news = self._triaged_news_items(news_items, active_themes)
        news_lines = []
        for index, item in enumerate(triaged_news[:6], start=1):
            news_lines.append(
                f"{index}. [{item['source_priority']}] {item['publisher']}: {item['title']}"
                + (f" — {item['summary']}" if item['summary'] else "")
            )
        contradiction_labels = list(lifecycle_summary.get("contradictory_event_labels", []))
        previous_top_labels = top_event_labels(previous.active_themes) if previous is not None else []
        previous_regime_tags = previous.regime_tags if previous is not None else []
        previous_summary = ""
        if previous is not None and isinstance(previous.summary_text, str):
            previous_summary = previous.summary_text.strip()[:320]
        delta_lines = [
            f"new events: {', '.join(str(label) for label in lifecycle_summary.get('new_event_labels', [])) or 'none'}",
            f"escalating events: {', '.join(str(label) for label in lifecycle_summary.get('escalating_event_labels', [])) or 'none'}",
            f"fading events: {', '.join(str(label) for label in lifecycle_summary.get('fading_event_labels', [])) or 'none'}",
            f"contradictory events: {', '.join(contradiction_labels) if contradiction_labels else 'none'}",
        ]
        prompt_parts = [
            "Write a short operator-facing macro market summary in 2-4 sentences.",
            "Focus on the top salient events, not just one event.",
            "Ground the summary in the highest-quality fetched sources first. Use social evidence only as secondary support.",
            "Say what the main macro events are, what concrete catalyst or state change is driving them right now, why they matter, and what short-horizon transmission window they imply.",
            "Explicitly distinguish escalation, easing, stabilization, or mixed conditions when the evidence supports it.",
            "Prefer durable semantic language over person-specific labels; mention specific actors only as evidence-level detail.",
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
            f"previous top events: {', '.join(previous_top_labels) if previous_top_labels else 'none'}",
            f"previous regime tags: {', '.join(str(tag) for tag in previous_regime_tags) if previous_regime_tags else 'none'}",
            f"previous summary: {previous_summary or 'none'}",
            "",
            "Change since previous snapshot:",
            *delta_lines,
            "",
            "Top salient events:",
            *top_events,
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
        active_themes: list[dict[str, object]],
    ) -> list[dict[str, str]]:
        definition_map = {definition.key: definition for definition in MACRO_THEME_DEFINITIONS}
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
            state_change_bonus = 0
            for event in active_themes[:3]:
                key = str(event.get("key", "") or "")
                definition = definition_map.get(key)
                if definition is None:
                    continue
                if any(phrase.lower() in text for phrase in definition.phrases):
                    event_hits += 1
                    saliency_score += float(event.get("saliency_weight", 0.0) or 0.0)
                    if any(hint in text for hint in ("escalat", "de-escalat", "easing", "relief", "cooling", "ceasefire", "sanction", "disruption", "jump", "cut")):
                        state_change_bonus += 1
            ranked.append(
                (
                    (priority_score, saliency_score + (state_change_bonus * 0.35), event_hits + state_change_bonus),
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

    @staticmethod
    def _source_priority_for_item(raw_item: dict[str, object]) -> str:
        publisher = raw_item.get("publisher")
        normalized = str(publisher or "").strip().lower()
        if any(hint in normalized for hint in ("federal reserve", "fomc", "treasury", "ecb", "european central bank", "opec")):
            return "official"
        if any(hint in normalized for hint in ("digitimes", "semianalysis", "freightwaves")):
            return "trade"
        if any(hint in normalized for hint in ("reuters", "bloomberg", "financial times", "wall street journal", "wsj", "cnbc", "associated press", "ap", "nikkei")):
            return "major"
        return "other"

    @staticmethod
    def _describe_state(state: str) -> str:
        return {
            "new": "new",
            "escalating": "like it is escalating",
            "persistent": "persistent",
            "fading": "like it is fading",
        }.get(state, "unclear")

    @staticmethod
    def _describe_window(window: str) -> str:
        return {
            "1d": "about one trading day",
            "2d_5d": "roughly the next 2 to 5 trading days",
            "1w_plus": "about a week or longer",
            "intraday": "intraday",
            "unknown": "unclear",
        }.get(window, window.replace("_", " ") if window else "unclear")

    @staticmethod
    def _describe_source_priority(priority: str) -> str:
        return {
            "official": "official or policy-source",
            "major": "major-news",
            "trade": "trade-publication",
            "other": "other-news",
            "social": "social",
        }.get(priority, "mixed-source")

    @staticmethod
    def _describe_channels(raw_channels: object) -> str:
        if not isinstance(raw_channels, list):
            return "unclear channels"
        channel_map = {
            "rates": "interest-rate pressure",
            "valuation_duration": "valuation sensitivity",
            "funding_costs": "funding costs",
            "commodity_input_costs": "commodity input costs",
            "energy_revenue": "energy revenue sensitivity",
            "transport_costs": "transport costs",
            "cyclical_demand": "cyclical demand",
            "credit_risk": "credit risk",
            "beta": "broad risk appetite",
            "risk_appetite": "broad risk appetite",
            "liquidity": "liquidity conditions",
            "euro_rates": "European rate pressure",
            "european_demand": "European demand",
            "commodity_risk": "commodity risk",
            "supply_chain": "supply-chain pressure",
        }
        labels = [channel_map.get(str(item), str(item).replace("_", " ")) for item in raw_channels[:2]]
        return " and ".join(labels) if labels else "unclear channels"

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
