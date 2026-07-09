#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from statistics import mean
from typing import Any

from sqlalchemy import create_engine, text

from trade_proposer_app.config import settings


def _json(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pct(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * percentile / 100.0
    floor = math.floor(k)
    ceil = math.ceil(k)
    if floor == ceil:
        return ordered[floor]
    return ordered[floor] * (ceil - k) + ordered[ceil] * (k - floor)


def _score_value(source: dict[str, Any]) -> float:
    value = source.get("support_score")
    if value is None:
        value = source.get("context_score")
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _label_value(source: dict[str, Any]) -> str:
    return str(source.get("support_label") or source.get("context_label") or "NEUTRAL").upper()


def _snapshot_summary(rows: list[tuple[Any, ...]], *, scope: str) -> dict[str, Any]:
    labels: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    evidence: Counter[str] = Counter()
    score_versions: Counter[str] = Counter()
    news_counts: list[float] = []
    scores: list[float] = []
    directional_confidence: list[float] = []
    neutral_reasons: Counter[str] = Counter()
    for row in rows:
        source = _json(row[0])
        labels[_label_value(source)] += 1
        quality[str(source.get("context_quality_status") or "unknown")] += 1
        evidence[str(source.get("evidence_state") or "unknown")] += 1
        score_versions[str(source.get("score_version") or "legacy")] += 1
        news_counts.append(float(source.get("primary_news_item_count") or 0.0))
        score = _score_value(source)
        scores.append(score)
        try:
            directional_confidence.append(float(source.get("directional_confidence_percent") or 0.0))
        except (TypeError, ValueError):
            directional_confidence.append(0.0)
        if abs(score) <= 0.01:
            for reason in source.get("score_reasons") or []:
                neutral_reasons[str(reason)] += 1
    total = len(rows)
    return {
        "scope": scope,
        "snapshot_count": total,
        "labels": dict(labels.most_common()),
        "quality": dict(quality.most_common()),
        "evidence": dict(evidence.most_common()),
        "score_versions": dict(score_versions.most_common()),
        "primary_news_avg": round(mean(news_counts), 2) if news_counts else None,
        "primary_news_p50": _pct(news_counts, 50),
        "zero_primary_news_percent": round(100.0 * sum(value == 0 for value in news_counts) / total, 2) if total else None,
        "non_zero_score_percent": round(100.0 * sum(abs(value) > 0.01 for value in scores) / total, 2) if total else None,
        "avg_abs_score": round(mean(abs(value) for value in scores), 4) if scores else None,
        "directional_confidence_avg": round(mean(directional_confidence), 2) if directional_confidence else None,
        "neutral_reasons": dict(neutral_reasons.most_common(10)),
    }


def _ablation_adjustment(transmission: dict[str, Any], *, mode: str) -> float:
    actual = transmission.get("transmission_confidence_adjustment")
    actual_value = float(actual) if isinstance(actual, (int, float)) else 0.0
    if mode == "normal":
        return actual_value
    if mode == "forced_neutral":
        return 0.0
    quality = str(transmission.get("context_quality_status") or "").lower()
    macro_quality = str(transmission.get("macro_context_quality_status") or "").lower()
    industry_quality = str(transmission.get("industry_context_quality_status") or "").lower()
    if mode == "quality_only":
        if any(value in {"blocked", "failed"} for value in (quality, macro_quality, industry_quality)):
            return -2.0
        if any(value in {"degraded", "partial"} for value in (quality, macro_quality, industry_quality)):
            return -1.0
        return 0.0
    bias = str(transmission.get("transmission_bias") or transmission.get("context_bias") or "").lower()
    if mode == "adverse_only":
        return actual_value if actual_value < 0 or bias == "headwind" else 0.0
    if mode == "mapped_exposure":
        mapped = transmission.get("mapped_exposure") if isinstance(transmission.get("mapped_exposure"), dict) else {}
        alignment = mapped.get("alignment_percent", transmission.get("alignment_percent"))
        try:
            alignment_value = float(alignment)
        except (TypeError, ValueError):
            return 0.0
        if alignment_value >= 62:
            return min(2.0, (alignment_value - 50.0) / 20.0)
        if alignment_value <= 42:
            return max(-4.0, (alignment_value - 50.0) / 10.0)
        return 0.0
    return actual_value


def _plan_context_summary(rows: list[tuple[Any, ...]], *, ablation_mode: str = "normal") -> dict[str, Any]:
    actions: Counter[str] = Counter()
    macro_scores: list[float] = []
    industry_scores: list[float] = []
    transmission_bias: Counter[str] = Counter()
    action_reasons: Counter[str] = Counter()
    adjustments: list[float] = []
    for action, signal_breakdown_json, evidence_summary_json in rows:
        actions[str(action)] += 1
        signal = _json(signal_breakdown_json)
        evidence = _json(evidence_summary_json)
        try:
            macro_scores.append(float(signal.get("macro_exposure_score") or 0.0))
            industry_scores.append(float(signal.get("industry_alignment_score") or 0.0))
        except (TypeError, ValueError):
            pass
        transmission = signal.get("transmission_summary") if isinstance(signal.get("transmission_summary"), dict) else {}
        transmission_bias[str(transmission.get("transmission_bias") or "unknown")] += 1
        adjustments.append(_ablation_adjustment(transmission, mode=ablation_mode))
        action_reasons[str(evidence.get("action_reason") or evidence.get("decision_reason") or "unknown")] += 1
    total = len(rows)
    return {
        "plan_count": total,
        "actions": dict(actions.most_common()),
        "macro_exposure_non_neutral_percent": round(100.0 * sum(abs(value - 50.0) > 1.0 for value in macro_scores) / len(macro_scores), 2) if macro_scores else None,
        "industry_alignment_non_neutral_percent": round(100.0 * sum(abs(value - 50.0) > 1.0 for value in industry_scores) / len(industry_scores), 2) if industry_scores else None,
        "transmission_bias": dict(transmission_bias.most_common()),
        "action_reasons": dict(action_reasons.most_common(10)),
        "ablation_mode": ablation_mode,
        "transmission_adjustment_avg": round(mean(adjustments), 3) if adjustments else None,
        "transmission_adjustment_non_zero_percent": round(100.0 * sum(abs(value) > 0.001 for value in adjustments) / len(adjustments), 2) if adjustments else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report macro/industry context scoring coverage and downstream impact.")
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--plan-limit", type=int, default=10000)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--ablation-mode",
        choices=["normal", "forced_neutral", "quality_only", "adverse_only", "mapped_exposure"],
        default="normal",
        help="Summarize plan transmission impact under a context ablation mode.",
    )
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    with engine.connect() as conn:
        macro_rows = list(conn.execute(text("select source_breakdown_json from macro_context_snapshots")))
        industry_rows = list(conn.execute(text("select source_breakdown_json from industry_context_snapshots")))
        plan_rows = list(
            conn.execute(
                text(
                    "select action, signal_breakdown_json, evidence_summary_json "
                    "from recommendation_plans order by computed_at desc limit :limit"
                ),
                {"limit": args.plan_limit},
            )
        )

    payload = {
        "macro": _snapshot_summary(macro_rows, scope="macro"),
        "industry": _snapshot_summary(industry_rows, scope="industry"),
        "plans": _plan_context_summary(plan_rows, ablation_mode=args.ablation_mode),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
