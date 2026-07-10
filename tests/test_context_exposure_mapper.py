from __future__ import annotations

from trade_proposer_app.domain.enums import RecommendationDirection
from trade_proposer_app.services.context_exposure_mapper import ContextExposureMapper


def test_context_exposure_mapper_maps_direct_tailwind_and_preserves_raw_support() -> None:
    mapper = ContextExposureMapper()

    result = mapper.map_context(
        ticker="AMAT",
        context={
            "macro_context_score": 0.35,
            "industry_context_score": 0.45,
            "macro_context_evidence_state": "usable",
            "industry_context_evidence_state": "usable",
            "macro_context_quality_status": "usable",
            "industry_context_quality_status": "usable",
            "macro_context_events": [{"label": "AI capex and semiconductor demand improve"}],
            "industry_context_events": [{"label": "Fab expansion supports wafer equipment orders"}],
        },
        direction=RecommendationDirection.LONG,
    )

    assert result.exposure_bias == "tailwind"
    assert result.raw_support_score > 0
    assert result.raw_support_percent > 50
    assert result.alignment_percent > result.raw_support_percent
    assert result.matched_exposure_paths
    assert result.neutral_reason is None


def test_context_exposure_mapper_inverts_context_for_short_direction() -> None:
    mapper = ContextExposureMapper()

    result = mapper.map_context(
        ticker="AMAT",
        context={
            "macro_context_score": 0.35,
            "industry_context_score": 0.45,
            "macro_context_evidence_state": "usable",
            "industry_context_evidence_state": "usable",
            "macro_context_quality_status": "usable",
            "industry_context_quality_status": "usable",
            "macro_context_events": [{"label": "AI capex and semiconductor demand improve"}],
            "industry_context_events": [{"label": "Fab expansion supports wafer equipment orders"}],
        },
        direction=RecommendationDirection.SHORT,
    )

    assert result.raw_support_score > 0
    assert result.raw_support_percent < 50
    assert result.exposure_bias in {"headwind", "mixed"}


def test_context_exposure_mapper_keeps_missing_or_unmapped_context_neutral() -> None:
    mapper = ContextExposureMapper()

    result = mapper.map_context(
        ticker="ZZZZ",
        context={
            "macro_context_score": 0.9,
            "industry_context_score": 0.9,
            "macro_context_quality_status": "usable",
        },
        direction=RecommendationDirection.LONG,
        taxonomy_profile={},
    )

    assert result.exposure_bias == "unknown"
    assert result.alignment_percent == 50.0
    assert result.neutral_reason in {"missing_context_evidence", "missing_exposure_mapping"}


def test_context_exposure_mapper_zeroes_degraded_industry_positive_support() -> None:
    mapper = ContextExposureMapper()

    result = mapper.map_context(
        ticker="AMAT",
        context={
            "macro_context_score": 0.0,
            "industry_context_score": 0.9,
            "industry_context_evidence_state": "usable",
            "industry_context_quality_status": "degraded",
            "industry_context_events": [{"label": "Fab expansion supports wafer equipment orders"}],
        },
        direction=RecommendationDirection.LONG,
    )

    assert result.industry_support_score == 0.0
    assert result.raw_support_score == 0.0
    assert result.exposure_bias in {"neutral", "mixed"}
    assert result.exposure_bias != "tailwind"


def test_context_exposure_mapper_surfaces_mixed_conflicts_as_neutral_reason() -> None:
    mapper = ContextExposureMapper()

    result = mapper.map_context(
        ticker="AAPL",
        context={
            "macro_context_score": 0.0,
            "industry_context_score": 0.0,
            "macro_context_evidence_state": "mixed",
            "macro_context_quality_status": "usable",
            "market_intelligence_conflict_flags": ["consumer_demand_mixed"],
            "macro_context_events": [{"label": "consumer spending improves but input costs rise"}],
        },
        direction=RecommendationDirection.LONG,
    )

    assert result.exposure_bias in {"mixed", "neutral"}
    assert "consumer_demand_mixed" in result.conflict_flags
    assert result.neutral_reason == "mixed_or_conflicting_context"
