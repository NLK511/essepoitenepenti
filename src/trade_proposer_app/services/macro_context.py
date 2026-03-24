from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.domain.models import MacroContextSnapshot, SentimentSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository

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


class MacroContextService:
    def __init__(self, repository: ContextSnapshotRepository) -> None:
        self.repository = repository

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
        items = social_items if isinstance(social_items, list) else []
        active_themes = self._extract_themes(items)
        warnings = []
        missing_inputs = []
        if not items:
            warnings.append("macro context built without matched social evidence; output is low-confidence and saliency-light")
        warnings.append("macro context currently relies on social evidence first; primary-news/official-source writer still pending")
        if not source_breakdown or not (source_breakdown.get("news") if isinstance(source_breakdown, dict) else None):
            missing_inputs.append("primary_news_evidence")
        sentiment_score = float(getattr(snapshot, "score", 0.0) or 0.0)
        sentiment_label = str(getattr(snapshot, "label", "NEUTRAL") or "NEUTRAL")
        regime_tags = self._regime_tags(active_themes, sentiment_score, sentiment_label)
        saliency_score = self._saliency_score(active_themes, len(items), abs(sentiment_score))
        confidence_percent = self._confidence_percent(active_themes, len(items), diagnostics)
        summary_text = self._summary_text(previous, active_themes, warnings)
        context = MacroContextSnapshot(
            computed_at=datetime.now(timezone.utc),
            status="warning" if warnings else "ok",
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
                "social_item_count": len(items),
                "providers": diagnostics.get("providers", []) if isinstance(diagnostics, dict) else [],
                "upstream": source_breakdown if isinstance(source_breakdown, dict) else {},
            },
            metadata={
                "subject_key": getattr(snapshot, "subject_key", None),
                "subject_label": getattr(snapshot, "subject_label", None),
                "query_diagnostics": diagnostics.get("query_diagnostics", {}) if isinstance(diagnostics, dict) else {},
                "top_evidence_titles": [self._item_text(item)[:140] for item in items[:5]],
            },
            run_id=run_id,
            job_id=job_id,
        )
        return self.repository.create_macro_context_snapshot(context)

    def _extract_themes(self, items: list[object]) -> list[dict[str, object]]:
        themes: list[dict[str, object]] = []
        for key, (label, phrases, regime_tags) in MACRO_THEME_MAP.items():
            evidence: list[str] = []
            hit_count = 0
            for raw_item in items:
                text = self._item_text(raw_item).lower()
                if not text:
                    continue
                if any(phrase in text for phrase in phrases):
                    hit_count += 1
                    if len(evidence) < 3:
                        evidence.append(self._item_text(raw_item)[:160])
            if hit_count == 0:
                continue
            themes.append(
                {
                    "key": key,
                    "label": label,
                    "evidence_count": hit_count,
                    "saliency_weight": round(min(1.0, 0.35 + (hit_count * 0.15)), 3),
                    "regime_tags": regime_tags,
                    "evidence_samples": evidence,
                }
            )
        themes.sort(key=lambda item: (int(item.get("evidence_count", 0)), float(item.get("saliency_weight", 0.0))), reverse=True)
        return themes[:5]

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
    def _saliency_score(active_themes: list[dict[str, object]], item_count: int, sentiment_magnitude: float) -> float:
        score = 0.15 + (len(active_themes) * 0.14) + (min(item_count, 8) * 0.04) + (sentiment_magnitude * 0.2)
        return round(min(1.0, score), 3)

    @staticmethod
    def _confidence_percent(active_themes: list[dict[str, object]], item_count: int, diagnostics: dict[str, object]) -> float:
        provider_count = len(diagnostics.get("providers", [])) if isinstance(diagnostics, dict) and isinstance(diagnostics.get("providers"), list) else 0
        confidence = 22.0 + (len(active_themes) * 10.0) + (min(item_count, 6) * 6.0) + (provider_count * 4.0)
        return round(min(90.0, confidence), 1)

    @staticmethod
    def _summary_text(
        previous: MacroContextSnapshot | None,
        active_themes: list[dict[str, object]],
        warnings: list[str],
    ) -> str:
        theme_labels = [str(item.get("label", "")).strip() for item in active_themes if item.get("label")]
        focus = ", ".join(theme_labels[:2]) if theme_labels else "no dominant macro theme"
        if previous and previous.summary_text and theme_labels:
            return f"Backdrop stays centered on {focus}. Relative to the prior run, the main emphasis remains continuity rather than regime change."
        if previous and previous.summary_text:
            return "Backdrop is broadly unchanged, but the current run did not surface a clearly dominant macro theme."
        if theme_labels:
            return f"Macro context is currently led by {focus}, with the run pointing more to saliency than to a clean directional regime."
        if warnings:
            return "Macro context evidence is light in this run, so the output is mainly a continuity placeholder rather than a strong regime call."
        return "Macro context remains mixed without one clearly dominant theme."

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
