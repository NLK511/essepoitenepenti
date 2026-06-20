from __future__ import annotations

from trade_proposer_app.domain.enums import RecommendationDirection
from trade_proposer_app.services.ticker_exposure_ontology import TickerExposureOntologyService
from trade_proposer_app.services.watchlist_transmission import WatchlistTransmissionService


class _Owner:
    @staticmethod
    def _pluck(payload, *keys):
        current = payload
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _is_number(value):
        return isinstance(value, (int, float))

    @staticmethod
    def _string_value(value, *, default=""):
        text = str(value or "").strip()
        return text or default

    @staticmethod
    def _detail_fallback(values):
        return [{"key": str(value), "label": str(value)} for value in values]

    @staticmethod
    def _channel_detail_fallback(values):
        return [{"key": str(value), "label": str(value)} for value in values]

    @staticmethod
    def _relationship_detail_fallback(values):
        return [{"key": str(index), "label": str(value.get("target_label") or value.get("target") or index)} for index, value in enumerate(values) if isinstance(value, dict)]

    @staticmethod
    def _transmission_bias(analysis):
        transmission = analysis["ticker_deep_analysis"]["transmission_analysis"]
        value = float(transmission.get("alignment_percent", 0.0))
        if value >= 62.0:
            return "tailwind"
        if value <= 42.0:
            return "headwind"
        return "mixed"

    @staticmethod
    def _transmission_bias_detail(value):
        return {"key": value, "label": value}

    @staticmethod
    def _fallback_transmission_window(signal):
        return "1d_2d"

    @staticmethod
    def _transmission_window_detail(value):
        return {"key": value, "label": value}

    @staticmethod
    def _fallback_decay_state(signal):
        return "new"


class _Signal:
    catalyst_score = 0.0
    macro_exposure_score = 0.0
    industry_alignment_score = 0.0
    diagnostics = {}


def test_exposure_ontology_scores_semiconductor_capex_tailwind() -> None:
    service = TickerExposureOntologyService()

    result = service.assess_context(
        "AMAT",
        {
            "macro_context_events": [
                {"key": "semiconductor_capex", "label": "Foundry spending and wafer fab equipment orders improve"}
            ],
            "industry_context_events": [
                {"key": "fab_expansion", "label": "Fab expansion supports chip equipment orders"}
            ],
        },
        direction=RecommendationDirection.LONG,
    )

    assert result["coverage_status"] == "usable"
    assert result["directional_support"] == "supports_long"
    assert result["matched_exposure_count"] >= 1
    assert result["alignment_adjustment_percent"] > 0
    assert "semiconductor_capex_cycle" in result["transmission_paths"][0]


def test_exposure_ontology_scores_airline_fuel_headwind() -> None:
    service = TickerExposureOntologyService()

    result = service.assess_context(
        "DAL",
        {"macro_context_events": [{"key": "oil", "label": "Oil prices and jet fuel costs rise"}]},
        direction=RecommendationDirection.LONG,
    )

    assert result["coverage_status"] == "usable"
    assert result["directional_support"] == "against_long"
    assert result["alignment_adjustment_percent"] < 0


def test_missing_explicit_ontology_is_degraded_and_neutral() -> None:
    service = TickerExposureOntologyService()

    result = service.assess_context(
        "ZZZZ",
        {"macro_context_events": [{"label": "generic rates headline"}]},
        direction=RecommendationDirection.LONG,
        taxonomy_profile={"macro_sensitivity": ["rates"]},
    )

    assert result["coverage_status"] == "degraded"
    assert result["source"] == "taxonomy_derived"
    assert result["directional_support"] in {"mixed", "unknown"}
    assert result["alignment_adjustment_percent"] == 0.0
    assert result["warnings"]


def test_watchlist_transmission_surfaces_ontology_context() -> None:
    service = WatchlistTransmissionService(_Owner())
    ontology_context = {
        "coverage_status": "usable",
        "directional_support": "supports_long",
        "alignment_adjustment_percent": 2.5,
        "transmission_paths": ["AI_capex -> macro_sensitivity -> positive_long_context"],
    }

    summary = service.transmission_summary(
        _Signal(),
        {
            "ticker_deep_analysis": {
                "transmission_analysis": {
                    "alignment_percent": 64.0,
                    "pre_ontology_alignment_percent": 61.5,
                    "ontology_context": ontology_context,
                    "context_quality_status": "ok",
                    "macro_context_quality_status": "ok",
                    "industry_context_quality_status": "ok",
                }
            }
        },
        candidate=None,
    )

    assert summary["context_bias"] == "tailwind"
    assert summary["pre_ontology_alignment_percent"] == 61.5
    assert summary["ontology_context"] == ontology_context
