#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trade_proposer_app.services.taxonomy import TAXONOMY_PATH, TickerTaxonomyService  # noqa: E402

REQUIRED_TICKER_FIELDS = ["company_name", "sector", "industry", "ticker_keywords"]
REQUIRED_INDUSTRY_FIELDS = ["label", "sector", "queries", "transmission_channels"]
VALID_RELATIONSHIP_TYPES = {
    "belongs_to_sector",
    "belongs_to_industry",
    "peer_of",
    "supplier_to",
    "customer_of",
    "benefits_from",
    "hurt_by",
    "sensitive_to",
    "exposed_to_theme",
    "linked_macro_channel",
}
VALID_RELATIONSHIP_TYPES.update({"sensitive_to", "benefits_from", "hurt_by"})


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    service = TickerTaxonomyService(TAXONOMY_PATH)

    raw_payload = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8")) if TAXONOMY_PATH.exists() else {}
    alias_to_tickers: dict[str, set[str]] = {}

    for ticker in sorted(service._taxonomy):
        profile = service.get_ticker_profile(ticker)
        for field in REQUIRED_TICKER_FIELDS:
            value = profile.get(field)
            if isinstance(value, list):
                if not value:
                    errors.append(f"ticker {ticker} missing required list field: {field}")
            elif not str(value or "").strip():
                errors.append(f"ticker {ticker} missing required field: {field}")
        for alias in profile.get("aliases", []):
            alias_to_tickers.setdefault(alias.lower(), set()).add(ticker)
        if not profile.get("ticker_keywords"):
            errors.append(f"ticker {ticker} has no ticker_keywords")
        for keyword in profile.get("ticker_keywords", []) + profile.get("industry_keywords", []):
            text = str(keyword).strip()
            if len(text) < 2:
                warnings.append(f"ticker {ticker} has very short keyword: {text!r}")

    for alias, tickers in sorted(alias_to_tickers.items()):
        if len(tickers) > 1:
            warnings.append(f"alias {alias!r} is shared across multiple tickers: {', '.join(sorted(tickers))}")

    industry_keys = set()
    for subject_key, definition in sorted(service._industries.items()):
        industry_keys.add(subject_key)
        normalized_key = service._normalize_subject_key(subject_key)
        if subject_key != normalized_key:
            errors.append(f"industry key {subject_key!r} is not normalized; expected {normalized_key!r}")
        for field in REQUIRED_INDUSTRY_FIELDS:
            value = definition.get(field)
            if isinstance(value, list):
                if not value:
                    errors.append(f"industry {subject_key} missing required list field: {field}")
            elif not str(value or "").strip():
                errors.append(f"industry {subject_key} missing required field: {field}")
        for ticker in definition.get("tickers", []):
            if ticker not in service._taxonomy:
                errors.append(f"industry {subject_key} references unknown ticker {ticker}")
        for peer in definition.get("peer_industries", []):
            if peer not in service._industries:
                warnings.append(f"industry {subject_key} references peer industry {peer!r} that is not explicitly defined")

    relationships = raw_payload.get("_relationships", []) if isinstance(raw_payload, dict) else []
    if not isinstance(relationships, list):
        errors.append("_relationships must be a list")
        relationships = []
    for index, relationship in enumerate(relationships, start=1):
        if not isinstance(relationship, dict):
            errors.append(f"relationship #{index} is not an object")
            continue
        relation_type = str(relationship.get("type", "")).strip()
        source = service._normalize_subject_key(relationship.get("source"))
        target = service._normalize_subject_key(relationship.get("target"))
        target_kind = str(relationship.get("target_kind", "industry")).strip() or "industry"
        if relation_type not in VALID_RELATIONSHIP_TYPES:
            warnings.append(f"relationship #{index} uses non-standard type {relation_type!r}")
        if source not in industry_keys:
            errors.append(f"relationship #{index} source {source!r} is not a defined industry key")
        if target_kind == "industry" and target not in industry_keys:
            errors.append(f"relationship #{index} target {target!r} is not a defined industry key")
        if not relation_type:
            errors.append(f"relationship #{index} missing type")

    print(f"Taxonomy file: {TAXONOMY_PATH}")
    print(f"Tickers: {len(service._taxonomy)}")
    print(f"Industries: {len(service._industries)}")
    print(f"Relationships: {len(service._relationships)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
