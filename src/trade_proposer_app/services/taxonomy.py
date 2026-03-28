from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TAXONOMY_PATH = DATA_DIR / "ticker_taxonomy.json"
TAXONOMY_DIR = DATA_DIR / "taxonomy"
TICKERS_PATH = TAXONOMY_DIR / "tickers.json"
INDUSTRIES_PATH = TAXONOMY_DIR / "industries.json"
SECTORS_PATH = TAXONOMY_DIR / "sectors.json"
RELATIONSHIPS_PATH = TAXONOMY_DIR / "relationships.json"
EVENT_VOCAB_PATH = TAXONOMY_DIR / "event_vocab.json"


class TickerTaxonomyService:
    def __init__(self, taxonomy_path: Path | None = None) -> None:
        self.taxonomy_path = taxonomy_path or TICKERS_PATH
        payload = self._load_payload()
        self._taxonomy: dict[str, dict[str, Any]] = payload["tickers"]
        self._industries: dict[str, dict[str, Any]] = payload["industries"]
        self._sectors: dict[str, dict[str, Any]] = payload["sectors"]
        self._relationships: list[dict[str, Any]] = payload["relationships"]
        self._event_vocab: dict[str, list[str]] = payload["event_vocab"]
        self._source_mode: str = payload["source_mode"]

    def _load_payload(self) -> dict[str, Any]:
        split_payload = self._load_split_payload()
        if split_payload is not None:
            split_payload["source_mode"] = "split"
            return split_payload
        monolith_payload = self._load_monolith_payload()
        monolith_payload["source_mode"] = "monolith"
        return monolith_payload

    def _load_split_payload(self) -> dict[str, Any] | None:
        if not TICKERS_PATH.exists():
            return None
        tickers_payload = self._read_json_file(TICKERS_PATH)
        if not isinstance(tickers_payload, dict):
            return None
        return {
            "tickers": {
                key.upper(): value
                for key, value in tickers_payload.items()
                if not key.startswith("_") and isinstance(value, dict)
            },
            "industries": self._load_industries(self._read_json_file(INDUSTRIES_PATH)),
            "sectors": self._load_sectors(self._read_json_file(SECTORS_PATH)),
            "relationships": self._load_relationships(self._read_json_file(RELATIONSHIPS_PATH)),
            "event_vocab": self._load_event_vocab(self._read_json_file(EVENT_VOCAB_PATH)),
        }

    def _load_monolith_payload(self) -> dict[str, Any]:
        empty = {"tickers": {}, "industries": {}, "sectors": {}, "relationships": [], "event_vocab": {}}
        if not TAXONOMY_PATH.exists():
            return empty
        payload = self._read_json_file(TAXONOMY_PATH)
        if not isinstance(payload, dict):
            return empty
        return {
            "tickers": {
                key.upper(): value
                for key, value in payload.items()
                if not key.startswith("_") and isinstance(value, dict)
            },
            "industries": self._load_industries(payload.get("_industries")),
            "sectors": self._load_sectors(payload.get("_sectors")),
            "relationships": self._load_relationships(payload.get("_relationships")),
            "event_vocab": self._load_event_vocab(payload.get("_event_vocab")),
        }

    @staticmethod
    def _read_json_file(path: Path) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _load_industries(self, payload: object) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            return {}
        industries: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            subject_key = self._normalize_subject_key(key)
            industries[subject_key] = self._normalize_industry_definition(subject_key, value)
        return industries

    def _load_sectors(self, payload: object) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            return {}
        sectors: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            sector_key = self._normalize_subject_key(key)
            sectors[sector_key] = {
                "key": sector_key,
                "label": str(value.get("label", self._label_from_subject_key(sector_key))).strip() or self._label_from_subject_key(sector_key),
                "queries": self._normalize_string_list(value.get("queries")),
                "themes": self._normalize_string_list(value.get("themes")),
                "macro_sensitivity": self._normalize_string_list(value.get("macro_sensitivity")),
            }
        return sectors

    def _load_event_vocab(self, payload: object) -> dict[str, list[str]]:
        if not isinstance(payload, dict):
            return {}
        vocab: dict[str, list[str]] = {}
        for key, value in payload.items():
            normalized_key = self._normalize_subject_key(key)
            vocab[normalized_key] = self._normalize_string_list(value)
        return vocab

    def _load_relationships(self, payload: object) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        relationships: list[dict[str, Any]] = []
        for value in payload:
            if not isinstance(value, dict):
                continue
            source = self._normalize_subject_key(value.get("source"))
            target = self._normalize_subject_key(value.get("target"))
            relation_type = str(value.get("type", "")).strip()
            if not source or source == "unknown" or not target or target == "unknown" or not relation_type:
                continue
            relationships.append(
                {
                    "source": source,
                    "target": target,
                    "type": relation_type,
                    "target_kind": str(value.get("target_kind", "industry")).strip() or "industry",
                    "channel": str(value.get("channel", "")).strip(),
                    "strength": str(value.get("strength", "")).strip(),
                    "note": str(value.get("note", "")).strip(),
                }
            )
        return relationships

    def get_ticker_profile(self, ticker: str) -> dict[str, Any]:
        normalized = ticker.upper()
        profile = dict(self._taxonomy.get(normalized, {}))
        profile["ticker"] = normalized
        profile["company_name"] = str(profile.get("company_name") or normalized).strip() or normalized
        profile["aliases"] = self._normalize_string_list(profile.get("aliases")) or [normalized]
        profile["sector"] = str(profile.get("sector", "")).strip()
        profile["industry"] = str(profile.get("industry", "")).strip()
        profile["subindustry"] = str(profile.get("subindustry", "")).strip()
        profile["region"] = str(profile.get("region", "")).strip()
        profile["domicile"] = str(profile.get("domicile", "")).strip()
        profile["market_cap_bucket"] = str(profile.get("market_cap_bucket", "")).strip()
        profile["themes"] = self._normalize_string_list(profile.get("themes"))
        profile["macro_sensitivity"] = self._normalize_string_list(profile.get("macro_sensitivity"))
        profile["industry_keywords"] = self._normalize_string_list(profile.get("industry_keywords"))
        profile["ticker_keywords"] = self._normalize_string_list(profile.get("ticker_keywords")) or [f"${normalized}", normalized]
        profile["exclude_keywords"] = [value.lower() for value in self._normalize_string_list(profile.get("exclude_keywords"))]
        profile["peers"] = self._normalize_ticker_list(profile.get("peers"))
        profile["suppliers"] = self._normalize_ticker_list(profile.get("suppliers"))
        profile["customers"] = self._normalize_ticker_list(profile.get("customers"))
        profile["exposure_channels"] = self._normalize_string_list(profile.get("exposure_channels"))
        profile["factor_tags"] = self._normalize_string_list(profile.get("factor_tags"))
        profile["event_vocab"] = self._normalize_string_list(profile.get("event_vocab"))
        return profile

    def build_query_profile(self, ticker: str) -> dict[str, list[str]]:
        profile = self.get_ticker_profile(ticker)
        industry_profile = self.get_industry_profile(ticker)
        aliases = [str(value).strip() for value in profile.get("aliases", []) if str(value).strip()]
        ticker_queries = [str(value).strip() for value in profile.get("ticker_keywords", []) if str(value).strip()]
        if not ticker_queries:
            ticker_queries = [f"${profile['ticker']}", profile["ticker"]]
        industry_queries = [str(value).strip() for value in industry_profile.get("queries", []) if str(value).strip()]
        macro_queries = list(
            dict.fromkeys(
                [str(value).strip() for value in profile.get("macro_sensitivity", []) if str(value).strip()]
                + [str(value).strip() for value in industry_profile.get("macro_sensitivity", []) if str(value).strip()]
            )
        )
        return {
            "ticker_queries": list(dict.fromkeys(ticker_queries + aliases)),
            "industry_queries": list(dict.fromkeys(industry_queries)),
            "macro_queries": macro_queries,
            "exclude_keywords": [str(value).strip().lower() for value in profile.get("exclude_keywords", []) if str(value).strip()],
        }

    def get_sector_definition(self, sector: str) -> dict[str, Any]:
        sector_key = self._normalize_subject_key(sector)
        return dict(self._sectors.get(sector_key, {"key": sector_key, "label": self._label_from_subject_key(sector_key), "queries": [], "themes": [], "macro_sensitivity": []}))

    def get_industry_definition(self, subject: str) -> dict[str, Any]:
        subject_key = self._subject_key_for_input(subject)
        explicit = dict(self._industries.get(subject_key, {}))
        return self._normalize_industry_definition(subject_key, explicit)

    def get_industry_profile(self, ticker: str) -> dict[str, Any]:
        ticker_profile = self.get_ticker_profile(ticker)
        industry = str(ticker_profile.get("industry", "")).strip()
        sector = str(ticker_profile.get("sector", "")).strip()
        subindustry = str(ticker_profile.get("subindustry", "")).strip()
        subject_key = self._normalize_subject_key(industry or sector or ticker_profile.get("ticker", ticker))
        subject_label = industry or sector or str(ticker_profile.get("ticker", ticker)).upper()
        explicit_definition = self.get_industry_definition(subject_key)
        sector_definition = self.get_sector_definition(explicit_definition.get("sector") or sector)
        themes = self._normalize_string_list(ticker_profile.get("themes"))
        industry_keywords = self._normalize_string_list(ticker_profile.get("industry_keywords"))
        event_vocab = self._normalize_string_list(explicit_definition.get("event_vocab")) + self._normalize_string_list(ticker_profile.get("event_vocab")) + self._event_vocab.get(subject_key, [])
        derived_queries = industry_keywords + themes + ([subindustry] if subindustry else []) + ([industry] if industry else []) + ([sector] if sector else [])
        relationships = self.list_relationships(subject_key, direction="outbound")
        return {
            "subject_key": subject_key,
            "subject_label": explicit_definition.get("label") or subject_label,
            "industry": industry,
            "sector": explicit_definition.get("sector") or sector,
            "sector_definition": sector_definition,
            "queries": list(
                dict.fromkeys(
                    self._normalize_string_list(sector_definition.get("queries"))
                    + self._normalize_string_list(explicit_definition.get("queries"))
                    + derived_queries
                )
            ),
            "themes": list(
                dict.fromkeys(
                    self._normalize_string_list(sector_definition.get("themes"))
                    + self._normalize_string_list(explicit_definition.get("themes"))
                    + themes
                )
            ),
            "macro_sensitivity": list(
                dict.fromkeys(
                    self._normalize_string_list(sector_definition.get("macro_sensitivity"))
                    + self._normalize_string_list(explicit_definition.get("macro_sensitivity"))
                    + self._normalize_string_list(ticker_profile.get("macro_sensitivity"))
                )
            ),
            "transmission_channels": list(
                dict.fromkeys(
                    self._normalize_string_list(explicit_definition.get("transmission_channels"))
                    + self._normalize_string_list(ticker_profile.get("exposure_channels"))
                )
            ),
            "peer_industries": self._normalize_string_list(explicit_definition.get("peer_industries")),
            "risk_flags": self._normalize_string_list(explicit_definition.get("risk_flags")),
            "event_vocab": list(dict.fromkeys(event_vocab)),
            "regions": list(dict.fromkeys([value for value in [ticker_profile.get("region")] if value])),
            "domiciles": list(dict.fromkeys([value for value in [ticker_profile.get("domicile")] if value])),
            "relationships": relationships,
            "ticker": ticker_profile.get("ticker", ticker).upper(),
        }

    def list_industry_profiles(self) -> list[dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for subject_key, definition in self._industries.items():
            sector_definition = self.get_sector_definition(definition.get("sector", ""))
            profiles[subject_key] = {
                **definition,
                "subject_key": subject_key,
                "subject_label": definition.get("label") or self._label_from_subject_key(subject_key),
                "industry": definition.get("label") or self._label_from_subject_key(subject_key),
                "sector_definition": sector_definition,
                "queries": list(dict.fromkeys(self._normalize_string_list(sector_definition.get("queries")) + self._normalize_string_list(definition.get("queries")))),
                "themes": list(dict.fromkeys(self._normalize_string_list(sector_definition.get("themes")) + self._normalize_string_list(definition.get("themes")))),
                "macro_sensitivity": list(dict.fromkeys(self._normalize_string_list(sector_definition.get("macro_sensitivity")) + self._normalize_string_list(definition.get("macro_sensitivity")))),
                "transmission_channels": self._normalize_string_list(definition.get("transmission_channels")),
                "peer_industries": self._normalize_string_list(definition.get("peer_industries")),
                "risk_flags": self._normalize_string_list(definition.get("risk_flags")),
                "event_vocab": list(dict.fromkeys(self._normalize_string_list(definition.get("event_vocab")) + self._event_vocab.get(subject_key, []))),
                "tickers": self._normalize_ticker_list(definition.get("tickers")),
                "regions": self._normalize_string_list(definition.get("regions")),
                "domiciles": self._normalize_string_list(definition.get("domiciles")),
                "companies": self._normalize_string_list(definition.get("companies")),
                "relationships": self.list_relationships(subject_key, direction="outbound"),
            }
        for ticker in sorted(self._taxonomy):
            ticker_profile = self.get_ticker_profile(ticker)
            industry_profile = self.get_industry_profile(ticker)
            subject_key = industry_profile["subject_key"]
            existing = profiles.get(subject_key)
            if existing is None:
                profiles[subject_key] = {
                    **industry_profile,
                    "tickers": [industry_profile["ticker"]],
                    "regions": industry_profile.get("regions", []),
                    "domiciles": industry_profile.get("domiciles", []),
                    "companies": [ticker_profile.get("company_name", industry_profile["ticker"])],
                }
                continue
            existing["subject_label"] = existing.get("subject_label") or industry_profile["subject_label"]
            existing["industry"] = existing.get("industry") or industry_profile["industry"]
            existing["sector"] = existing.get("sector") or industry_profile["sector"]
            existing["queries"] = list(dict.fromkeys(existing.get("queries", []) + industry_profile.get("queries", [])))
            existing["themes"] = list(dict.fromkeys(existing.get("themes", []) + industry_profile.get("themes", [])))
            existing["macro_sensitivity"] = list(dict.fromkeys(existing.get("macro_sensitivity", []) + industry_profile.get("macro_sensitivity", [])))
            existing["transmission_channels"] = list(dict.fromkeys(existing.get("transmission_channels", []) + industry_profile.get("transmission_channels", [])))
            existing["peer_industries"] = list(dict.fromkeys(existing.get("peer_industries", []) + industry_profile.get("peer_industries", [])))
            existing["risk_flags"] = list(dict.fromkeys(existing.get("risk_flags", []) + industry_profile.get("risk_flags", [])))
            existing["event_vocab"] = list(dict.fromkeys(existing.get("event_vocab", []) + industry_profile.get("event_vocab", [])))
            existing["tickers"] = list(dict.fromkeys(existing.get("tickers", []) + [industry_profile["ticker"]]))
            existing["regions"] = list(dict.fromkeys(existing.get("regions", []) + industry_profile.get("regions", [])))
            existing["domiciles"] = list(dict.fromkeys(existing.get("domiciles", []) + industry_profile.get("domiciles", [])))
            existing["companies"] = list(dict.fromkeys(existing.get("companies", []) + [ticker_profile.get("company_name", industry_profile["ticker"])]))
            existing["relationships"] = self.list_relationships(subject_key, direction="outbound")
        return [profiles[key] for key in sorted(profiles)]

    def list_sector_definitions(self) -> list[dict[str, Any]]:
        return [self.get_sector_definition(key) for key in sorted(self._sectors)]

    def list_relationships(self, subject_key: str | None = None, *, direction: str = "any") -> list[dict[str, Any]]:
        normalized = self._normalize_subject_key(subject_key) if subject_key else None
        relationships = self._relationships
        if normalized is None:
            return list(relationships)
        if direction == "outbound":
            return [relationship for relationship in relationships if relationship.get("source") == normalized]
        if direction == "inbound":
            return [relationship for relationship in relationships if relationship.get("target") == normalized]
        return [relationship for relationship in relationships if relationship.get("source") == normalized or relationship.get("target") == normalized]

    def taxonomy_overview(self) -> dict[str, Any]:
        return {
            "source_mode": self._source_mode,
            "ticker_count": len(self._taxonomy),
            "industry_count": len(self._industries),
            "sector_count": len(self._sectors),
            "relationship_count": len(self._relationships),
            "event_vocab_group_count": len(self._event_vocab),
        }

    def _subject_key_for_input(self, subject: str) -> str:
        normalized_ticker = str(subject or "").strip().upper()
        if normalized_ticker in self._taxonomy:
            ticker_profile = self.get_ticker_profile(normalized_ticker)
            return self._normalize_subject_key(ticker_profile.get("industry") or ticker_profile.get("sector") or ticker_profile.get("ticker") or normalized_ticker)
        return self._normalize_subject_key(subject)

    def _normalize_industry_definition(self, subject_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "subject_key": subject_key,
            "label": str(payload.get("label", self._label_from_subject_key(subject_key))).strip() or self._label_from_subject_key(subject_key),
            "sector": str(payload.get("sector", "")).strip(),
            "queries": self._normalize_string_list(payload.get("queries") or payload.get("industry_keywords")),
            "themes": self._normalize_string_list(payload.get("themes")),
            "macro_sensitivity": self._normalize_string_list(payload.get("macro_sensitivity")),
            "transmission_channels": self._normalize_string_list(payload.get("transmission_channels")),
            "peer_industries": [self._normalize_subject_key(value) for value in self._normalize_string_list(payload.get("peer_industries"))],
            "risk_flags": self._normalize_string_list(payload.get("risk_flags")),
            "event_vocab": self._normalize_string_list(payload.get("event_vocab")),
            "tickers": self._normalize_ticker_list(payload.get("tickers")),
            "regions": self._normalize_string_list(payload.get("regions")),
            "domiciles": self._normalize_string_list(payload.get("domiciles")),
            "companies": self._normalize_string_list(payload.get("companies")),
        }

    @staticmethod
    def _normalize_string_list(values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        normalized: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_ticker_list(values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        normalized: list[str] = []
        for value in values:
            text = str(value or "").strip().upper()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _label_from_subject_key(subject_key: str) -> str:
        return " ".join(token.capitalize() for token in subject_key.split("_") if token)

    @staticmethod
    def _normalize_subject_key(value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "unknown"
        return "_".join(token for token in text.replace("/", " ").replace("-", " ").split() if token)
