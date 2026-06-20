from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import select

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.services.taxonomy import TickerTaxonomyService
from trade_proposer_app.services.ticker_exposure_ontology import TickerExposureOntologyService


def _json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _bias(alignment: float) -> str:
    if alignment >= 62.0:
        return "tailwind"
    if alignment <= 42.0:
        return "headwind"
    return "mixed"


def evaluate(limit: int) -> dict[str, Any]:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(RecommendationPlanRecord).order_by(RecommendationPlanRecord.created_at.desc()).limit(limit)
        ).all()
    finally:
        session.close()

    old_bias = Counter()
    new_bias = Counter()
    coverage = Counter()
    support = Counter()
    prospective_coverage = Counter()
    prospective_source = Counter()
    taxonomy = TickerTaxonomyService()
    ontology_service = TickerExposureOntologyService()
    matched = 0
    adjusted = 0
    adjustments: list[float] = []
    examples: list[dict[str, Any]] = []

    seen_tickers: set[str] = set()
    for row in rows:
        ticker = str(row.ticker or "").strip().upper()
        if ticker and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            prospective_profile = ontology_service.get_profile(ticker, taxonomy_profile=taxonomy.get_ticker_profile(ticker))
            prospective_coverage[ontology_service._coverage_status(prospective_profile)] += 1
            prospective_source[str(prospective_profile.get("source") or "unknown")] += 1
        breakdown = _json_dict(row.signal_breakdown_json)
        transmission = breakdown.get("transmission_summary") if isinstance(breakdown.get("transmission_summary"), dict) else {}
        if not transmission:
            continue
        current_alignment = float(transmission.get("alignment_percent", 0.0) or 0.0)
        pre_alignment = float(transmission.get("pre_ontology_alignment_percent", current_alignment) or current_alignment)
        old_bias[_bias(pre_alignment)] += 1
        new_bias[_bias(current_alignment)] += 1
        ontology = transmission.get("ontology_context") if isinstance(transmission.get("ontology_context"), dict) else {}
        if ontology:
            coverage[str(ontology.get("coverage_status") or "missing")] += 1
            support[str(ontology.get("directional_support") or "unknown")] += 1
            match_count = int(ontology.get("matched_exposure_count", 0) or 0)
            if match_count > 0:
                matched += 1
            adjustment = float(ontology.get("alignment_adjustment_percent", 0.0) or 0.0)
            adjustments.append(adjustment)
            if abs(adjustment) > 0.01:
                adjusted += 1
                if len(examples) < 10:
                    examples.append(
                        {
                            "plan_id": row.id,
                            "ticker": row.ticker,
                            "old_alignment": round(pre_alignment, 2),
                            "new_alignment": round(current_alignment, 2),
                            "old_bias": _bias(pre_alignment),
                            "new_bias": _bias(current_alignment),
                            "ontology_support": ontology.get("directional_support"),
                            "adjustment": adjustment,
                            "paths": ontology.get("transmission_paths", [])[:3],
                        }
                    )
        else:
            coverage["missing"] += 1

    total = sum(old_bias.values())
    return {
        "sampled_plan_count": len(rows),
        "plans_with_transmission": total,
        "old_bias_counts": dict(old_bias),
        "ontology_enhanced_bias_counts": dict(new_bias),
        "old_mixed_rate": round(old_bias["mixed"] / total, 4) if total else None,
        "ontology_enhanced_mixed_rate": round(new_bias["mixed"] / total, 4) if total else None,
        "ontology_coverage_counts": dict(coverage),
        "ontology_support_counts": dict(support),
        "prospective_unique_ticker_count": len(seen_tickers),
        "prospective_unique_ticker_coverage_counts": dict(prospective_coverage),
        "prospective_unique_ticker_source_counts": dict(prospective_source),
        "matched_exposure_plan_count": matched,
        "adjusted_plan_count": adjusted,
        "average_alignment_adjustment": round(mean(adjustments), 4) if adjustments else None,
        "examples": examples,
        "assessment": _assessment(total, old_bias, new_bias, coverage, matched, adjusted),
    }


def _assessment(total: int, old_bias: Counter, new_bias: Counter, coverage: Counter, matched: int, adjusted: int) -> str:
    if total <= 0:
        return "insufficient persisted transmission data"
    old_mixed = old_bias["mixed"] / total
    new_mixed = new_bias["mixed"] / total
    usable = coverage["usable"] / total if total else 0.0
    matched_rate = matched / total if total else 0.0
    if usable >= 0.2 and matched_rate > 0 and new_mixed < old_mixed:
        return "ontology is directionally better than old context labeling on coverage and mixed-bias reduction, but outcome validation is still required"
    if usable > 0 and matched_rate > 0:
        return "ontology adds auditable exposure matches, but this sample does not yet prove better directional separation"
    return "ontology plumbing is present but this sample does not show enough usable matches yet"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ticker exposure ontology effectiveness on recent persisted plans.")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.limit)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
