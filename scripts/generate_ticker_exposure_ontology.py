from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from trade_proposer_app.services.taxonomy import TICKERS_PATH
from trade_proposer_app.services.ticker_exposure_ontology import (
    ONTOLOGY_PATH,
    TickerExposureOntologyService,
)

CURATED_SOURCES = {"curated", "operator_curated", "provider_backed"}


def _string_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _generic_profile(ticker: str, taxonomy_profile: dict[str, Any]) -> dict[str, Any]:
    sector = str(taxonomy_profile.get("sector") or "").strip()
    industry = str(taxonomy_profile.get("industry") or "").strip()
    subindustry = str(taxonomy_profile.get("subindustry") or "").strip()
    company_name = str(taxonomy_profile.get("company_name") or ticker).strip() or ticker
    industry_keywords = _string_list(taxonomy_profile.get("industry_keywords"))[:8]
    macro_terms = _string_list(taxonomy_profile.get("macro_sensitivity"))[:8]
    event_terms = _string_list(taxonomy_profile.get("event_vocab"))[:10]
    demand_label = industry or sector or "business demand"
    return {
        "business_summary": f"{company_name} exposure profile generated from taxonomy classification: {subindustry or industry or sector or 'unknown industry'}.",
        "revenue_drivers": list(dict.fromkeys(industry_keywords[:3] + [demand_label]))[:4],
        "cost_drivers": ["input costs", "labor costs", "financing costs"],
        "customer_segments": [sector or industry or "end customers"],
        "geographic_exposure": [str(taxonomy_profile.get("region") or "global").strip() or "global"],
        "macro_sensitivities": [
            {
                "factor": term,
                "aliases": [term],
                "direction_if_factor_rises": "mixed",
                "strength": "low",
                "rationale": "taxonomy-derived macro sensitivity; directional impact requires further curation",
            }
            for term in macro_terms
        ],
        "event_sensitivities": [
            {
                "event": term,
                "aliases": [term],
                "direction_for_long": "mixed",
                "strength": "low",
                "rationale": "taxonomy-derived event vocabulary; directional impact requires further curation",
            }
            for term in event_terms
        ],
        "peers": _string_list(taxonomy_profile.get("peers"))[:12],
        "suppliers": _string_list(taxonomy_profile.get("suppliers"))[:12],
        "customers": _string_list(taxonomy_profile.get("customers"))[:12],
        "related_etfs": [],
        "setup_family_relevance": {},
        "confidence_score": 0.42,
        "source": "taxonomy_generated",
        "version": "taxonomy-generated-2026-06-v1",
        "updated_at": date.today().isoformat(),
    }


def _profile_for_ticker(ticker: str, taxonomy_profile: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    source = str(existing.get("source") or "").strip()
    if source in CURATED_SOURCES:
        preserved = deepcopy(existing)
        preserved.setdefault("version", "2026-06-ontology-v1")
        preserved.setdefault("updated_at", date.today().isoformat())
        return preserved
    template = TickerExposureOntologyService._template_profile(taxonomy_profile)
    if template:
        generated = {
            **_generic_profile(ticker, taxonomy_profile),
            **template,
            "source": "template_generated",
            "version": "taxonomy-generated-2026-06-v1",
            "updated_at": date.today().isoformat(),
        }
    else:
        generated = _generic_profile(ticker, taxonomy_profile)
    generated["peers"] = _string_list(taxonomy_profile.get("peers"))[:12]
    generated["suppliers"] = _string_list(taxonomy_profile.get("suppliers"))[:12]
    generated["customers"] = _string_list(taxonomy_profile.get("customers"))[:12]
    return generated


def generate(*, tickers_path: Path = TICKERS_PATH, ontology_path: Path = ONTOLOGY_PATH) -> dict[str, Any]:
    tickers_payload = json.loads(tickers_path.read_text(encoding="utf-8"))
    existing_payload = json.loads(ontology_path.read_text(encoding="utf-8")) if ontology_path.exists() else {}
    output: dict[str, Any] = {
        "_meta": {
            "version": "taxonomy-generated-2026-06-v1",
            "description": "Complete ticker exposure ontology generated from taxonomy classifications with curated overrides preserved.",
            "generated_at": date.today().isoformat(),
            "ticker_count": 0,
        }
    }
    for ticker in sorted(key for key, value in tickers_payload.items() if not key.startswith("_") and isinstance(value, dict)):
        taxonomy_profile = tickers_payload[ticker]
        existing = existing_payload.get(ticker, {}) if isinstance(existing_payload.get(ticker), dict) else {}
        output[ticker] = _profile_for_ticker(ticker, taxonomy_profile, existing)
    output["_meta"]["ticker_count"] = len(output) - 1
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate complete ticker exposure ontology from taxonomy tickers.")
    parser.add_argument("--output", type=Path, default=ONTOLOGY_PATH)
    args = parser.parse_args()
    payload = generate(ontology_path=args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["_meta"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
