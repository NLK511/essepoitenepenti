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
