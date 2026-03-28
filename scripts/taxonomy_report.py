#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trade_proposer_app.services.taxonomy import TickerTaxonomyService  # noqa: E402


def main() -> int:
    service = TickerTaxonomyService()
    overview = service.taxonomy_overview()
    profiles = service.list_industry_profiles()

    print("Taxonomy overview")
    print(f"- source mode: {overview['source_mode']}")
    print(f"- tickers: {overview['ticker_count']}")
    print(f"- industries: {overview['industry_count']}")
    print(f"- sectors: {overview['sector_count']}")
    print(f"- relationships: {overview['relationship_count']}")
    print(f"- event vocab groups: {overview['event_vocab_group_count']}")
    print(f"- themes: {overview['theme_count']}")
    print(f"- macro channels: {overview['macro_channel_count']}")
    print(f"- transmission channels: {overview['transmission_channel_count']}")
    print(f"- transmission tags: {overview['transmission_tag_count']}")
    print(f"- transmission primary drivers: {overview['transmission_primary_driver_count']}")
    print(f"- transmission conflict flags: {overview['transmission_conflict_flag_count']}")
    print(f"- relationship types: {overview['relationship_type_count']}")
    print(f"- relationship target kinds: {overview['relationship_target_kind_count']}")
    print(f"- derived relationships: {overview['derived_relationship_count']}")
    print()
    print("Industry coverage")
    for profile in profiles:
        print(
            f"- {profile['subject_label']} ({profile.get('sector') or 'unknown sector'}) | "
            f"tickers={len(profile.get('tickers', []))} | "
            f"queries={len(profile.get('queries', []))} | "
            f"relationships={len(profile.get('relationships', []))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
