from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "ticker_taxonomy.json"


class TickerTaxonomyService:
    def __init__(self, taxonomy_path: Path | None = None) -> None:
        self.taxonomy_path = taxonomy_path or TAXONOMY_PATH
        self._taxonomy = self._load_taxonomy()

    def _load_taxonomy(self) -> dict[str, dict[str, Any]]:
        if not self.taxonomy_path.exists():
            return {}
        try:
            payload = json.loads(self.taxonomy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {key.upper(): value for key, value in payload.items() if not key.startswith("_") and isinstance(value, dict)}

    def get_ticker_profile(self, ticker: str) -> dict[str, Any]:
        normalized = ticker.upper()
        profile = dict(self._taxonomy.get(normalized, {}))
        profile.setdefault("ticker", normalized)
        profile.setdefault("company_name", normalized)
        profile.setdefault("aliases", [normalized])
        profile.setdefault("sector", "")
        profile.setdefault("industry", "")
        profile.setdefault("themes", [])
        profile.setdefault("macro_sensitivity", [])
        profile.setdefault("industry_keywords", [])
        profile.setdefault("ticker_keywords", [f"${normalized}", normalized])
        profile.setdefault("exclude_keywords", [])
        return profile

    def build_query_profile(self, ticker: str) -> dict[str, list[str]]:
        profile = self.get_ticker_profile(ticker)
        aliases = [str(value).strip() for value in profile.get("aliases", []) if str(value).strip()]
        ticker_queries = [str(value).strip() for value in profile.get("ticker_keywords", []) if str(value).strip()]
        if not ticker_queries:
            ticker_queries = [f"${profile['ticker']}", profile["ticker"]]
        industry_queries = [str(value).strip() for value in profile.get("industry_keywords", []) if str(value).strip()]
        macro_queries = [str(value).strip() for value in profile.get("macro_sensitivity", []) if str(value).strip()]
        return {
            "ticker_queries": list(dict.fromkeys(ticker_queries + aliases)),
            "industry_queries": list(dict.fromkeys(industry_queries)),
            "macro_queries": list(dict.fromkeys(macro_queries)),
            "exclude_keywords": [str(value).strip().lower() for value in profile.get("exclude_keywords", []) if str(value).strip()],
        }
