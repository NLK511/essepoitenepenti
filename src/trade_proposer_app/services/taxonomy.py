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

    def get_industry_profile(self, ticker: str) -> dict[str, Any]:
        ticker_profile = self.get_ticker_profile(ticker)
        industry = str(ticker_profile.get("industry", "")).strip()
        sector = str(ticker_profile.get("sector", "")).strip()
        themes = [str(value).strip() for value in ticker_profile.get("themes", []) if str(value).strip()]
        industry_keywords = [str(value).strip() for value in ticker_profile.get("industry_keywords", []) if str(value).strip()]
        subject_key = self._normalize_subject_key(industry or sector or ticker_profile.get("ticker", ticker))
        subject_label = industry or sector or str(ticker_profile.get("ticker", ticker)).upper()
        queries = list(dict.fromkeys(industry_keywords + themes + ([industry] if industry else []) + ([sector] if sector else [])))
        return {
            "subject_key": subject_key,
            "subject_label": subject_label,
            "industry": industry,
            "sector": sector,
            "queries": queries,
            "ticker": ticker_profile.get("ticker", ticker).upper(),
        }

    def list_industry_profiles(self) -> list[dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for ticker in sorted(self._taxonomy):
            industry_profile = self.get_industry_profile(ticker)
            subject_key = industry_profile["subject_key"]
            existing = profiles.get(subject_key)
            if existing is None:
                profiles[subject_key] = {
                    **industry_profile,
                    "tickers": [industry_profile["ticker"]],
                }
                continue
            existing["queries"] = list(dict.fromkeys(existing.get("queries", []) + industry_profile.get("queries", [])))
            existing["tickers"] = list(dict.fromkeys(existing.get("tickers", []) + [industry_profile["ticker"]]))
        return list(profiles.values())

    @staticmethod
    def _normalize_subject_key(value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "unknown"
        return "_".join(token for token in text.replace("/", " ").replace("-", " ").split() if token)
