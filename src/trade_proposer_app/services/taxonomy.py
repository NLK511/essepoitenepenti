from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
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
THEMES_PATH = TAXONOMY_DIR / "themes.json"
MACRO_CHANNELS_PATH = TAXONOMY_DIR / "macro_channels.json"
TRANSMISSION_CHANNELS_PATH = TAXONOMY_DIR / "transmission_channels.json"
TRANSMISSION_TAGS_PATH = TAXONOMY_DIR / "transmission_tags.json"
TRANSMISSION_PRIMARY_DRIVERS_PATH = TAXONOMY_DIR / "transmission_primary_drivers.json"
TRANSMISSION_CONFLICT_FLAGS_PATH = TAXONOMY_DIR / "transmission_conflict_flags.json"
TRANSMISSION_BIASES_PATH = TAXONOMY_DIR / "transmission_biases.json"
TRANSMISSION_CONTEXT_REGIMES_PATH = TAXONOMY_DIR / "transmission_context_regimes.json"
TRANSMISSION_WINDOWS_PATH = TAXONOMY_DIR / "transmission_windows.json"
SHORTLIST_REASON_CODES_PATH = TAXONOMY_DIR / "shortlist_reason_codes.json"
SHORTLIST_SELECTION_LANES_PATH = TAXONOMY_DIR / "shortlist_selection_lanes.json"
CALIBRATION_REVIEW_STATUSES_PATH = TAXONOMY_DIR / "calibration_review_statuses.json"
CALIBRATION_REASON_CODES_PATH = TAXONOMY_DIR / "calibration_reason_codes.json"
ACTION_REASON_CODES_PATH = TAXONOMY_DIR / "action_reason_codes.json"
CONTRADICTION_REASON_CODES_PATH = TAXONOMY_DIR / "contradiction_reason_codes.json"
EVENT_SOURCE_PRIORITIES_PATH = TAXONOMY_DIR / "event_source_priorities.json"
EVENT_PERSISTENCE_STATES_PATH = TAXONOMY_DIR / "event_persistence_states.json"
EVENT_WINDOW_HINTS_PATH = TAXONOMY_DIR / "event_window_hints.json"
EVENT_RECENCY_BUCKETS_PATH = TAXONOMY_DIR / "event_recency_buckets.json"
RELATIONSHIP_TYPES_PATH = TAXONOMY_DIR / "relationship_types.json"
RELATIONSHIP_TARGET_KINDS_PATH = TAXONOMY_DIR / "relationship_target_kinds.json"

SECTOR_ALIASES = {
    "technology": "information_technology",
    "tech": "information_technology",
    "financial_services": "financials",
    "financial_service": "financials",
    "healthcare": "health_care",
    "consumer_defensive": "consumer_staples",
    "basic_materials": "materials",
}


class TickerTaxonomyService:
    def __init__(
        self,
        taxonomy_path: Path | None = None,
        *,
        metadata_provider: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.taxonomy_path = taxonomy_path or TICKERS_PATH
        self._metadata_provider = metadata_provider
        self._external_profile_cache: dict[str, dict[str, Any]] = {}
        payload = self._load_payload()
        self._taxonomy: dict[str, dict[str, Any]] = payload["tickers"]
        self._industries: dict[str, dict[str, Any]] = payload["industries"]
        self._sectors: dict[str, dict[str, Any]] = payload["sectors"]
        self._relationships: list[dict[str, Any]] = payload["relationships"]
        self._event_vocab: dict[str, list[str]] = payload["event_vocab"]
        self._themes: dict[str, dict[str, Any]] = payload["themes"]
        self._macro_channels: dict[str, dict[str, Any]] = payload["macro_channels"]
        self._transmission_channels: dict[str, dict[str, Any]] = payload["transmission_channels"]
        self._relationship_types: dict[str, dict[str, Any]] = payload["relationship_types"]
        self._relationship_target_kinds: dict[str, dict[str, Any]] = payload["relationship_target_kinds"]
        self._transmission_tags: dict[str, dict[str, Any]] = payload["transmission_tags"]
        self._transmission_primary_drivers: dict[str, dict[str, Any]] = payload["transmission_primary_drivers"]
        self._transmission_conflict_flags: dict[str, dict[str, Any]] = payload["transmission_conflict_flags"]
        self._transmission_biases: dict[str, dict[str, Any]] = payload["transmission_biases"]
        self._transmission_context_regimes: dict[str, dict[str, Any]] = payload["transmission_context_regimes"]
        self._transmission_windows: dict[str, dict[str, Any]] = payload["transmission_windows"]
        self._shortlist_reason_codes: dict[str, dict[str, Any]] = payload["shortlist_reason_codes"]
        self._shortlist_selection_lanes: dict[str, dict[str, Any]] = payload["shortlist_selection_lanes"]
        self._calibration_review_statuses: dict[str, dict[str, Any]] = payload["calibration_review_statuses"]
        self._calibration_reason_codes: dict[str, dict[str, Any]] = payload["calibration_reason_codes"]
        self._action_reason_codes: dict[str, dict[str, Any]] = payload["action_reason_codes"]
        self._contradiction_reason_codes: dict[str, dict[str, Any]] = payload["contradiction_reason_codes"]
        self._event_source_priorities: dict[str, dict[str, Any]] = payload["event_source_priorities"]
        self._event_persistence_states: dict[str, dict[str, Any]] = payload["event_persistence_states"]
        self._event_window_hints: dict[str, dict[str, Any]] = payload["event_window_hints"]
        self._event_recency_buckets: dict[str, dict[str, Any]] = payload["event_recency_buckets"]
        self._theme_alias_map: dict[str, str] = self._build_alias_map(self._themes)
        self._macro_channel_alias_map: dict[str, str] = self._build_alias_map(self._macro_channels)
        self._transmission_channel_alias_map: dict[str, str] = self._build_alias_map(self._transmission_channels)
        self._relationship_type_alias_map: dict[str, str] = self._build_alias_map(self._relationship_types)
        self._relationship_target_kind_alias_map: dict[str, str] = self._build_alias_map(self._relationship_target_kinds)
        self._transmission_tag_alias_map: dict[str, str] = self._build_alias_map(self._transmission_tags)
        self._transmission_primary_driver_alias_map: dict[str, str] = self._build_alias_map(self._transmission_primary_drivers)
        self._transmission_conflict_flag_alias_map: dict[str, str] = self._build_alias_map(self._transmission_conflict_flags)
        self._transmission_bias_alias_map: dict[str, str] = self._build_alias_map(self._transmission_biases)
        self._transmission_context_regime_alias_map: dict[str, str] = self._build_alias_map(self._transmission_context_regimes)
        self._transmission_window_alias_map: dict[str, str] = self._build_alias_map(self._transmission_windows)
        self._shortlist_reason_code_alias_map: dict[str, str] = self._build_alias_map(self._shortlist_reason_codes)
        self._shortlist_selection_lane_alias_map: dict[str, str] = self._build_alias_map(self._shortlist_selection_lanes)
        self._calibration_review_status_alias_map: dict[str, str] = self._build_alias_map(self._calibration_review_statuses)
        self._calibration_reason_code_alias_map: dict[str, str] = self._build_alias_map(self._calibration_reason_codes)
        self._action_reason_code_alias_map: dict[str, str] = self._build_alias_map(self._action_reason_codes)
        self._contradiction_reason_code_alias_map: dict[str, str] = self._build_alias_map(self._contradiction_reason_codes)
        self._event_source_priority_alias_map: dict[str, str] = self._build_alias_map(self._event_source_priorities)
        self._event_persistence_state_alias_map: dict[str, str] = self._build_alias_map(self._event_persistence_states)
        self._event_window_hint_alias_map: dict[str, str] = self._build_alias_map(self._event_window_hints)
        self._event_recency_bucket_alias_map: dict[str, str] = self._build_alias_map(self._event_recency_buckets)
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
        themes = self._load_registry(self._read_json_file(THEMES_PATH))
        macro_channels = self._load_registry(self._read_json_file(MACRO_CHANNELS_PATH))
        transmission_channels = self._load_registry(self._read_json_file(TRANSMISSION_CHANNELS_PATH))
        transmission_tags = self._load_registry(self._read_json_file(TRANSMISSION_TAGS_PATH))
        transmission_primary_drivers = self._load_registry(self._read_json_file(TRANSMISSION_PRIMARY_DRIVERS_PATH))
        transmission_conflict_flags = self._load_registry(self._read_json_file(TRANSMISSION_CONFLICT_FLAGS_PATH))
        transmission_biases = self._load_registry(self._read_json_file(TRANSMISSION_BIASES_PATH))
        transmission_context_regimes = self._load_registry(self._read_json_file(TRANSMISSION_CONTEXT_REGIMES_PATH))
        transmission_windows = self._load_registry(self._read_json_file(TRANSMISSION_WINDOWS_PATH))
        shortlist_reason_codes = self._load_registry(self._read_json_file(SHORTLIST_REASON_CODES_PATH))
        shortlist_selection_lanes = self._load_registry(self._read_json_file(SHORTLIST_SELECTION_LANES_PATH))
        calibration_review_statuses = self._load_registry(self._read_json_file(CALIBRATION_REVIEW_STATUSES_PATH))
        calibration_reason_codes = self._load_registry(self._read_json_file(CALIBRATION_REASON_CODES_PATH))
        action_reason_codes = self._load_registry(self._read_json_file(ACTION_REASON_CODES_PATH))
        contradiction_reason_codes = self._load_registry(self._read_json_file(CONTRADICTION_REASON_CODES_PATH))
        event_source_priorities = self._load_registry(self._read_json_file(EVENT_SOURCE_PRIORITIES_PATH))
        event_persistence_states = self._load_registry(self._read_json_file(EVENT_PERSISTENCE_STATES_PATH))
        event_window_hints = self._load_registry(self._read_json_file(EVENT_WINDOW_HINTS_PATH))
        event_recency_buckets = self._load_registry(self._read_json_file(EVENT_RECENCY_BUCKETS_PATH))
        relationship_types = self._load_registry(self._read_json_file(RELATIONSHIP_TYPES_PATH))
        relationship_target_kinds = self._load_registry(self._read_json_file(RELATIONSHIP_TARGET_KINDS_PATH))
        self._themes = themes
        self._macro_channels = macro_channels
        self._transmission_channels = transmission_channels
        self._transmission_tags = transmission_tags
        self._transmission_primary_drivers = transmission_primary_drivers
        self._transmission_conflict_flags = transmission_conflict_flags
        self._transmission_biases = transmission_biases
        self._transmission_context_regimes = transmission_context_regimes
        self._transmission_windows = transmission_windows
        self._shortlist_reason_codes = shortlist_reason_codes
        self._shortlist_selection_lanes = shortlist_selection_lanes
        self._calibration_review_statuses = calibration_review_statuses
        self._calibration_reason_codes = calibration_reason_codes
        self._action_reason_codes = action_reason_codes
        self._contradiction_reason_codes = contradiction_reason_codes
        self._event_source_priorities = event_source_priorities
        self._event_persistence_states = event_persistence_states
        self._event_window_hints = event_window_hints
        self._event_recency_buckets = event_recency_buckets
        self._relationship_types = relationship_types
        self._relationship_target_kinds = relationship_target_kinds
        self._theme_alias_map = self._build_alias_map(themes)
        self._macro_channel_alias_map = self._build_alias_map(macro_channels)
        self._transmission_channel_alias_map = self._build_alias_map(transmission_channels)
        self._transmission_tag_alias_map = self._build_alias_map(transmission_tags)
        self._transmission_primary_driver_alias_map = self._build_alias_map(transmission_primary_drivers)
        self._transmission_conflict_flag_alias_map = self._build_alias_map(transmission_conflict_flags)
        self._transmission_bias_alias_map = self._build_alias_map(transmission_biases)
        self._transmission_context_regime_alias_map = self._build_alias_map(transmission_context_regimes)
        self._transmission_window_alias_map = self._build_alias_map(transmission_windows)
        self._shortlist_reason_code_alias_map = self._build_alias_map(shortlist_reason_codes)
        self._shortlist_selection_lane_alias_map = self._build_alias_map(shortlist_selection_lanes)
        self._calibration_review_status_alias_map = self._build_alias_map(calibration_review_statuses)
        self._calibration_reason_code_alias_map = self._build_alias_map(calibration_reason_codes)
        self._action_reason_code_alias_map = self._build_alias_map(action_reason_codes)
        self._contradiction_reason_code_alias_map = self._build_alias_map(contradiction_reason_codes)
        self._event_source_priority_alias_map = self._build_alias_map(event_source_priorities)
        self._event_persistence_state_alias_map = self._build_alias_map(event_persistence_states)
        self._event_window_hint_alias_map = self._build_alias_map(event_window_hints)
        self._event_recency_bucket_alias_map = self._build_alias_map(event_recency_buckets)
        self._relationship_type_alias_map = self._build_alias_map(relationship_types)
        self._relationship_target_kind_alias_map = self._build_alias_map(relationship_target_kinds)
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
            "themes": themes,
            "macro_channels": macro_channels,
            "transmission_channels": transmission_channels,
            "transmission_tags": transmission_tags,
            "transmission_primary_drivers": transmission_primary_drivers,
            "transmission_conflict_flags": transmission_conflict_flags,
            "transmission_biases": transmission_biases,
            "transmission_context_regimes": transmission_context_regimes,
            "transmission_windows": transmission_windows,
            "shortlist_reason_codes": shortlist_reason_codes,
            "shortlist_selection_lanes": shortlist_selection_lanes,
            "calibration_review_statuses": calibration_review_statuses,
            "calibration_reason_codes": calibration_reason_codes,
            "action_reason_codes": action_reason_codes,
            "contradiction_reason_codes": contradiction_reason_codes,
            "event_source_priorities": event_source_priorities,
            "event_persistence_states": event_persistence_states,
            "event_window_hints": event_window_hints,
            "event_recency_buckets": event_recency_buckets,
            "relationship_types": relationship_types,
            "relationship_target_kinds": relationship_target_kinds,
        }

    def _load_monolith_payload(self) -> dict[str, Any]:
        empty = {"tickers": {}, "industries": {}, "sectors": {}, "relationships": [], "event_vocab": {}, "themes": {}, "macro_channels": {}, "transmission_channels": {}, "transmission_tags": {}, "transmission_primary_drivers": {}, "transmission_conflict_flags": {}, "transmission_biases": {}, "transmission_context_regimes": {}, "transmission_windows": {}, "shortlist_reason_codes": {}, "shortlist_selection_lanes": {}, "calibration_review_statuses": {}, "calibration_reason_codes": {}, "action_reason_codes": {}, "contradiction_reason_codes": {}, "event_source_priorities": {}, "event_persistence_states": {}, "event_window_hints": {}, "event_recency_buckets": {}, "relationship_types": {}, "relationship_target_kinds": {}}
        if not TAXONOMY_PATH.exists():
            return empty
        payload = self._read_json_file(TAXONOMY_PATH)
        if not isinstance(payload, dict):
            return empty
        themes = self._load_registry(payload.get("_themes"))
        macro_channels = self._load_registry(payload.get("_macro_channels"))
        transmission_channels = self._load_registry(payload.get("_transmission_channels"))
        transmission_tags = self._load_registry(payload.get("_transmission_tags"))
        transmission_primary_drivers = self._load_registry(payload.get("_transmission_primary_drivers"))
        transmission_conflict_flags = self._load_registry(payload.get("_transmission_conflict_flags"))
        transmission_biases = self._load_registry(payload.get("_transmission_biases"))
        transmission_context_regimes = self._load_registry(payload.get("_transmission_context_regimes"))
        transmission_windows = self._load_registry(payload.get("_transmission_windows"))
        shortlist_reason_codes = self._load_registry(payload.get("_shortlist_reason_codes"))
        shortlist_selection_lanes = self._load_registry(payload.get("_shortlist_selection_lanes"))
        calibration_review_statuses = self._load_registry(payload.get("_calibration_review_statuses"))
        calibration_reason_codes = self._load_registry(payload.get("_calibration_reason_codes"))
        action_reason_codes = self._load_registry(payload.get("_action_reason_codes"))
        contradiction_reason_codes = self._load_registry(payload.get("_contradiction_reason_codes"))
        event_source_priorities = self._load_registry(payload.get("_event_source_priorities"))
        event_persistence_states = self._load_registry(payload.get("_event_persistence_states"))
        event_window_hints = self._load_registry(payload.get("_event_window_hints"))
        event_recency_buckets = self._load_registry(payload.get("_event_recency_buckets"))
        relationship_types = self._load_registry(payload.get("_relationship_types"))
        relationship_target_kinds = self._load_registry(payload.get("_relationship_target_kinds"))
        self._themes = themes
        self._macro_channels = macro_channels
        self._transmission_channels = transmission_channels
        self._transmission_tags = transmission_tags
        self._transmission_primary_drivers = transmission_primary_drivers
        self._transmission_conflict_flags = transmission_conflict_flags
        self._transmission_biases = transmission_biases
        self._transmission_context_regimes = transmission_context_regimes
        self._transmission_windows = transmission_windows
        self._shortlist_reason_codes = shortlist_reason_codes
        self._shortlist_selection_lanes = shortlist_selection_lanes
        self._calibration_review_statuses = calibration_review_statuses
        self._calibration_reason_codes = calibration_reason_codes
        self._action_reason_codes = action_reason_codes
        self._contradiction_reason_codes = contradiction_reason_codes
        self._event_source_priorities = event_source_priorities
        self._event_persistence_states = event_persistence_states
        self._event_window_hints = event_window_hints
        self._event_recency_buckets = event_recency_buckets
        self._relationship_types = relationship_types
        self._relationship_target_kinds = relationship_target_kinds
        self._theme_alias_map = self._build_alias_map(themes)
        self._macro_channel_alias_map = self._build_alias_map(macro_channels)
        self._transmission_channel_alias_map = self._build_alias_map(transmission_channels)
        self._transmission_tag_alias_map = self._build_alias_map(transmission_tags)
        self._transmission_primary_driver_alias_map = self._build_alias_map(transmission_primary_drivers)
        self._transmission_conflict_flag_alias_map = self._build_alias_map(transmission_conflict_flags)
        self._transmission_bias_alias_map = self._build_alias_map(transmission_biases)
        self._transmission_context_regime_alias_map = self._build_alias_map(transmission_context_regimes)
        self._transmission_window_alias_map = self._build_alias_map(transmission_windows)
        self._shortlist_reason_code_alias_map = self._build_alias_map(shortlist_reason_codes)
        self._shortlist_selection_lane_alias_map = self._build_alias_map(shortlist_selection_lanes)
        self._calibration_review_status_alias_map = self._build_alias_map(calibration_review_statuses)
        self._calibration_reason_code_alias_map = self._build_alias_map(calibration_reason_codes)
        self._action_reason_code_alias_map = self._build_alias_map(action_reason_codes)
        self._contradiction_reason_code_alias_map = self._build_alias_map(contradiction_reason_codes)
        self._event_source_priority_alias_map = self._build_alias_map(event_source_priorities)
        self._event_persistence_state_alias_map = self._build_alias_map(event_persistence_states)
        self._event_window_hint_alias_map = self._build_alias_map(event_window_hints)
        self._event_recency_bucket_alias_map = self._build_alias_map(event_recency_buckets)
        self._relationship_type_alias_map = self._build_alias_map(relationship_types)
        self._relationship_target_kind_alias_map = self._build_alias_map(relationship_target_kinds)
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
            "themes": themes,
            "macro_channels": macro_channels,
            "transmission_channels": transmission_channels,
            "transmission_tags": transmission_tags,
            "transmission_primary_drivers": transmission_primary_drivers,
            "transmission_conflict_flags": transmission_conflict_flags,
            "transmission_biases": transmission_biases,
            "transmission_context_regimes": transmission_context_regimes,
            "transmission_windows": transmission_windows,
            "shortlist_reason_codes": shortlist_reason_codes,
            "shortlist_selection_lanes": shortlist_selection_lanes,
            "calibration_review_statuses": calibration_review_statuses,
            "calibration_reason_codes": calibration_reason_codes,
            "action_reason_codes": action_reason_codes,
            "contradiction_reason_codes": contradiction_reason_codes,
            "event_source_priorities": event_source_priorities,
            "event_persistence_states": event_persistence_states,
            "event_window_hints": event_window_hints,
            "event_recency_buckets": event_recency_buckets,
            "relationship_types": relationship_types,
            "relationship_target_kinds": relationship_target_kinds,
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
                "themes": self._normalize_theme_values(value.get("themes")),
                "macro_sensitivity": self._normalize_macro_channel_values(value.get("macro_sensitivity")),
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

    def _load_registry(self, payload: object) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            return {}
        registry: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            canonical_key = self._normalize_subject_key(key)
            label = str(value.get("label", canonical_key.replace("_", " "))).strip() or canonical_key.replace("_", " ")
            aliases = self._normalize_string_list(value.get("aliases"))
            entry: dict[str, Any] = {
                "key": canonical_key,
                "label": label,
                "aliases": aliases,
            }
            for field, field_value in value.items():
                if field in {"label", "aliases"}:
                    continue
                entry[field] = field_value
            registry[canonical_key] = entry
        return registry

    def _load_relationships(self, payload: object) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        relationships: list[dict[str, Any]] = []
        for value in payload:
            if not isinstance(value, dict):
                continue
            source = self._normalize_subject_key(value.get("source"))
            target_kind = self._normalize_relationship_target_kind(value.get("target_kind", "industry"))
            target = self._canonicalize_relationship_target(value.get("target"), target_kind)
            relation_type = self._normalize_relationship_type(value.get("type"))
            channel = self._canonicalize_transmission_channel(value.get("channel"))
            if not source or source == "unknown" or not target or target == "unknown" or not relation_type:
                continue
            direction = self._normalize_relationship_direction(value.get("direction"), relation_type)
            mechanism = self._normalize_subject_key(value.get("mechanism") or channel or relation_type)
            confidence, confidence_score = self._normalize_relationship_confidence(value.get("confidence"), relation_type)
            provenance = self._normalize_relationship_provenance(value.get("provenance"))
            relationships.append(
                {
                    "source": source,
                    "target": target,
                    "type": relation_type,
                    "target_kind": target_kind,
                    "channel": channel,
                    "direction": direction,
                    "mechanism": mechanism,
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "provenance": provenance,
                    "valid_from": self._normalize_iso_date_string(value.get("valid_from")),
                    "valid_to": self._normalize_iso_date_string(value.get("valid_to")),
                    "state_condition": self._normalize_subject_key(value.get("state_condition")),
                    "strength": str(value.get("strength", "")).strip(),
                    "note": str(value.get("note", "")).strip(),
                }
            )
        return relationships

    def _normalize_relationship_type(self, value: object) -> str:
        normalized = self._normalize_subject_key(value)
        if normalized == "unknown":
            return ""
        return self._relationship_type_alias_map.get(normalized, normalized)

    def _normalize_relationship_target_kind(self, value: object) -> str:
        normalized = self._normalize_subject_key(value)
        if normalized == "unknown":
            return "industry"
        return self._relationship_target_kind_alias_map.get(normalized, normalized)

    def _canonicalize_transmission_channel(self, value: object) -> str:
        normalized = self._normalize_transmission_channel_values([value])
        return normalized[0] if normalized else ""

    def _canonicalize_relationship_target(self, value: object, target_kind: str) -> str:
        if target_kind == "ticker":
            return str(value or "").strip().upper()
        if target_kind == "macro_channel":
            definition = self.get_macro_channel_definition(str(value or ""))
            return str(definition.get("key") or self._normalize_subject_key(value))
        if target_kind == "theme":
            definition = self.get_theme_definition(str(value or ""))
            return str(definition.get("key") or self._normalize_subject_key(value))
        if target_kind == "sector":
            return self._resolve_sector_key(str(value or ""))
        return self._normalize_subject_key(value)

    def _normalize_relationship_direction(self, value: object, relation_type: str) -> str:
        normalized = self._normalize_subject_key(value)
        if normalized in {"positive", "negative", "mixed"}:
            return normalized
        type_defaults = {
            "benefits_from": "positive",
            "hurt_by": "negative",
            "sensitive_to": "mixed",
            "exposed_to_theme": "mixed",
            "linked_macro_channel": "mixed",
            "belongs_to_sector": "mixed",
            "belongs_to_industry": "mixed",
            "peer_of": "mixed",
            "supplier_to": "mixed",
            "customer_of": "mixed",
        }
        return type_defaults.get(relation_type, "mixed")

    def _normalize_relationship_confidence(self, value: object, relation_type: str) -> tuple[str, float]:
        default_bucket = {
            "benefits_from": "high",
            "hurt_by": "high",
            "sensitive_to": "medium",
            "exposed_to_theme": "medium",
            "linked_macro_channel": "medium",
            "belongs_to_sector": "high",
            "belongs_to_industry": "high",
            "peer_of": "medium",
            "supplier_to": "medium",
            "customer_of": "medium",
        }.get(relation_type, "medium")
        if isinstance(value, (int, float)):
            score = max(0.0, min(1.0, float(value)))
            bucket = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
            return bucket, round(score, 3)
        text = str(value or "").strip().lower()
        if not text:
            return default_bucket, {"low": 0.35, "medium": 0.65, "high": 0.9}.get(default_bucket, 0.65)
        if text in {"low", "medium", "high"}:
            return text, {"low": 0.35, "medium": 0.65, "high": 0.9}[text]
        try:
            score = max(0.0, min(1.0, float(text)))
        except ValueError:
            return default_bucket, {"low": 0.35, "medium": 0.65, "high": 0.9}.get(default_bucket, 0.65)
        bucket = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
        return bucket, round(score, 3)

    def _normalize_relationship_provenance(self, value: object) -> str:
        normalized = self._normalize_subject_key(value)
        if normalized in {"curated", "provider_backed", "derived", "heuristic"}:
            return normalized
        return "curated"

    @staticmethod
    def _normalize_iso_date_string(value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        try:
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            return text

    def get_ticker_profile(self, ticker: str) -> dict[str, Any]:
        normalized = ticker.upper()
        profile = dict(self._taxonomy.get(normalized, {}))
        if not profile:
            profile.update(self._fetch_external_profile(normalized))
        profile["ticker"] = normalized
        profile["company_name"] = str(profile.get("company_name") or normalized).strip() or normalized
        profile["aliases"] = self._normalize_string_list(profile.get("aliases")) or [normalized]
        profile["sector"] = str(profile.get("sector", "")).strip()
        profile["industry"] = str(profile.get("industry", "")).strip()
        profile["subindustry"] = str(profile.get("subindustry", "")).strip()
        profile["region"] = str(profile.get("region", "")).strip()
        profile["domicile"] = str(profile.get("domicile", "")).strip()
        profile["market_cap_bucket"] = str(profile.get("market_cap_bucket", "")).strip()
        profile["themes"] = self._normalize_theme_values(profile.get("themes"))
        profile["macro_sensitivity"] = self._normalize_macro_channel_values(profile.get("macro_sensitivity"))
        profile["industry_keywords"] = self._normalize_string_list(profile.get("industry_keywords"))
        profile["ticker_keywords"] = self._normalize_string_list(profile.get("ticker_keywords")) or [f"${normalized}", normalized]
        profile["exclude_keywords"] = [value.lower() for value in self._normalize_string_list(profile.get("exclude_keywords"))]
        profile["peers"] = self._normalize_ticker_list(profile.get("peers"))
        profile["suppliers"] = self._normalize_ticker_list(profile.get("suppliers"))
        profile["customers"] = self._normalize_ticker_list(profile.get("customers"))
        profile["exposure_channels"] = self._normalize_transmission_channel_values(profile.get("exposure_channels"))
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
                self._macro_channel_query_terms(profile.get("macro_sensitivity"), expand_lineage=True)
                + self._macro_channel_query_terms(industry_profile.get("macro_sensitivity"), expand_lineage=True)
            )
        )
        return {
            "ticker_queries": list(dict.fromkeys(ticker_queries + aliases)),
            "industry_queries": list(dict.fromkeys(industry_queries)),
            "macro_queries": macro_queries,
            "exclude_keywords": [str(value).strip().lower() for value in profile.get("exclude_keywords", []) if str(value).strip()],
        }

    def get_sector_definition(self, sector: str) -> dict[str, Any]:
        sector_key = self._resolve_sector_key(sector)
        definition = dict(self._sectors.get(sector_key, {"key": sector_key, "label": self._label_from_subject_key(sector_key), "queries": [], "themes": [], "macro_sensitivity": []}))
        definition["themes"] = self._normalize_theme_values(definition.get("themes"))
        definition["macro_sensitivity"] = self._normalize_macro_channel_values(definition.get("macro_sensitivity"))
        return definition

    def get_industry_definition(self, subject: str) -> dict[str, Any]:
        subject_key = self._subject_key_for_input(subject)
        explicit = dict(self._industries.get(subject_key, {}))
        return self._normalize_industry_definition(subject_key, explicit)

    def get_industry_profile(self, ticker: str) -> dict[str, Any]:
        ticker_profile = self.get_ticker_profile(ticker)
        industry = str(ticker_profile.get("industry", "")).strip()
        sector = str(ticker_profile.get("sector", "")).strip()
        subindustry = str(ticker_profile.get("subindustry", "")).strip()
        base_subject_key = self._normalize_subject_key(industry or sector or ticker_profile.get("ticker", ticker))
        base_subject_label = industry or sector or str(ticker_profile.get("ticker", ticker)).upper()
        explicit_definition = self.get_industry_definition(base_subject_key)
        has_explicit_industry = base_subject_key in self._industries
        sector_definition = self.get_sector_definition(explicit_definition.get("sector") or sector)

        subject_key = base_subject_key
        subject_label = explicit_definition.get("label") or base_subject_label
        resolution_mode = "taxonomy" if has_explicit_industry else "derived"
        if not has_explicit_industry and sector_definition.get("key") not in {"", "unknown"}:
            subject_key = str(sector_definition.get("key") or base_subject_key)
            subject_label = str(sector_definition.get("label") or sector or base_subject_label)
            resolution_mode = "sector_fallback" if industry else "sector_only"

        themes = self._normalize_string_list(ticker_profile.get("themes"))
        industry_keywords = self._normalize_string_list(ticker_profile.get("industry_keywords"))
        event_vocab = self._normalize_string_list(explicit_definition.get("event_vocab")) + self._normalize_string_list(ticker_profile.get("event_vocab")) + self._event_vocab.get(subject_key, [])
        derived_queries = industry_keywords + self._theme_query_terms(themes) + ([subindustry] if subindustry else []) + ([industry] if industry else []) + ([sector] if sector else [])
        relationships = self.list_relationships(subject_key, direction="outbound")
        return {
            "subject_key": subject_key,
            "subject_label": subject_label,
            "industry": industry,
            "sector": explicit_definition.get("sector") or sector_definition.get("label") or sector,
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
                    self._normalize_transmission_channel_values(explicit_definition.get("transmission_channels"))
                    + self._normalize_transmission_channel_values(ticker_profile.get("exposure_channels"))
                )
            ),
            "peer_industries": self._normalize_string_list(explicit_definition.get("peer_industries")),
            "risk_flags": self._normalize_string_list(explicit_definition.get("risk_flags")),
            "event_vocab": list(dict.fromkeys(event_vocab)),
            "regions": list(dict.fromkeys([value for value in [ticker_profile.get("region")] if value])),
            "domiciles": list(dict.fromkeys([value for value in [ticker_profile.get("domicile")] if value])),
            "relationships": relationships,
            "ticker": ticker_profile.get("ticker", ticker).upper(),
            "resolution_mode": resolution_mode,
        }

    def list_industry_profiles(self) -> list[dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for sector_key, definition in self._sectors.items():
            profiles[sector_key] = {
                "subject_key": sector_key,
                "subject_label": definition.get("label") or self._label_from_subject_key(sector_key),
                "industry": "",
                "sector": definition.get("label") or self._label_from_subject_key(sector_key),
                "sector_definition": definition,
                "queries": self._normalize_string_list(definition.get("queries")),
                "themes": self._normalize_string_list(definition.get("themes")),
                "macro_sensitivity": self._normalize_string_list(definition.get("macro_sensitivity")),
                "transmission_channels": [],
                "peer_industries": [],
                "risk_flags": [],
                "event_vocab": list(dict.fromkeys(self._event_vocab.get(sector_key, []))),
                "tickers": [],
                "regions": [],
                "domiciles": [],
                "companies": [],
                "relationships": self.list_relationships(sector_key, direction="outbound"),
                "resolution_mode": "sector_seed",
            }
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
                "transmission_channels": self._normalize_transmission_channel_values(definition.get("transmission_channels")),
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

    def _derived_relationships(self, subject_key: str | None = None) -> list[dict[str, Any]]:
        if subject_key is None:
            derived: list[dict[str, Any]] = []
            for key in sorted(set(self._industries) | set(self._sectors)):
                derived.extend(self._derived_relationships(key))
            return derived
        normalized = self._normalize_subject_key(subject_key)
        derived: list[dict[str, Any]] = []
        if normalized in self._industries:
            definition = self.get_industry_definition(normalized)
            sector_key = self._resolve_sector_key(str(definition.get("sector", "")))
            if sector_key and sector_key not in {"", "unknown"} and sector_key in self._sectors:
                derived.append(
                    {
                        "source": normalized,
                        "target": sector_key,
                        "type": "belongs_to_sector",
                        "target_kind": "sector",
                        "channel": "",
                        "strength": "structural",
                        "note": "industry classification edge",
                    }
                )
            for raw_macro in self._normalize_string_list(definition.get("macro_sensitivity")):
                macro_definition = self.get_macro_channel_definition(raw_macro)
                macro_key = str(macro_definition.get("key", "")).strip()
                if macro_key and macro_key != "unknown":
                    derived.append(
                        {
                            "source": normalized,
                            "target": macro_key,
                            "type": "linked_macro_channel",
                            "target_kind": "macro_channel",
                            "channel": "",
                            "strength": "structural",
                            "note": "industry macro sensitivity mapping",
                        }
                    )
            for raw_theme in self._normalize_string_list(definition.get("themes")):
                theme_definition = self.get_theme_definition(raw_theme)
                theme_key = str(theme_definition.get("key", "")).strip()
                if theme_key and theme_key != "unknown":
                    derived.append(
                        {
                            "source": normalized,
                            "target": theme_key,
                            "type": "exposed_to_theme",
                            "target_kind": "theme",
                            "channel": "theme",
                            "direction": "mixed",
                            "mechanism": "theme_exposure",
                            "confidence": "low",
                            "confidence_score": 0.45,
                            "provenance": "derived",
                            "valid_from": "",
                            "valid_to": "",
                            "state_condition": "",
                            "strength": "structural",
                            "note": "industry theme exposure mapping",
                        }
                    )
        elif normalized in self._sectors:
            definition = self.get_sector_definition(normalized)
            for raw_macro in self._normalize_string_list(definition.get("macro_sensitivity")):
                macro_definition = self.get_macro_channel_definition(raw_macro)
                macro_key = str(macro_definition.get("key", "")).strip()
                if macro_key and macro_key != "unknown":
                    derived.append(
                        {
                            "source": normalized,
                            "target": macro_key,
                            "type": "linked_macro_channel",
                            "target_kind": "macro_channel",
                            "channel": "macro_channel",
                            "direction": "mixed",
                            "mechanism": "macro_transmission",
                            "confidence": "low",
                            "confidence_score": 0.45,
                            "provenance": "derived",
                            "valid_from": "",
                            "valid_to": "",
                            "state_condition": "",
                            "strength": "structural",
                            "note": "sector macro sensitivity mapping",
                        }
                    )
            for raw_theme in self._normalize_string_list(definition.get("themes")):
                theme_definition = self.get_theme_definition(raw_theme)
                theme_key = str(theme_definition.get("key", "")).strip()
                if theme_key and theme_key != "unknown":
                    derived.append(
                        {
                            "source": normalized,
                            "target": theme_key,
                            "type": "exposed_to_theme",
                            "target_kind": "theme",
                            "channel": "theme",
                            "direction": "mixed",
                            "mechanism": "theme_exposure",
                            "confidence": "low",
                            "confidence_score": 0.45,
                            "provenance": "derived",
                            "valid_from": "",
                            "valid_to": "",
                            "state_condition": "",
                            "strength": "structural",
                            "note": "sector theme exposure mapping",
                        }
                    )
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for item in derived:
            key = (
                str(item.get("source", "")),
                str(item.get("type", "")),
                str(item.get("target_kind", "")),
                str(item.get("target", "")),
                str(item.get("channel", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _relationship_is_effective(self, relationship: dict[str, Any], as_of: object | None = None) -> bool:
        if as_of is None:
            return True
        if isinstance(as_of, datetime):
            effective_date = as_of.date()
        else:
            text = str(as_of).strip()
            if not text:
                return True
            try:
                effective_date = datetime.fromisoformat(text).date()
            except ValueError:
                return True
        valid_from = str(relationship.get("valid_from", "")).strip()
        valid_to = str(relationship.get("valid_to", "")).strip()
        if valid_from:
            try:
                if effective_date < datetime.fromisoformat(valid_from).date():
                    return False
            except ValueError:
                pass
        if valid_to:
            try:
                if effective_date > datetime.fromisoformat(valid_to).date():
                    return False
            except ValueError:
                pass
        return True

    def list_relationships(self, subject_key: str | None = None, *, direction: str = "any", as_of: object | None = None) -> list[dict[str, Any]]:
        normalized = self._normalize_subject_key(subject_key) if subject_key else None
        relationships = [
            self._enrich_relationship(relationship)
            for relationship in [*self._relationships, *self._derived_relationships(normalized)]
            if self._relationship_is_effective(relationship, as_of)
        ]
        if normalized is None:
            return list(relationships)
        if direction == "outbound":
            return [relationship for relationship in relationships if relationship.get("source") == normalized]
        if direction == "inbound":
            return [relationship for relationship in relationships if relationship.get("target") == normalized]
        return [relationship for relationship in relationships if relationship.get("source") == normalized or relationship.get("target") == normalized]

    def _enrich_relationship(self, relationship: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(relationship)
        source = str(enriched.get("source", "")).strip()
        target = str(enriched.get("target", "")).strip()
        target_kind = str(enriched.get("target_kind", "industry")).strip() or "industry"
        relation_type = str(enriched.get("type", "")).strip()
        source_label = self._label_for_relationship_subject(source)
        if source_label:
            enriched["source_label"] = source_label
        if target_kind == "macro_channel":
            definition = self.get_macro_channel_definition(target)
            if definition.get("label"):
                enriched["target_label"] = definition.get("label")
        elif target_kind == "industry":
            definition = self.get_industry_definition(target)
            if definition.get("label"):
                enriched["target_label"] = definition.get("label")
        elif target_kind == "sector":
            definition = self.get_sector_definition(target)
            if definition.get("label"):
                enriched["target_label"] = definition.get("label")
        elif target_kind == "theme":
            definition = self.get_theme_definition(target)
            if definition.get("label"):
                enriched["target_label"] = definition.get("label")
        elif target_kind == "ticker":
            definition = self.get_ticker_profile(target)
            if definition.get("company_name"):
                enriched["target_label"] = definition.get("company_name")
        type_definition = self.get_relationship_type_definition(relation_type)
        if type_definition.get("label"):
            enriched["type_label"] = type_definition.get("label")
        target_kind_definition = self.get_relationship_target_kind_definition(target_kind)
        if target_kind_definition.get("label"):
            enriched["target_kind_label"] = target_kind_definition.get("label")
        channel_definition = self.get_transmission_channel_definition(str(enriched.get("channel", "")))
        if channel_definition.get("label"):
            enriched["channel_label"] = channel_definition.get("label")
        enriched["relationship_score"] = self._relationship_score(enriched)
        return enriched

    @staticmethod
    def _relationship_strength_score(relationship: dict[str, Any]) -> float:
        strength = str(relationship.get("strength", "")).strip().lower()
        return {
            "structural": 0.9,
            "high": 0.85,
            "medium": 0.65,
            "low": 0.4,
            "weak": 0.3,
        }.get(strength, 0.55)

    def _relationship_score(self, relationship: dict[str, Any]) -> float:
        confidence_score = relationship.get("confidence_score")
        if isinstance(confidence_score, (int, float)):
            confidence = max(0.0, min(1.0, float(confidence_score)))
        else:
            confidence = {"low": 0.35, "medium": 0.65, "high": 0.9}.get(str(relationship.get("confidence", "")).strip().lower(), 0.6)
        strength_score = self._relationship_strength_score(relationship)
        direction = str(relationship.get("direction", "")).strip().lower()
        direction_bonus = 0.03 if direction in {"positive", "negative"} else 0.0
        return round(min(1.0, (confidence * 0.75) + (strength_score * 0.22) + direction_bonus), 3)

    def get_ticker_relationships(self, ticker: str, *, as_of: object | None = None) -> list[dict[str, Any]]:
        profile = self.get_ticker_profile(ticker)
        industry_profile = self.get_industry_profile(ticker)
        relationships: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        def add_relationship(relationship: dict[str, Any]) -> None:
            key = (
                str(relationship.get("source", "")),
                str(relationship.get("type", "")),
                str(relationship.get("target_kind", "")),
                str(relationship.get("target", "")),
                str(relationship.get("channel", "")),
            )
            if key in seen:
                return
            if not self._relationship_is_effective(relationship, as_of):
                return
            seen.add(key)
            relationship["relationship_score"] = self._relationship_score(relationship)
            relationships.append(relationship)

        mapping = (
            ("peers", "peer_of", "competitive_position", "peer read-through and competitive positioning"),
            ("suppliers", "supplier_to", "supply_chain", "supplier and component dependency"),
            ("customers", "customer_of", "customer_demand", "customer demand read-through"),
        )
        for field, relation_type, channel, note in mapping:
            for target in self._normalize_ticker_list(profile.get(field)):
                target_profile = self.get_ticker_profile(target)
                add_relationship(
                    {
                        "source": profile["ticker"],
                        "source_label": profile.get("company_name", profile["ticker"]),
                        "type": relation_type,
                        "type_label": self.get_relationship_type_definition(relation_type).get("label", relation_type.replace("_", " ")),
                        "target": target,
                        "target_kind": "ticker",
                        "target_kind_label": self.get_relationship_target_kind_definition("ticker").get("label", "ticker"),
                        "target_label": target_profile.get("company_name", target),
                        "target_industry": target_profile.get("industry", ""),
                        "channel": channel,
                        "channel_label": self.get_transmission_channel_definition(channel).get("label", channel.replace("_", " ")),
                        "direction": "mixed",
                        "mechanism": channel,
                        "confidence": "medium",
                        "confidence_score": 0.65,
                        "provenance": "curated",
                        "valid_from": "",
                        "valid_to": "",
                        "state_condition": "",
                        "strength": "medium",
                        "note": note,
                    }
                )

        industry_key = self._subject_key_for_input(str(profile.get("industry", "")))
        if industry_key in self._industries:
            add_relationship(
                {
                    "source": profile["ticker"],
                    "source_label": profile.get("company_name", profile["ticker"]),
                    "type": "belongs_to_industry",
                    "type_label": self.get_relationship_type_definition("belongs_to_industry").get("label", "belongs to industry"),
                    "target": industry_key,
                    "target_kind": "industry",
                    "target_kind_label": self.get_relationship_target_kind_definition("industry").get("label", "industry"),
                    "target_label": industry_profile.get("subject_label") or industry_profile.get("industry") or industry_key.replace("_", " "),
                    "channel": "",
                    "channel_label": "",
                    "direction": "mixed",
                    "mechanism": "classification",
                    "confidence": "high",
                    "confidence_score": 0.9,
                    "provenance": "curated",
                    "valid_from": "",
                    "valid_to": "",
                    "state_condition": "",
                    "strength": "structural",
                    "note": "ticker industry classification edge",
                }
            )

        sector_key = str(industry_profile.get("sector_definition", {}).get("key", "")).strip()
        if sector_key in self._sectors:
            add_relationship(
                {
                    "source": profile["ticker"],
                    "source_label": profile.get("company_name", profile["ticker"]),
                    "type": "belongs_to_sector",
                    "type_label": self.get_relationship_type_definition("belongs_to_sector").get("label", "belongs to sector"),
                    "target": sector_key,
                    "target_kind": "sector",
                    "target_kind_label": self.get_relationship_target_kind_definition("sector").get("label", "sector"),
                    "target_label": industry_profile.get("sector_definition", {}).get("label") or sector_key.replace("_", " "),
                    "channel": "",
                    "channel_label": "",
                    "direction": "mixed",
                    "mechanism": "classification",
                    "confidence": "high",
                    "confidence_score": 0.9,
                    "provenance": "curated",
                    "valid_from": "",
                    "valid_to": "",
                    "state_condition": "",
                    "strength": "structural",
                    "note": "ticker sector classification edge",
                }
            )

        macro_terms = list(
            dict.fromkeys(
                self._normalize_macro_channel_values(profile.get("macro_sensitivity"))
                + self._normalize_macro_channel_values(industry_profile.get("macro_sensitivity"))
            )
        )
        for raw_macro in macro_terms:
            macro_definition = self.get_macro_channel_definition(raw_macro)
            macro_key = str(macro_definition.get("key", "")).strip()
            if not macro_key or macro_key == "unknown":
                continue
            add_relationship(
                {
                    "source": profile["ticker"],
                    "source_label": profile.get("company_name", profile["ticker"]),
                    "type": "linked_macro_channel",
                    "type_label": self.get_relationship_type_definition("linked_macro_channel").get("label", "linked macro channel"),
                    "target": macro_key,
                    "target_kind": "macro_channel",
                    "target_kind_label": self.get_relationship_target_kind_definition("macro_channel").get("label", "macro channel"),
                    "target_label": macro_definition.get("label") or macro_key.replace("_", " "),
                    "channel": "macro_channel",
                    "channel_label": self.get_transmission_channel_definition("macro_channel").get("label", "macro channel"),
                    "direction": "mixed",
                    "mechanism": "macro_transmission",
                    "confidence": "medium",
                    "confidence_score": 0.65,
                    "provenance": "derived",
                    "valid_from": "",
                    "valid_to": "",
                    "state_condition": "",
                    "strength": "structural",
                    "note": "ticker macro sensitivity mapping",
                }
            )
        return relationships

    def taxonomy_overview(self) -> dict[str, Any]:
        relationship_direction_count = sum(1 for item in self._relationships if str(item.get("direction", "")).strip())
        relationship_mechanism_count = sum(1 for item in self._relationships if str(item.get("mechanism", "")).strip())
        relationship_confidence_count = sum(1 for item in self._relationships if str(item.get("confidence", "")).strip())
        relationship_provenance_count = sum(1 for item in self._relationships if str(item.get("provenance", "")).strip())
        relationship_validity_count = sum(1 for item in self._relationships if str(item.get("valid_from", "")).strip() or str(item.get("valid_to", "")).strip())
        ticker_peer_link_count = sum(len(self._normalize_ticker_list(profile.get("peers"))) for profile in self._taxonomy.values())
        ticker_supplier_link_count = sum(len(self._normalize_ticker_list(profile.get("suppliers"))) for profile in self._taxonomy.values())
        ticker_customer_link_count = sum(len(self._normalize_ticker_list(profile.get("customers"))) for profile in self._taxonomy.values())
        ticker_with_peer_count = sum(1 for profile in self._taxonomy.values() if self._normalize_ticker_list(profile.get("peers")))
        ticker_with_supplier_count = sum(1 for profile in self._taxonomy.values() if self._normalize_ticker_list(profile.get("suppliers")))
        ticker_with_customer_count = sum(1 for profile in self._taxonomy.values() if self._normalize_ticker_list(profile.get("customers")))
        ticker_industry_link_count = sum(
            1
            for profile in self._taxonomy.values()
            if self._subject_key_for_input(str(profile.get("industry", ""))) in self._industries
        )
        ticker_sector_link_count = sum(
            1
            for profile in self._taxonomy.values()
            if self._resolve_sector_key(str(profile.get("sector", ""))) in self._sectors
        )
        ticker_macro_link_count = 0
        for profile in self._taxonomy.values():
            subject_key = self._subject_key_for_input(str(profile.get("industry", "")))
            industry_macro_sensitivity = self._industries.get(subject_key, {}).get("macro_sensitivity", []) if subject_key in self._industries else []
            macro_keys = {
                str(self.get_macro_channel_definition(raw_macro).get("key", "")).strip()
                for raw_macro in dict.fromkeys(
                    self._normalize_macro_channel_values(profile.get("macro_sensitivity"))
                    + self._normalize_macro_channel_values(industry_macro_sensitivity)
                )
            }
            ticker_macro_link_count += sum(1 for macro_key in macro_keys if macro_key and macro_key != "unknown")
        return {
            "source_mode": self._source_mode,
            "ticker_count": len(self._taxonomy),
            "industry_count": len(self._industries),
            "sector_count": len(self._sectors),
            "relationship_count": len(self._relationships),
            "relationship_direction_count": relationship_direction_count,
            "relationship_mechanism_count": relationship_mechanism_count,
            "relationship_confidence_count": relationship_confidence_count,
            "relationship_provenance_count": relationship_provenance_count,
            "relationship_validity_count": relationship_validity_count,
            "event_vocab_group_count": len(self._event_vocab),
            "theme_count": len(self._themes),
            "theme_parent_count": sum(1 for item in self._themes.values() if str(item.get("parent", "")).strip()),
            "macro_channel_count": len(self._macro_channels),
            "macro_channel_parent_count": sum(1 for item in self._macro_channels.values() if str(item.get("parent", "")).strip()),
            "transmission_channel_count": len(self._transmission_channels),
            "transmission_tag_count": len(self._transmission_tags),
            "transmission_primary_driver_count": len(self._transmission_primary_drivers),
            "transmission_conflict_flag_count": len(self._transmission_conflict_flags),
            "transmission_bias_count": len(self._transmission_biases),
            "transmission_context_regime_count": len(self._transmission_context_regimes),
            "transmission_window_count": len(self._transmission_windows),
            "shortlist_reason_code_count": len(self._shortlist_reason_codes),
            "shortlist_selection_lane_count": len(self._shortlist_selection_lanes),
            "calibration_review_status_count": len(self._calibration_review_statuses),
            "calibration_reason_code_count": len(self._calibration_reason_codes),
            "action_reason_code_count": len(self._action_reason_codes),
            "contradiction_reason_code_count": len(self._contradiction_reason_codes),
            "event_source_priority_count": len(self._event_source_priorities),
            "event_persistence_state_count": len(self._event_persistence_states),
            "event_window_hint_count": len(self._event_window_hints),
            "event_recency_bucket_count": len(self._event_recency_buckets),
            "relationship_type_count": len(self._relationship_types),
            "relationship_target_kind_count": len(self._relationship_target_kinds),
            "derived_relationship_count": len(self._derived_relationships()),
            "ticker_peer_link_count": ticker_peer_link_count,
            "ticker_supplier_link_count": ticker_supplier_link_count,
            "ticker_customer_link_count": ticker_customer_link_count,
            "ticker_with_peer_count": ticker_with_peer_count,
            "ticker_with_supplier_count": ticker_with_supplier_count,
            "ticker_with_customer_count": ticker_with_customer_count,
            "ticker_industry_link_count": ticker_industry_link_count,
            "ticker_sector_link_count": ticker_sector_link_count,
            "ticker_macro_link_count": ticker_macro_link_count,
        }

    def _fetch_external_profile(self, ticker: str) -> dict[str, Any]:
        cached = self._external_profile_cache.get(ticker)
        if cached is not None:
            return dict(cached)
        if self._metadata_provider is not None:
            payload = self._metadata_provider(ticker) or {}
            normalized = payload if isinstance(payload, dict) else {}
            self._external_profile_cache[ticker] = dict(normalized)
            return dict(normalized)
        try:
            import yfinance as yf

            info = yf.Ticker(ticker).info
        except Exception:
            self._external_profile_cache[ticker] = {}
            return {}
        if not isinstance(info, dict):
            self._external_profile_cache[ticker] = {}
            return {}
        profile = {
            "company_name": str(info.get("longName") or info.get("shortName") or ticker).strip() or ticker,
            "sector": str(info.get("sectorDisp") or info.get("sector") or "").strip(),
            "industry": str(info.get("industryDisp") or info.get("industry") or "").strip(),
            "region": str(info.get("region") or info.get("country") or "").strip(),
            "domicile": str(info.get("country") or "").strip(),
        }
        self._external_profile_cache[ticker] = dict(profile)
        return profile

    def _resolve_sector_key(self, sector: str) -> str:
        normalized = self._normalize_subject_key(sector)
        if normalized in self._sectors:
            return normalized
        alias = SECTOR_ALIASES.get(normalized)
        if alias and alias in self._sectors:
            return alias
        normalized_tokens = set(normalized.split("_"))
        for sector_key, definition in self._sectors.items():
            label_tokens = set(self._normalize_subject_key(definition.get("label", "")).split("_"))
            if normalized_tokens and (normalized_tokens <= label_tokens or label_tokens <= normalized_tokens):
                return sector_key
        return normalized

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
            "themes": self._normalize_theme_values(payload.get("themes")),
            "macro_sensitivity": self._normalize_macro_channel_values(payload.get("macro_sensitivity")),
            "transmission_channels": self._normalize_transmission_channel_values(payload.get("transmission_channels")),
            "peer_industries": [self._normalize_subject_key(value) for value in self._normalize_string_list(payload.get("peer_industries"))],
            "risk_flags": self._normalize_string_list(payload.get("risk_flags")),
            "event_vocab": self._normalize_string_list(payload.get("event_vocab")),
            "tickers": self._normalize_ticker_list(payload.get("tickers")),
            "regions": self._normalize_string_list(payload.get("regions")),
            "domiciles": self._normalize_string_list(payload.get("domiciles")),
            "companies": self._normalize_string_list(payload.get("companies")),
        }

    @staticmethod
    def _build_alias_map(registry: dict[str, dict[str, Any]]) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        for key, definition in registry.items():
            aliases = [key, str(definition.get("label", "")).strip(), *[str(value).strip() for value in definition.get("aliases", []) if str(value).strip()]]
            for alias in aliases:
                normalized_alias = TickerTaxonomyService._normalize_subject_key(alias)
                if normalized_alias and normalized_alias != "unknown":
                    alias_map[normalized_alias] = key
        return alias_map

    def _normalize_registry_values(self, values: object, alias_map: dict[str, str], registry: dict[str, dict[str, Any]]) -> list[str]:
        raw_values = self._normalize_string_list(values)
        normalized: list[str] = []
        for value in raw_values:
            canonical_key = alias_map.get(self._normalize_subject_key(value))
            if canonical_key and canonical_key in registry:
                label = str(registry[canonical_key].get("label", value)).strip() or value
                if label not in normalized:
                    normalized.append(label)
                continue
            if value not in normalized:
                normalized.append(value)
        return normalized

    def _normalize_theme_values(self, values: object) -> list[str]:
        return self._normalize_registry_values(values, self._theme_alias_map if hasattr(self, "_theme_alias_map") else {}, self._themes if hasattr(self, "_themes") else {})

    def _normalize_macro_channel_values(self, values: object) -> list[str]:
        return self._normalize_registry_values(values, self._macro_channel_alias_map if hasattr(self, "_macro_channel_alias_map") else {}, self._macro_channels if hasattr(self, "_macro_channels") else {})

    def _normalize_transmission_channel_values(self, values: object) -> list[str]:
        raw_values = self._normalize_string_list(values)
        normalized: list[str] = []
        for value in raw_values:
            canonical_key = self._transmission_channel_alias_map.get(self._normalize_subject_key(value)) if hasattr(self, "_transmission_channel_alias_map") else None
            if canonical_key and canonical_key not in normalized:
                normalized.append(canonical_key)
                continue
            if value not in normalized:
                normalized.append(value)
        return normalized

    def _macro_channel_query_terms(self, values: object, *, expand_lineage: bool = False) -> list[str]:
        terms: list[str] = []
        sources = self._registry_lineage_keys(self._macro_channels, values) if expand_lineage else self._normalize_string_list(values)
        for value in sources:
            canonical_key = self._macro_channel_alias_map.get(self._normalize_subject_key(value))
            if canonical_key and canonical_key in self._macro_channels:
                definition = self._macro_channels[canonical_key]
                candidates = [definition.get("label", ""), *self._normalize_string_list(definition.get("aliases"))]
                for candidate in candidates:
                    text = str(candidate).strip().replace("_", " ")
                    if text and text not in terms:
                        terms.append(text)
                continue
            text = str(value).strip()
            if text and text not in terms:
                terms.append(text)
        return terms

    def _theme_query_terms(self, values: object) -> list[str]:
        terms: list[str] = []
        for value in self._registry_lineage_keys(self._themes, values):
            canonical_key = self._theme_alias_map.get(self._normalize_subject_key(value))
            if canonical_key and canonical_key in self._themes:
                definition = self._themes[canonical_key]
                candidates = [definition.get("label", ""), *self._normalize_string_list(definition.get("aliases"))]
                for candidate in candidates:
                    text = str(candidate).strip().replace("_", " ")
                    if text and text not in terms:
                        terms.append(text)
                continue
            text = str(value).strip()
            if text and text not in terms:
                terms.append(text)
        return terms

    def get_theme_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._theme_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._themes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip(), "aliases": []}))

    def list_theme_definitions(self) -> list[dict[str, Any]]:
        return [self.get_theme_definition(key) for key in sorted(self._themes)]

    def get_macro_channel_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._macro_channel_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._macro_channels.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_macro_channel_definitions(self) -> list[dict[str, Any]]:
        return [self.get_macro_channel_definition(key) for key in sorted(self._macro_channels)]

    def get_transmission_channel_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_channel_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_channels.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_channel_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_channel_definition(key) for key in sorted(self._transmission_channels)]

    def get_transmission_tag_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_tag_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_tags.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_tag_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_tag_definition(key) for key in sorted(self._transmission_tags)]

    def get_transmission_primary_driver_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_primary_driver_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_primary_drivers.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_primary_driver_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_primary_driver_definition(key) for key in sorted(self._transmission_primary_drivers)]

    def get_transmission_conflict_flag_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_conflict_flag_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_conflict_flags.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_conflict_flag_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_conflict_flag_definition(key) for key in sorted(self._transmission_conflict_flags)]

    def get_transmission_bias_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_bias_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_biases.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_bias_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_bias_definition(key) for key in sorted(self._transmission_biases)]

    def derive_transmission_bias(self, transmission_summary: dict[str, Any] | None) -> str:
        if not isinstance(transmission_summary, dict):
            return "unknown"
        return self.get_transmission_bias_definition(str(transmission_summary.get("context_bias", "unknown") or "unknown")).get("key", "unknown")

    def get_transmission_context_regime_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_context_regime_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_context_regimes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_context_regime_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_context_regime_definition(key) for key in sorted(self._transmission_context_regimes)]

    def get_transmission_window_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._transmission_window_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._transmission_windows.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_transmission_window_definitions(self) -> list[dict[str, Any]]:
        return [self.get_transmission_window_definition(key) for key in sorted(self._transmission_windows)]

    def derive_transmission_context_regime(self, transmission_summary: dict[str, Any] | None) -> str:
        if not isinstance(transmission_summary, dict):
            return "mixed_context"
        tags = transmission_summary.get("transmission_tags")
        normalized_tags = {
            self.get_transmission_tag_definition(str(item)).get("key", self._normalize_subject_key(item))
            for item in (tags if isinstance(tags, list) else [])
            if isinstance(item, str) and item.strip()
        }
        if "catalyst_active" in normalized_tags and ("macro_dominant" in normalized_tags or "industry_dominant" in normalized_tags):
            return "context_plus_catalyst"
        if "macro_dominant" in normalized_tags and "industry_dominant" in normalized_tags:
            return "macro_and_industry"
        if "macro_dominant" in normalized_tags:
            return "macro_dominant"
        if "industry_dominant" in normalized_tags:
            return "industry_dominant"
        if "catalyst_active" in normalized_tags:
            return "catalyst_active"
        bias = self.derive_transmission_bias(transmission_summary)
        if bias == "tailwind":
            return "tailwind_without_dominant_tag"
        if bias == "headwind":
            return "headwind_without_dominant_tag"
        return "mixed_context"

    def get_analysis_slice_label(self, slice_name: str) -> str:
        labels = {
            "setup_family": "setup family",
            "horizon": "horizon",
            "confidence_bucket": "confidence bucket",
            "transmission_bias": "transmission bias",
            "context_regime": "context regime",
            "horizon_setup_family": "horizon + setup family",
        }
        normalized = self._normalize_subject_key(slice_name)
        return labels.get(normalized, str(slice_name or "").strip().replace("_", " "))

    def get_analysis_bucket_label(self, group_by: str, key: str) -> str:
        normalized_group = self._normalize_subject_key(group_by)
        normalized_key = str(key or "").strip()
        if "__" in normalized_key:
            return normalized_key.replace("__", " / ").replace("_", " ")
        if normalized_group == "transmission_bias":
            definition = self.get_transmission_bias_definition(normalized_key)
            if definition.get("key") in self._transmission_biases:
                return str(definition.get("label", normalized_key.replace("_", " ")))
        if normalized_group == "context_regime":
            definition = self.get_transmission_context_regime_definition(normalized_key)
            if definition.get("key") in self._transmission_context_regimes:
                return str(definition.get("label", normalized_key.replace("_", " ")))
        return normalized_key.replace("_", " ")

    def get_shortlist_reason_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._shortlist_reason_code_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._shortlist_reason_codes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_shortlist_reason_definitions(self) -> list[dict[str, Any]]:
        return [self.get_shortlist_reason_definition(key) for key in sorted(self._shortlist_reason_codes)]

    def get_shortlist_selection_lane_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._shortlist_selection_lane_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._shortlist_selection_lanes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_shortlist_selection_lane_definitions(self) -> list[dict[str, Any]]:
        return [self.get_shortlist_selection_lane_definition(key) for key in sorted(self._shortlist_selection_lanes)]

    def get_calibration_review_status_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._calibration_review_status_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._calibration_review_statuses.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_calibration_review_status_definitions(self) -> list[dict[str, Any]]:
        return [self.get_calibration_review_status_definition(key) for key in sorted(self._calibration_review_statuses)]

    def get_calibration_reason_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._calibration_reason_code_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._calibration_reason_codes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_calibration_reason_definitions(self) -> list[dict[str, Any]]:
        return [self.get_calibration_reason_definition(key) for key in sorted(self._calibration_reason_codes)]

    def get_action_reason_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._action_reason_code_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._action_reason_codes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_action_reason_definitions(self) -> list[dict[str, Any]]:
        return [self.get_action_reason_definition(key) for key in sorted(self._action_reason_codes)]

    def get_contradiction_reason_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._contradiction_reason_code_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._contradiction_reason_codes.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_contradiction_reason_definitions(self) -> list[dict[str, Any]]:
        return [self.get_contradiction_reason_definition(key) for key in sorted(self._contradiction_reason_codes)]

    def get_event_source_priority_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._event_source_priority_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._event_source_priorities.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def get_event_persistence_state_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._event_persistence_state_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._event_persistence_states.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def get_event_window_hint_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._event_window_hint_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._event_window_hints.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def get_event_recency_bucket_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._event_recency_bucket_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._event_recency_buckets.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def get_relationship_type_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._relationship_type_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._relationship_types.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_relationship_type_definitions(self) -> list[dict[str, Any]]:
        return [self.get_relationship_type_definition(key) for key in sorted(self._relationship_types)]

    def get_relationship_target_kind_definition(self, value: str) -> dict[str, Any]:
        canonical_key = self._relationship_target_kind_alias_map.get(self._normalize_subject_key(value), self._normalize_subject_key(value))
        return dict(self._relationship_target_kinds.get(canonical_key, {"key": canonical_key, "label": str(value or "").strip().replace("_", " "), "aliases": []}))

    def list_relationship_target_kind_definitions(self) -> list[dict[str, Any]]:
        return [self.get_relationship_target_kind_definition(key) for key in sorted(self._relationship_target_kinds)]

    def _label_for_relationship_subject(self, subject: str) -> str:
        normalized = self._normalize_subject_key(subject)
        if normalized in self._industries:
            return str(self.get_industry_definition(normalized).get("label", "")).strip()
        if normalized in self._sectors:
            return str(self.get_sector_definition(normalized).get("label", "")).strip()
        ticker = str(subject or "").strip().upper()
        if ticker:
            return str(self.get_ticker_profile(ticker).get("company_name", ticker)).strip()
        return ""

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

    def _registry_lineage_keys(self, registry: dict[str, dict[str, Any]], values: object) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for value in self._normalize_string_list(values):
            key = self._normalize_subject_key(value)
            while key and key != "unknown" and key not in seen:
                seen.add(key)
                keys.append(key)
                entry = registry.get(key) or {}
                parent = self._normalize_subject_key(entry.get("parent"))
                if parent in {"", "unknown", key}:
                    break
                key = parent
        return keys

    def _registry_lineage_terms(self, registry: dict[str, dict[str, Any]], values: object) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for key in self._registry_lineage_keys(registry, values):
            entry = registry.get(key) or {}
            for candidate in [entry.get("label"), *self._normalize_string_list(entry.get("aliases"))]:
                text = str(candidate or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    terms.append(text)
        return terms

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
