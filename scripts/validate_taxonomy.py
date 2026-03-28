#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trade_proposer_app.services.taxonomy import (  # noqa: E402
    EVENT_VOCAB_PATH,
    INDUSTRIES_PATH,
    RELATIONSHIPS_PATH,
    SECTORS_PATH,
    TICKERS_PATH,
    THEMES_PATH,
    MACRO_CHANNELS_PATH,
    RELATIONSHIP_TARGET_KINDS_PATH,
    RELATIONSHIP_TYPES_PATH,
    TRANSMISSION_CHANNELS_PATH,
    TRANSMISSION_CONFLICT_FLAGS_PATH,
    TRANSMISSION_CONTEXT_REGIMES_PATH,
    TRANSMISSION_PRIMARY_DRIVERS_PATH,
    TRANSMISSION_TAGS_PATH,
    TAXONOMY_DIR,
    TAXONOMY_PATH,
    TickerTaxonomyService,
)

REQUIRED_TICKER_FIELDS = ["company_name", "sector", "industry", "ticker_keywords"]
REQUIRED_INDUSTRY_FIELDS = ["label", "sector", "queries", "transmission_channels"]


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    service = TickerTaxonomyService()
    alias_to_tickers: dict[str, set[str]] = {}

    expected_paths = [TICKERS_PATH, INDUSTRIES_PATH, SECTORS_PATH, RELATIONSHIPS_PATH, EVENT_VOCAB_PATH, THEMES_PATH, MACRO_CHANNELS_PATH, TRANSMISSION_CHANNELS_PATH, TRANSMISSION_TAGS_PATH, TRANSMISSION_PRIMARY_DRIVERS_PATH, TRANSMISSION_CONFLICT_FLAGS_PATH, TRANSMISSION_CONTEXT_REGIMES_PATH, RELATIONSHIP_TYPES_PATH, RELATIONSHIP_TARGET_KINDS_PATH]
    split_mode = all(path.exists() for path in expected_paths)
    if not split_mode and not TAXONOMY_PATH.exists():
        errors.append(f"no taxonomy source found; expected split files in {TAXONOMY_DIR} or fallback file {TAXONOMY_PATH}")

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
        for keyword in profile.get("ticker_keywords", []) + profile.get("industry_keywords", []):
            text = str(keyword).strip()
            if len(text) < 2:
                warnings.append(f"ticker {ticker} has very short keyword: {text!r}")
        raw_profile = service._taxonomy.get(ticker, {})
        for raw_theme in raw_profile.get("themes", []):
            definition = service.get_theme_definition(str(raw_theme))
            if not definition.get("label") or definition.get("key") not in service._themes:
                errors.append(f"ticker {ticker} uses ungoverned theme {raw_theme!r}")
        for raw_macro in raw_profile.get("macro_sensitivity", []):
            definition = service.get_macro_channel_definition(str(raw_macro))
            if not definition.get("label") or definition.get("key") not in service._macro_channels:
                errors.append(f"ticker {ticker} uses ungoverned macro channel {raw_macro!r}")
        for raw_channel in raw_profile.get("exposure_channels", []):
            definition = service.get_transmission_channel_definition(str(raw_channel))
            if not definition.get("label") or definition.get("key") not in service._transmission_channels:
                errors.append(f"ticker {ticker} uses ungoverned transmission channel {raw_channel!r}")

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
        for raw_theme in (service._industries.get(subject_key, {}) or {}).get("themes", []):
            theme_definition = service.get_theme_definition(str(raw_theme))
            if theme_definition.get("key") not in service._themes:
                errors.append(f"industry {subject_key} uses ungoverned theme {raw_theme!r}")
        for raw_macro in (service._industries.get(subject_key, {}) or {}).get("macro_sensitivity", []):
            macro_definition = service.get_macro_channel_definition(str(raw_macro))
            if macro_definition.get("key") not in service._macro_channels:
                errors.append(f"industry {subject_key} uses ungoverned macro channel {raw_macro!r}")
        for raw_channel in (service._industries.get(subject_key, {}) or {}).get("transmission_channels", []):
            channel_definition = service.get_transmission_channel_definition(str(raw_channel))
            if channel_definition.get("key") not in service._transmission_channels:
                errors.append(f"industry {subject_key} uses ungoverned transmission channel {raw_channel!r}")

    for sector_key, definition in sorted(service._sectors.items()):
        normalized_key = service._normalize_subject_key(sector_key)
        if sector_key != normalized_key:
            errors.append(f"sector key {sector_key!r} is not normalized; expected {normalized_key!r}")
        if not str(definition.get("label", "")).strip():
            errors.append(f"sector {sector_key} missing label")
        for raw_theme in (service._sectors.get(sector_key, {}) or {}).get("themes", []):
            theme_definition = service.get_theme_definition(str(raw_theme))
            if theme_definition.get("key") not in service._themes:
                errors.append(f"sector {sector_key} uses ungoverned theme {raw_theme!r}")
        for raw_macro in (service._sectors.get(sector_key, {}) or {}).get("macro_sensitivity", []):
            macro_definition = service.get_macro_channel_definition(str(raw_macro))
            if macro_definition.get("key") not in service._macro_channels:
                errors.append(f"sector {sector_key} uses ungoverned macro channel {raw_macro!r}")

    valid_relationship_types = set(service._relationship_types)
    valid_target_kinds = set(service._relationship_target_kinds)
    sector_keys = set(service._sectors)
    for index, relationship in enumerate(service._relationships, start=1):
        relation_type = str(relationship.get("type", "")).strip()
        source = service._normalize_subject_key(relationship.get("source"))
        target = str(relationship.get("target", "")).strip()
        target_kind = str(relationship.get("target_kind", "industry")).strip() or "industry"
        if relation_type not in valid_relationship_types:
            errors.append(f"relationship #{index} type {relation_type!r} is not a governed relationship type")
        if target_kind not in valid_target_kinds:
            errors.append(f"relationship #{index} target kind {target_kind!r} is not a governed relationship target kind")
        if source not in industry_keys and source not in sector_keys:
            errors.append(f"relationship #{index} source {source!r} is not a defined industry or sector key")
        if target_kind == "industry" and target not in industry_keys:
            errors.append(f"relationship #{index} target {target!r} is not a defined industry key")
        if target_kind == "sector" and target not in sector_keys:
            errors.append(f"relationship #{index} target {target!r} is not a defined sector key")
        if target_kind == "macro_channel" and target not in service._macro_channels:
            errors.append(f"relationship #{index} target {target!r} is not a governed macro channel")
        if target_kind == "theme" and target not in service._themes:
            errors.append(f"relationship #{index} target {target!r} is not a governed theme")
        if target_kind == "ticker" and target not in service._taxonomy:
            errors.append(f"relationship #{index} target {target!r} is not a known ticker")
        channel = str(relationship.get("channel", "")).strip()
        if channel:
            channel_definition = service.get_transmission_channel_definition(channel)
            if channel_definition.get("key") not in service._transmission_channels:
                errors.append(f"relationship #{index} channel {channel!r} is not a governed transmission channel")
        if not relation_type:
            errors.append(f"relationship #{index} missing type")

    for vocab_key, vocab_values in sorted(service._event_vocab.items()):
        if vocab_key not in industry_keys:
            warnings.append(f"event vocab group {vocab_key!r} is not a defined industry key")
        if not vocab_values:
            warnings.append(f"event vocab group {vocab_key!r} is empty")

    overview = service.taxonomy_overview()
    print(f"Taxonomy source mode: {overview['source_mode']}")
    print(f"Split taxonomy directory: {TAXONOMY_DIR}")
    print(f"Fallback taxonomy file: {TAXONOMY_PATH}")
    print(f"Tickers: {overview['ticker_count']}")
    print(f"Industries: {overview['industry_count']}")
    print(f"Sectors: {overview['sector_count']}")
    print(f"Relationships: {overview['relationship_count']}")
    print(f"Event vocab groups: {overview['event_vocab_group_count']}")
    print(f"Themes: {overview['theme_count']}")
    print(f"Macro channels: {overview['macro_channel_count']}")
    print(f"Transmission channels: {overview['transmission_channel_count']}")
    print(f"Transmission tags: {overview['transmission_tag_count']}")
    print(f"Transmission primary drivers: {overview['transmission_primary_driver_count']}")
    print(f"Transmission conflict flags: {overview['transmission_conflict_flag_count']}")
    print(f"Transmission context regimes: {overview['transmission_context_regime_count']}")
    print(f"Relationship types: {overview['relationship_type_count']}")
    print(f"Relationship target kinds: {overview['relationship_target_kind_count']}")
    print(f"Derived relationships: {overview['derived_relationship_count']}")
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
