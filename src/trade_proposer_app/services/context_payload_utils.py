from __future__ import annotations

from typing import Any


def macro_snapshot_context_fields(snapshot: dict[str, Any], existing_insights: list[object] | None = None) -> dict[str, Any]:
    return {
        "macro_sentiment_score": float(snapshot.get("score", 0.0) or 0.0),
        "macro_sentiment_label": snapshot.get("label", "NEUTRAL"),
        "macro_context_score": float(snapshot.get("score", 0.0) or 0.0),
        "macro_context_label": snapshot.get("label", "NEUTRAL"),
        "macro_snapshot_id": snapshot.get("snapshot_id"),
        "macro_snapshot_subject_key": snapshot.get("subject_key"),
        "macro_snapshot_subject_label": snapshot.get("subject_label"),
        "macro_snapshot_source": snapshot.get("source", "snapshot"),
        "macro_snapshot_coverage": snapshot.get("coverage", {}),
        "macro_snapshot_source_breakdown": snapshot.get("source_breakdown", {}),
        "macro_snapshot_drivers": snapshot.get("drivers", []),
        "macro_context_snapshot_id": snapshot.get("context_snapshot_id"),
        "macro_context_status": snapshot.get("context_status"),
        "macro_context_summary": snapshot.get("context_summary"),
        "macro_context_saliency_score": float(snapshot.get("context_saliency_score", 0.0) or 0.0),
        "macro_context_confidence_percent": float(snapshot.get("context_confidence_percent", 0.0) or 0.0),
        "macro_context_quality_score": float(snapshot.get("context_quality_score", 0.0) or 0.0),
        "macro_context_quality_status": snapshot.get("context_quality_status"),
        "macro_context_quality_flags": snapshot.get("context_quality_flags", {}),
        "macro_context_quality_notes": snapshot.get("context_quality_notes", []),
        "macro_context_events": snapshot.get("context_active_events", []),
        "macro_context_active_themes": snapshot.get("context_active_themes", []),
        "macro_context_regime_tags": snapshot.get("context_regime_tags", []),
        "macro_context_lifecycle": snapshot.get("context_lifecycle", {}),
        "macro_context_contradictory_event_labels": snapshot.get("context_contradictory_event_labels", []),
        "macro_context_source_breakdown": snapshot.get("context_source_breakdown", {}),
        "macro_context_metadata": snapshot.get("context_metadata", {}),
        "macro_context_score_source": snapshot.get("context_score_source"),
        "macro_directional_confidence_percent": snapshot.get("directional_confidence_percent"),
        "macro_context_score_components": snapshot.get("score_components") or (snapshot.get("source_breakdown", {}) or {}).get("score_components", {}),
        "macro_context_score_reasons": snapshot.get("score_reasons") or (snapshot.get("source_breakdown", {}) or {}).get("score_reasons", []),
        "macro_coverage_insights": _merged_insights(existing_insights, snapshot),
    }


def industry_snapshot_context_fields(snapshot: dict[str, Any], existing_insights: list[object] | None = None) -> dict[str, Any]:
    return {
        "industry_sentiment_score": float(snapshot.get("score", 0.0) or 0.0),
        "industry_sentiment_label": snapshot.get("label", "NEUTRAL"),
        "industry_context_score": float(snapshot.get("score", 0.0) or 0.0),
        "industry_context_label": snapshot.get("label", "NEUTRAL"),
        "industry_snapshot_id": snapshot.get("snapshot_id"),
        "industry_snapshot_subject_key": snapshot.get("subject_key"),
        "industry_snapshot_subject_label": snapshot.get("subject_label"),
        "industry_snapshot_source": snapshot.get("source", "snapshot"),
        "industry_snapshot_coverage": snapshot.get("coverage", {}),
        "industry_snapshot_source_breakdown": snapshot.get("source_breakdown", {}),
        "industry_snapshot_drivers": snapshot.get("drivers", []),
        "industry_context_snapshot_id": snapshot.get("context_snapshot_id"),
        "industry_context_status": snapshot.get("context_status"),
        "industry_context_summary": snapshot.get("context_summary"),
        "industry_context_saliency_score": float(snapshot.get("context_saliency_score", 0.0) or 0.0),
        "industry_context_confidence_percent": float(snapshot.get("context_confidence_percent", 0.0) or 0.0),
        "industry_context_quality_score": float(snapshot.get("context_quality_score", 0.0) or 0.0),
        "industry_context_quality_status": snapshot.get("context_quality_status"),
        "industry_context_quality_flags": snapshot.get("context_quality_flags", {}),
        "industry_context_quality_notes": snapshot.get("context_quality_notes", []),
        "industry_context_evidence_state": snapshot.get("context_evidence_state"),
        "industry_context_coverage_state": snapshot.get("context_coverage_state"),
        "industry_context_events": snapshot.get("context_active_events", []),
        "industry_context_active_drivers": snapshot.get("context_active_drivers", []),
        "industry_context_regime_tags": snapshot.get("context_regime_tags", []),
        "industry_context_lifecycle": snapshot.get("context_lifecycle", {}),
        "industry_context_contradictory_event_labels": snapshot.get("context_contradictory_event_labels", []),
        "industry_context_source_breakdown": snapshot.get("context_source_breakdown", {}),
        "industry_context_metadata": snapshot.get("context_metadata", {}),
        "industry_context_score_source": (snapshot.get("context_metadata", {}) or {}).get("context_score_source"),
        "industry_directional_confidence_percent": snapshot.get("directional_confidence_percent"),
        "industry_context_score_components": snapshot.get("score_components") or (snapshot.get("source_breakdown", {}) or {}).get("score_components", {}),
        "industry_context_score_reasons": snapshot.get("score_reasons") or (snapshot.get("source_breakdown", {}) or {}).get("score_reasons", []),
        "industry_coverage_insights": _merged_insights(existing_insights, snapshot),
    }


def _merged_insights(existing_insights: list[object] | None, snapshot: dict[str, Any]) -> list[object]:
    diagnostics = snapshot.get("diagnostics", {}) or {}
    warnings = diagnostics.get("warnings", []) if isinstance(diagnostics, dict) else []
    return list(dict.fromkeys(list(existing_insights or []) + list(warnings)))
