from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trade_proposer_app.domain.enums import RecommendationDirection
from trade_proposer_app.services.taxonomy import DATA_DIR

ONTOLOGY_PATH = DATA_DIR / "taxonomy" / "ticker_exposure_ontology.json"

_STRENGTH_SCORE = {"low": 0.35, "medium": 0.65, "high": 0.9, "structural": 0.95}
_DIRECTION_SIGN = {"positive": 1.0, "negative": -1.0, "mixed": 0.0}


class TickerExposureOntologyService:
    """Broker-agnostic ticker exposure graph matcher for context transmission."""

    _shared_payload_cache: dict[Path, dict[str, Any]] = {}

    def __init__(self, ontology_path: Path | None = None) -> None:
        self.ontology_path = ontology_path or ONTOLOGY_PATH
        self._payload = self._load_shared_payload(self.ontology_path)
        self._profiles = {
            str(key).strip().upper(): value
            for key, value in self._payload.items()
            if not str(key).startswith("_") and isinstance(value, dict)
        }
        meta = self._payload.get("_meta") if isinstance(self._payload.get("_meta"), dict) else {}
        self.version = str(meta.get("version") or "unknown")

    @classmethod
    def _load_shared_payload(cls, path: Path) -> dict[str, Any]:
        cached = cls._shared_payload_cache.get(path)
        if cached is not None:
            return cached
        if not path.exists():
            payload: dict[str, Any] = {}
        else:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            payload = raw if isinstance(raw, dict) else {}
        cls._shared_payload_cache[path] = payload
        return payload

    def get_profile(self, ticker: str, *, taxonomy_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = ticker.strip().upper()
        base = dict(taxonomy_profile or {})
        explicit = dict(self._profiles.get(normalized, {}))
        template = {} if explicit else self._template_profile(base)
        profile = {**base, **template, **explicit}
        profile["ticker"] = normalized
        profile["source"] = str(profile.get("source") or ("curated" if explicit else "taxonomy_derived"))
        profile["version"] = str(profile.get("version") or self.version)
        profile["confidence_score"] = self._number(profile.get("confidence_score"), default=0.45 if explicit or template else 0.25)
        for key in (
            "revenue_drivers",
            "cost_drivers",
            "customer_segments",
            "geographic_exposure",
            "peers",
            "suppliers",
            "customers",
            "related_etfs",
        ):
            profile[key] = self._string_list(profile.get(key))
        profile["macro_sensitivities"] = self._normalize_sensitivities(profile.get("macro_sensitivities"), fallback_terms=profile.get("macro_sensitivity"))
        profile["event_sensitivities"] = self._normalize_event_sensitivities(profile.get("event_sensitivities"), fallback_terms=profile.get("event_vocab"))
        return profile

    def assess_context(
        self,
        ticker: str,
        context: dict[str, Any],
        *,
        direction: RecommendationDirection,
        taxonomy_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = self.get_profile(ticker, taxonomy_profile=taxonomy_profile)
        warnings: list[str] = []
        if ticker.strip().upper() not in self._profiles:
            source = str(profile.get("source") or "taxonomy_derived")
            warnings.append(f"explicit exposure ontology profile missing; using {source} profile")
        coverage_status = self._coverage_status(profile)
        coverage_reasons = self._coverage_reasons(profile)
        if coverage_status != "usable":
            warnings.append(f"exposure ontology coverage is {coverage_status}: {', '.join(coverage_reasons)}")

        evidence = self._context_evidence(context)
        matches = self._matched_exposures(profile, evidence)
        directional_score = sum(float(item.get("signed_score", 0.0) or 0.0) for item in matches)
        if abs(directional_score) < 0.12:
            support = "unknown" if not matches else "mixed"
        elif directional_score > 0:
            support = "supports_long"
        else:
            support = "against_long"

        long_adjustment = self._bounded_adjustment(directional_score, positive_cap=3.0, negative_cap=6.0)
        adjustment = long_adjustment if direction == RecommendationDirection.LONG else -long_adjustment
        return {
            "coverage_status": coverage_status,
            "profile_version": profile.get("version"),
            "source": profile.get("source"),
            "confidence_score": round(float(profile.get("confidence_score", 0.0) or 0.0), 3),
            "matched_exposure_count": len(matches),
            "coverage_reasons": coverage_reasons,
            "directional_support": support,
            "alignment_adjustment_percent": round(adjustment, 1),
            "transmission_paths": [str(item.get("transmission_path")) for item in matches[:5]],
            "matched_exposures": matches[:8],
            "warnings": warnings,
        }

    @staticmethod
    def _template_profile(taxonomy_profile: dict[str, Any]) -> dict[str, Any]:
        sector = str(taxonomy_profile.get("sector") or "").lower()
        industry = str(taxonomy_profile.get("industry") or "").lower()
        if not sector and not industry:
            return {}
        keywords = TickerExposureOntologyService._string_list(taxonomy_profile.get("industry_keywords"))[:6]
        profile: dict[str, Any] = {
            "source": "template_derived",
            "version": "template-2026-06-v1",
            "confidence_score": 0.58,
            "revenue_drivers": keywords[:3] or [str(taxonomy_profile.get("industry") or taxonomy_profile.get("sector") or "industry demand")],
            "cost_drivers": ["input costs", "labor costs", "financing costs"],
            "event_sensitivities": [],
            "macro_sensitivities": [],
        }
        if "energy" in sector or any(term in industry for term in ("oil", "gas", "energy")):
            profile["macro_sensitivities"] = [
                {"factor": "oil_prices", "aliases": ["oil prices", "crude", "energy prices"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "higher commodity prices often support upstream energy revenues"},
                {"factor": "global_growth", "aliases": ["global growth", "industrial demand", "energy demand"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "stronger growth supports energy demand"},
            ]
        elif "financial" in sector or "bank" in industry:
            profile["macro_sensitivities"] = [
                {"factor": "yield_curve", "aliases": ["yield curve", "net interest margin", "NIM", "steepening"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "a steeper curve can support lending margins"},
                {"factor": "credit_stress", "aliases": ["credit stress", "charge-offs", "delinquencies", "loan losses"], "direction_if_factor_rises": "negative", "strength": "high", "rationale": "credit deterioration pressures financial earnings"},
            ]
        elif "industrial" in sector or any(term in industry for term in ("machinery", "aerospace", "transport", "construction")):
            profile["macro_sensitivities"] = [
                {"factor": "industrial_production", "aliases": ["industrial production", "manufacturing demand", "capex", "infrastructure spending"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "industrial demand supports order books and utilization"},
                {"factor": "interest_rates", "aliases": ["rates", "financing costs", "treasury yields"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "higher financing costs can slow capital goods demand"},
            ]
        elif "material" in sector or any(term in industry for term in ("building", "copper", "steel", "chemical")):
            profile["macro_sensitivities"] = [
                {"factor": "construction_demand", "aliases": ["construction demand", "infrastructure", "housing starts", "building materials"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "construction activity supports materials volumes and pricing"},
                {"factor": "input_cost_inflation", "aliases": ["input costs", "energy costs", "feedstock costs"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "input inflation can pressure margins"},
            ]
        elif "technology" in sector or "semiconductor" in industry:
            profile["macro_sensitivities"] = [
                {"factor": "technology_capex", "aliases": ["technology capex", "AI capex", "cloud spending", "semiconductor demand"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "technology capex supports demand"},
                {"factor": "interest_rates", "aliases": ["rates", "treasury yields", "discount rate"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "higher rates can pressure growth multiples"},
            ]
        elif "consumer discretionary" in sector or any(term in industry for term in ("restaurant", "travel", "lodging", "casino", "retail", "apparel", "automobile", "auto", "leisure")):
            profile["macro_sensitivities"] = [
                {"factor": "consumer_discretionary_spending", "aliases": ["consumer spending", "discretionary demand", "retail sales", "travel demand", "same-store sales"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "consumer discretionary industries generally benefit from stronger household spending and demand"},
                {"factor": "input_cost_inflation", "aliases": ["wage inflation", "food costs", "fuel costs", "input costs", "markdown pressure"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "labor, merchandise, fuel, or food inflation can pressure margins"},
            ]
            profile["event_sensitivities"] = [
                {"event": "demand_reacceleration", "aliases": ["traffic improves", "bookings improve", "retail sales improve", "same-store sales beat"], "direction_for_long": "positive", "strength": "medium", "rationale": "stronger demand supports revenue and operating leverage"},
                {"event": "consumer_slowdown", "aliases": ["consumer slowdown", "weak bookings", "weak traffic", "markdowns"], "direction_for_long": "negative", "strength": "medium", "rationale": "weaker discretionary demand pressures sales and margins"},
            ]
        elif "consumer staples" in sector or any(term in industry for term in ("grocery", "beverage", "food", "confection", "household", "tobacco")):
            profile["macro_sensitivities"] = [
                {"factor": "staples_volume_pricing", "aliases": ["pricing", "volume", "grocery demand", "staples demand"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "staples companies benefit when pricing and volumes are resilient"},
                {"factor": "commodity_input_costs", "aliases": ["commodity costs", "input costs", "packaging costs", "food inflation"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "input-cost inflation can pressure gross margins when not offset by pricing"},
            ]
        elif "health care" in sector or any(term in industry for term in ("pharma", "biotech", "medical", "healthcare", "diagnostic")):
            profile["macro_sensitivities"] = [
                {"factor": "healthcare_demand", "aliases": ["healthcare demand", "procedure volumes", "prescription demand", "utilization"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "higher utilization and product demand generally support healthcare revenue"},
                {"factor": "pricing_regulatory_pressure", "aliases": ["drug pricing", "reimbursement pressure", "regulatory pressure", "pricing pressure"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "pricing, reimbursement, and regulatory pressure can reduce expected profitability"},
            ]
            profile["event_sensitivities"] = [
                {"event": "clinical_regulatory_progress", "aliases": ["approval", "trial data", "pipeline progress", "FDA"], "direction_for_long": "positive", "strength": "medium", "rationale": "positive clinical or regulatory events can improve expected cash flows"},
                {"event": "clinical_regulatory_setback", "aliases": ["trial failure", "complete response letter", "safety concern", "regulatory setback"], "direction_for_long": "negative", "strength": "medium", "rationale": "setbacks can reduce expected product or pipeline value"},
            ]
        elif "communication" in sector or any(term in industry for term in ("telecom", "media", "entertainment", "advertising", "internet content")):
            profile["macro_sensitivities"] = [
                {"factor": "subscriber_advertising_demand", "aliases": ["subscriber growth", "advertising demand", "broadband adds", "wireless adds"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "subscriber, advertising, and engagement growth generally support communication-services revenue"},
                {"factor": "capex_competition_pressure", "aliases": ["capex", "spectrum costs", "competition", "churn"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "capital intensity and competition can pressure free cash flow and margins"},
            ]
        elif "real estate" in sector or "reit" in industry:
            profile["macro_sensitivities"] = [
                {"factor": "interest_rates", "aliases": ["rates", "treasury yields", "financing costs", "cap rates"], "direction_if_factor_rises": "negative", "strength": "high", "rationale": "REIT and real-estate valuations are generally sensitive to financing costs and capitalization rates"},
                {"factor": "occupancy_rent_growth", "aliases": ["occupancy", "rent growth", "leasing demand", "same-store NOI"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "occupancy and rent growth support real-estate cash flows"},
            ]
        elif "utilities" in sector or "utility" in industry:
            profile["macro_sensitivities"] = [
                {"factor": "interest_rates", "aliases": ["rates", "treasury yields", "financing costs"], "direction_if_factor_rises": "negative", "strength": "high", "rationale": "utilities are capital-intensive and often trade as rate-sensitive income equities"},
                {"factor": "regulated_returns_load_growth", "aliases": ["regulated returns", "rate base", "load growth", "electricity demand"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "regulated returns and load growth can support utility earnings"},
            ]
        elif "index" in sector or "etf" in sector or "etf" in industry:
            profile["macro_sensitivities"] = [
                {"factor": "underlying_market_trend", "aliases": ["market trend", "risk appetite", "index performance", "ETF flows"], "direction_if_factor_rises": "positive", "strength": "medium", "rationale": "index and ETF instruments generally follow their underlying market or factor exposure"},
                {"factor": "market_risk_aversion", "aliases": ["risk aversion", "volatility", "market selloff"], "direction_if_factor_rises": "negative", "strength": "medium", "rationale": "broad risk aversion can pressure risk-asset indexes and ETFs"},
            ]
        else:
            return {}
        return profile

    @staticmethod
    def _coverage_status(profile: dict[str, Any]) -> str:
        reasons = TickerExposureOntologyService._coverage_reasons(profile)
        if not reasons:
            return "usable"
        has_directional = bool(profile.get("macro_sensitivities") or profile.get("event_sensitivities"))
        driver_count = len(profile.get("revenue_drivers", [])) + len(profile.get("cost_drivers", []))
        if has_directional or driver_count > 0:
            return "degraded"
        return "missing"

    @staticmethod
    def _coverage_reasons(profile: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        has_directional = bool(profile.get("macro_sensitivities") or profile.get("event_sensitivities"))
        driver_count = len(profile.get("revenue_drivers", [])) + len(profile.get("cost_drivers", []))
        confidence = float(profile.get("confidence_score", 0.0) or 0.0)
        if not has_directional:
            reasons.append("missing directional macro/event sensitivities")
        if driver_count < 2:
            reasons.append("fewer than two business drivers")
        if confidence < 0.55:
            reasons.append(f"confidence score {confidence:.2f} below usable threshold 0.55")
        source = str(profile.get("source") or "").strip()
        if source == "taxonomy_generated":
            reasons.append("taxonomy-generated sparse profile has no sector template directional mapping")
        return reasons

    def _matched_exposures(self, profile: dict[str, Any], evidence: dict[str, str]) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for sensitivity in profile.get("macro_sensitivities", []):
            self._maybe_add_match(matches, sensitivity, evidence, kind="macro_sensitivity")
        for sensitivity in profile.get("event_sensitivities", []):
            self._maybe_add_match(matches, sensitivity, evidence, kind="event_sensitivity")
        for driver_kind in ("revenue_drivers", "cost_drivers", "customer_segments"):
            for driver in profile.get(driver_kind, [])[:8]:
                text = str(driver).strip()
                if text and text.lower() in evidence["all_text"]:
                    direction = "positive" if driver_kind != "cost_drivers" else "negative"
                    score = 0.22 if driver_kind != "customer_segments" else 0.16
                    matches.append(
                        {
                            "kind": driver_kind,
                            "factor": text,
                            "direction_for_long": direction,
                            "strength": "low",
                            "match_terms": [text],
                            "signed_score": round(score * _DIRECTION_SIGN[direction], 3),
                            "transmission_path": f"{text} -> {driver_kind} -> {direction}_long_context",
                            "rationale": "driver text matched active context evidence",
                        }
                    )
        matches.sort(key=lambda item: abs(float(item.get("signed_score", 0.0) or 0.0)), reverse=True)
        return matches

    def _maybe_add_match(self, matches: list[dict[str, Any]], sensitivity: dict[str, Any], evidence: dict[str, str], *, kind: str) -> None:
        terms = self._string_list(sensitivity.get("aliases")) + [str(sensitivity.get("factor") or sensitivity.get("event") or "")]
        hits = [term for term in terms if term and term.lower() in evidence["all_text"]]
        if not hits:
            return
        direction = str(sensitivity.get("direction_for_long") or sensitivity.get("direction_if_factor_rises") or "mixed").strip().lower()
        if direction not in _DIRECTION_SIGN:
            direction = "mixed"
        strength = str(sensitivity.get("strength") or "medium").strip().lower()
        strength_score = _STRENGTH_SCORE.get(strength, 0.65)
        confidence = self._number(sensitivity.get("confidence_score"), default=strength_score)
        signed_score = _DIRECTION_SIGN[direction] * strength_score * confidence
        factor = str(sensitivity.get("factor") or sensitivity.get("event") or hits[0]).strip()
        matches.append(
            {
                "kind": kind,
                "factor": factor,
                "direction_for_long": direction,
                "strength": strength,
                "match_terms": hits[:5],
                "signed_score": round(signed_score, 3),
                "transmission_path": f"{factor} -> {kind} -> {direction}_long_context",
                "rationale": str(sensitivity.get("rationale") or "ontology sensitivity matched active context evidence"),
            }
        )

    @staticmethod
    def _bounded_adjustment(score: float, *, positive_cap: float, negative_cap: float) -> float:
        if score > 0:
            return min(positive_cap, score * 4.0)
        if score < 0:
            return max(-negative_cap, score * 5.0)
        return 0.0

    @staticmethod
    def _context_evidence(context: dict[str, Any]) -> dict[str, str]:
        chunks: list[str] = []
        for key in (
            "macro_context_summary",
            "industry_context_summary",
            "market_intelligence_summary",
            "summary_text",
        ):
            value = context.get(key)
            if value:
                chunks.append(str(value))
        for raw_key in ("macro_context_events", "macro_context_active_themes", "industry_context_events", "industry_context_active_drivers", "news_items"):
            raw = context.get(raw_key)
            if isinstance(raw, list):
                for item in raw[:12]:
                    if isinstance(item, dict):
                        chunks.extend(str(item.get(field, "")) for field in ("key", "label", "title", "summary", "description"))
                        for list_field in ("transmission_channels", "regime_tags"):
                            values = item.get(list_field)
                            if isinstance(values, list):
                                chunks.extend(str(value) for value in values)
                    else:
                        chunks.append(str(item))
        return {"all_text": " ".join(chunk for chunk in chunks if chunk).lower()}

    @classmethod
    def _normalize_sensitivities(cls, raw: object, *, fallback_terms: object = None) -> list[dict[str, Any]]:
        if isinstance(raw, list) and raw and all(isinstance(item, dict) for item in raw):
            return [dict(item) for item in raw if isinstance(item, dict)]
        return [
            {"factor": term, "aliases": [term], "direction_if_factor_rises": "mixed", "strength": "low"}
            for term in cls._string_list(fallback_terms)
        ]

    @classmethod
    def _normalize_event_sensitivities(cls, raw: object, *, fallback_terms: object = None) -> list[dict[str, Any]]:
        if isinstance(raw, list) and raw and all(isinstance(item, dict) for item in raw):
            return [dict(item) for item in raw if isinstance(item, dict)]
        return [
            {"event": term, "aliases": [term], "direction_for_long": "mixed", "strength": "low"}
            for term in cls._string_list(fallback_terms)[:12]
        ]

    @staticmethod
    def _string_list(raw: object) -> list[str]:
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return []

    @staticmethod
    def _number(raw: object, *, default: float) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default
