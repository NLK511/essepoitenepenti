from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import IndustryContextSnapshot, SentimentSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository

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
    def __init__(self, repository: ContextSnapshotRepository) -> None:
        self.repository = repository

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
        items = social_items if isinstance(social_items, list) else []
        active_drivers = self._extract_active_drivers(items)
        linked_macro_themes = self._linked_macro_themes(items)
        linked_industry_themes = self._linked_industry_themes(active_drivers)
        warnings = []
        missing_inputs = []
        if not items:
            warnings.append(f"industry context for {industry_label} was built without matched social evidence")
        warnings.append("industry context currently relies on social evidence first; trade-press/news-first writer still pending")
        if not source_breakdown or not (source_breakdown.get("news") if isinstance(source_breakdown, dict) else None):
            missing_inputs.append("primary_industry_news_evidence")
        saliency_score = self._saliency_score(active_drivers, len(items), len(linked_macro_themes))
        confidence_percent = self._confidence_percent(active_drivers, len(items), diagnostics)
        summary_text = self._summary_text(previous, industry_label, active_drivers, linked_macro_themes)
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
                "social_item_count": len(items),
                "tracked_tickers": coverage.get("tracked_tickers", []) if isinstance(coverage, dict) else [],
                "providers": diagnostics.get("providers", []) if isinstance(diagnostics, dict) else [],
                "upstream": source_breakdown if isinstance(source_breakdown, dict) else {},
            },
            metadata={
                "query_diagnostics": diagnostics.get("query_diagnostics", {}) if isinstance(diagnostics, dict) else {},
                "queries": diagnostics.get("queries", []) if isinstance(diagnostics, dict) else [],
                "top_evidence_titles": [self._item_text(item)[:140] for item in items[:5]],
            },
            run_id=run_id,
            job_id=job_id,
        )
        return self.repository.create_industry_context_snapshot(context)

    def _extract_active_drivers(self, items: list[object]) -> list[dict[str, object]]:
        counts: dict[str, dict[str, object]] = {}
        for raw_item in items:
            text = self._item_text(raw_item).lower()
            if not text:
                continue
            matched: set[str] = set()
            for phrase, key in INDUSTRY_THEME_MAP.items():
                if phrase in text:
                    matched.add(key)
            for key in matched:
                entry = counts.setdefault(key, {"key": key, "evidence_count": 0, "evidence_samples": []})
                entry["evidence_count"] = int(entry["evidence_count"]) + 1
                samples = entry["evidence_samples"]
                if isinstance(samples, list) and len(samples) < 3:
                    samples.append(self._item_text(raw_item)[:160])
        results = []
        for key, payload in counts.items():
            results.append(
                {
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "evidence_count": payload["evidence_count"],
                    "evidence_samples": payload["evidence_samples"],
                }
            )
        results.sort(key=lambda item: int(item.get("evidence_count", 0)), reverse=True)
        return results[:5]

    def _linked_macro_themes(self, items: list[object]) -> list[str]:
        linked: list[str] = []
        for raw_item in items:
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
    def _saliency_score(active_drivers: list[dict[str, object]], item_count: int, macro_link_count: int) -> float:
        score = 0.14 + (len(active_drivers) * 0.13) + (min(item_count, 8) * 0.04) + (macro_link_count * 0.05)
        return round(min(1.0, score), 3)

    @staticmethod
    def _confidence_percent(active_drivers: list[dict[str, object]], item_count: int, diagnostics: dict[str, object]) -> float:
        provider_count = len(diagnostics.get("providers", [])) if isinstance(diagnostics, dict) and isinstance(diagnostics.get("providers"), list) else 0
        confidence = 24.0 + (len(active_drivers) * 9.0) + (min(item_count, 6) * 6.0) + (provider_count * 4.0)
        return round(min(90.0, confidence), 1)

    @staticmethod
    def _summary_text(
        previous: IndustryContextSnapshot | None,
        industry_label: str,
        active_drivers: list[dict[str, object]],
        linked_macro_themes: list[str],
    ) -> str:
        driver_labels = [str(item.get("label", "")).strip() for item in active_drivers if item.get("label")]
        focus = ", ".join(driver_labels[:2]) if driver_labels else "no dominant industry-native driver"
        macro = ", ".join(linked_macro_themes[:2]) if linked_macro_themes else "limited visible macro transmission"
        if previous and previous.summary_text and driver_labels:
            return f"{industry_label} remains driven by {focus}, with macro read-through still centered on {macro}."
        if driver_labels:
            return f"{industry_label} context is led by {focus}, while macro transmission points to {macro}."
        if previous and previous.summary_text:
            return f"{industry_label} context is broadly unchanged, but this run did not surface a clearly dominant fresh driver."
        return f"{industry_label} context is currently light on salient evidence, so the output mainly records continuity and known macro links."

    @staticmethod
    def _item_text(raw_item: object) -> str:
        if not isinstance(raw_item, dict):
            return ""
        title = raw_item.get("title")
        body = raw_item.get("body")
        parts = [part.strip() for part in [title, body] if isinstance(part, str) and part.strip()]
        return " — ".join(parts)


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
