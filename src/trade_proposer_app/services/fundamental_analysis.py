from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import yfinance as yf

from trade_proposer_app.repositories.fundamental_analysis_snapshots import (
    FundamentalAnalysisSnapshotRepository,
)


@dataclass(frozen=True)
class FundamentalAnalysisSnapshot:
    ticker: str
    as_of: datetime
    source_set: list[str]
    coverage_status: str
    freshness_status: str
    payload: dict[str, Any]
    warnings: list[str]
    missing_inputs: list[str]
    job_id: int | None = None
    run_id: int | None = None


class YFinanceFundamentalProvider:
    source_name = "yfinance"

    def fetch(self, ticker: str, as_of: datetime | None = None) -> dict[str, Any]:
        obj = yf.Ticker(ticker)
        info = obj.info if isinstance(obj.info, dict) else {}
        return {
            "info": info,
            "calendar": self._safe_attr(obj, "calendar"),
            "recommendations": self._safe_attr(obj, "recommendations"),
        }

    @staticmethod
    def _safe_attr(obj: Any, name: str) -> Any:
        try:
            raw = getattr(obj, name)
        except Exception:
            return []
        try:
            if hasattr(raw, "reset_index"):
                return raw.reset_index().head(5).to_dict(orient="records")
        except Exception:
            return []
        return raw if isinstance(raw, list) else []


class FundamentalAnalysisService:
    MONTHLY_STALE_DAYS = 30

    def __init__(self, *, provider: Any | None = None, repository: FundamentalAnalysisSnapshotRepository | None = None) -> None:
        self.provider = provider or YFinanceFundamentalProvider()
        self.repository = repository

    def analyze(self, ticker: str, *, as_of: datetime | None = None) -> FundamentalAnalysisSnapshot:
        normalized = str(ticker or "").strip().upper()
        effective_as_of = self._dt(as_of) or datetime.now(timezone.utc)
        warnings: list[str] = []
        missing_inputs: list[str] = []
        if not normalized:
            return FundamentalAnalysisSnapshot("", effective_as_of, [], "blocked", "unknown", self._empty_payload(), ["ticker is required"], ["ticker"])
        try:
            raw = self.provider.fetch(normalized, as_of=effective_as_of)
        except Exception as exc:
            payload = self._empty_payload()
            payload["provider_diagnostics"] = {"errors": [str(exc)]}
            return FundamentalAnalysisSnapshot(normalized, effective_as_of, [self._source_name()], "blocked", "unknown", payload, ["fundamental provider unavailable"], ["provider_payload"])
        info = raw.get("info") if isinstance(raw, dict) and isinstance(raw.get("info"), dict) else {}
        def pick(key: str) -> Any:
            value = info.get(key)
            if value is None:
                missing_inputs.append(key)
            return value
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        target = info.get("targetMeanPrice")
        upside = self._percent_delta(target, price)
        payload = {
            "business_profile": {
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "currency": info.get("currency"),
            },
            "valuation": {
                "market_cap": pick("marketCap"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "price_to_book": info.get("priceToBook"),
            },
            "profitability_quality": {
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "net_margin": info.get("profitMargins"),
                "return_on_equity": info.get("returnOnEquity"),
                "return_on_assets": info.get("returnOnAssets"),
            },
            "growth": {
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
            },
            "balance_sheet_risk": {
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "total_cash": info.get("totalCash"),
                "total_debt": info.get("totalDebt"),
            },
            "cash_flow": {
                "operating_cashflow": info.get("operatingCashflow"),
                "free_cashflow": info.get("freeCashflow"),
            },
            "analyst_context": {
                "recommendation_mean": info.get("recommendationMean"),
                "recommendation_key": info.get("recommendationKey"),
                "target_mean_price": target,
                "target_price_upside_percent": upside,
                "recent_recommendations": raw.get("recommendations", []) if isinstance(raw, dict) else [],
            },
            "event_calendar": {
                "next_earnings_at": self._event_iso(info.get("earningsTimestamp") or info.get("earningsTimestampStart") or info.get("nextEarningsDate")),
                "ex_dividend_at": self._event_iso(info.get("exDividendDate")),
                "raw_calendar": raw.get("calendar", []) if isinstance(raw, dict) else [],
            },
            "provider_diagnostics": {"source_name": self._source_name(), "missing_input_count": 0, "errors": []},
            "raw_payload_refs": {"info_keys": sorted(info.keys())[:80]},
            "confidence_contribution": {"positive_boost": 0.0},
        }
        payload["feature_buckets"] = self._feature_buckets(payload, as_of=effective_as_of)
        payload["valuation_context"] = self._valuation_context(payload, as_of=effective_as_of)
        missing_inputs = sorted({item for item in missing_inputs if item})
        payload["provider_diagnostics"]["missing_input_count"] = len(missing_inputs)
        usable_core_fields = self._usable_core_field_count(payload)
        if usable_core_fields < 3:
            warnings.append("fundamental provider returned sparse data")
        elif missing_inputs:
            warnings.append("fundamental provider returned partial data")
        coverage = self._coverage_status(info, missing_inputs=missing_inputs, usable_core_fields=usable_core_fields)
        payload["valuation_context"]["coverage_status"] = coverage
        return FundamentalAnalysisSnapshot(normalized, effective_as_of, [self._source_name()], coverage, "fresh", payload, warnings, missing_inputs)

    def refresh_ticker(self, ticker: str, *, job_id: int | None = None, run_id: int | None = None, as_of: datetime | None = None) -> dict[str, Any]:
        if self.repository is None:
            raise ValueError("repository is required to refresh fundamental snapshots")
        snapshot = self.analyze(ticker, as_of=as_of)
        return self.repository.create_snapshot(
            ticker=snapshot.ticker,
            as_of=snapshot.as_of,
            source_set=snapshot.source_set,
            coverage_status=snapshot.coverage_status,
            freshness_status=snapshot.freshness_status,
            payload=snapshot.payload,
            warnings=snapshot.warnings,
            missing_inputs=snapshot.missing_inputs,
            job_id=job_id,
            run_id=run_id,
        )

    def snapshot_due_reason(self, latest_snapshot: dict[str, Any] | None, as_of: datetime) -> str | None:
        if latest_snapshot is None:
            return "missing_snapshot"
        latest_as_of = self._dt(latest_snapshot.get("as_of"))
        if latest_as_of is None or latest_as_of <= self._dt(as_of) - timedelta(days=self.MONTHLY_STALE_DAYS):
            return "monthly_stale"
        payload = latest_snapshot.get("payload") if isinstance(latest_snapshot.get("payload"), dict) else {}
        if self.event_regime(payload, as_of=as_of) in {"pre_event", "event_week", "post_event"}:
            return "event_window"
        return None

    def important_event_window(self, snapshot: dict[str, Any], *, as_of: datetime) -> bool:
        payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else snapshot
        return self.event_regime(payload, as_of=as_of) in {"pre_event", "event_week", "post_event"}

    def event_regime(self, payload: dict[str, Any], *, as_of: datetime) -> str:
        events = payload.get("event_calendar") if isinstance(payload.get("event_calendar"), dict) else {}
        dates = [events.get("next_earnings_at"), events.get("shareholder_meeting_at"), events.get("investor_day_at"), events.get("ex_dividend_at")]
        parsed = [self._dt(value) for value in dates if self._dt(value) is not None]
        if not parsed:
            return "none_known"
        ref = self._dt(as_of) or datetime.now(timezone.utc)
        nearest = min(parsed, key=lambda value: abs((value - ref).total_seconds()))
        days = (nearest.date() - ref.date()).days
        if -2 <= days <= 3:
            return "event_week"
        if 4 <= days <= 14:
            return "pre_event"
        if -7 <= days <= -3:
            return "post_event"
        if days < -7:
            return "stale_event"
        return "none_known"

    def _feature_buckets(self, payload: dict[str, Any], *, as_of: datetime) -> dict[str, str]:
        val = payload.get("valuation", {})
        prof = payload.get("profitability_quality", {})
        growth = payload.get("growth", {})
        risk = payload.get("balance_sheet_risk", {})
        analyst = payload.get("analyst_context", {})
        return {
            "valuation": self._valuation_bucket(val.get("forward_pe") or val.get("trailing_pe")),
            "profitability_quality": self._quality_bucket(prof.get("operating_margin") or prof.get("net_margin")),
            "growth": self._growth_bucket(growth.get("revenue_growth") or growth.get("earnings_growth")),
            "balance_sheet_risk": self._balance_risk_bucket(risk.get("debt_to_equity")),
            "analyst_upside": self._analyst_upside_bucket(analyst.get("target_price_upside_percent")),
            "event_regime": self.event_regime(payload, as_of=as_of),
        }

    def _valuation_context(self, payload: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
        buckets = payload.get("feature_buckets") if isinstance(payload.get("feature_buckets"), dict) else {}
        valuation = str(buckets.get("valuation") or "unknown")
        quality = str(buckets.get("profitability_quality") or "unknown")
        growth = str(buckets.get("growth") or "unknown")
        risk = str(buckets.get("balance_sheet_risk") or "unknown")
        upside = str(buckets.get("analyst_upside") or "unknown")
        event_regime = str(buckets.get("event_regime") or self.event_regime(payload, as_of=as_of))
        known_supports = sum(
            1 for value in (quality, growth, risk, upside) if value not in {"", "unknown"}
        )
        has_valuation = valuation != "unknown"
        if not has_valuation or known_supports < 2:
            signal = "unknown" if not has_valuation else "unclear"
        elif valuation == "cheap" and quality == "strong" and growth in {"moderate", "high"} and risk != "high":
            signal = "undervalued"
        elif valuation == "cheap" and upside in {"positive", "strong_positive"} and risk != "high":
            signal = "undervalued"
        elif valuation == "extreme_expensive" and (growth in {"negative", "low"} or quality == "weak"):
            signal = "extreme_overvalued"
        elif valuation in {"expensive", "extreme_expensive"} and (growth in {"negative", "low"} or quality == "weak" or upside in {"negative", "strong_negative"}):
            signal = "overvalued" if valuation == "expensive" else "extreme_overvalued"
        elif valuation == "medium" and quality == "strong" and growth in {"moderate", "high"}:
            signal = "fairly_valued"
        elif valuation == "medium":
            signal = "fairly_valued"
        else:
            signal = "unclear"
        score_map = {
            "undervalued": 0.7,
            "fairly_valued": 0.0,
            "unclear": 0.0,
            "unknown": 0.0,
            "overvalued": -0.55,
            "extreme_overvalued": -0.85,
        }
        long_support, short_support = self._directional_support(signal)
        reasons = self._valuation_reasons(
            valuation=valuation,
            quality=quality,
            growth=growth,
            risk=risk,
            upside=upside,
            signal=signal,
        )
        warnings = []
        if event_regime in {"pre_event", "event_week"}:
            warnings.append("corporate event is near the intended holding window")
        if signal == "unknown":
            warnings.append("insufficient fundamental valuation data")
        return {
            "schema_version": "fundamental-valuation-v1",
            "coverage_status": "unknown",
            "mispricing_signal": signal,
            "mispricing_score": score_map.get(signal, 0.0),
            "valuation_bucket": valuation,
            "valuation_relative_to_quality": self._relative_label(valuation, quality),
            "valuation_relative_to_growth": self._relative_label(valuation, growth),
            "analyst_upside_bucket": upside,
            "quality_bucket": quality,
            "growth_bucket": growth,
            "balance_sheet_risk_bucket": risk,
            "event_regime": event_regime,
            "directional_support": {"long": long_support, "short": short_support},
            "confidence_contribution": {
                "positive_boost": 0.0,
                "risk_penalty": 0.0,
                "cap_multiplier": 1.0,
            },
            "reasons": reasons,
            "warnings": warnings,
        }

    @staticmethod
    def _valuation_bucket(value: Any) -> str:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "unknown"
        if v < 15:
            return "cheap"
        if v <= 35:
            return "medium"
        if v <= 60:
            return "expensive"
        return "extreme_expensive"

    @staticmethod
    def _quality_bucket(value: Any) -> str:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "unknown"
        return "weak" if v < 0.08 else "mixed" if v < 0.22 else "strong"

    @staticmethod
    def _growth_bucket(value: Any) -> str:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "unknown"
        return "negative" if v < -0.02 else "low" if v < 0.03 else "moderate" if v < 0.15 else "high"

    @staticmethod
    def _balance_risk_bucket(value: Any) -> str:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "unknown"
        return "low" if v < 80 else "medium" if v < 200 else "high"

    @staticmethod
    def _analyst_upside_bucket(value: Any) -> str:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "unknown"
        if v >= 25:
            return "strong_positive"
        if v >= 5:
            return "positive"
        if v <= -20:
            return "strong_negative"
        if v <= -5:
            return "negative"
        return "neutral"

    @staticmethod
    def _directional_support(signal: str) -> tuple[str, str]:
        if signal == "undervalued":
            return "supportive", "contradictory"
        if signal == "fairly_valued":
            return "neutral", "neutral"
        if signal == "overvalued":
            return "caution", "supportive"
        if signal == "extreme_overvalued":
            return "contradictory", "supportive"
        if signal == "unclear":
            return "neutral", "neutral"
        return "unknown", "unknown"

    @staticmethod
    def _relative_label(valuation: str, comparator: str) -> str:
        if valuation == "unknown" or comparator == "unknown":
            return "unknown"
        if valuation == "cheap" and comparator in {"strong", "high", "moderate"}:
            return "attractive"
        if valuation in {"expensive", "extreme_expensive"} and comparator in {"weak", "negative", "low"}:
            return "unattractive"
        return "mixed"

    @staticmethod
    def _valuation_reasons(
        *,
        valuation: str,
        quality: str,
        growth: str,
        risk: str,
        upside: str,
        signal: str,
    ) -> list[str]:
        reasons = [f"valuation bucket is {valuation}"] if valuation != "unknown" else []
        if quality != "unknown":
            reasons.append(f"profitability quality is {quality}")
        if growth != "unknown":
            reasons.append(f"growth is {growth}")
        if risk != "unknown":
            reasons.append(f"balance-sheet risk is {risk}")
        if upside != "unknown":
            reasons.append(f"analyst upside is {upside}")
        if signal == "unknown" and not reasons:
            reasons.append("insufficient usable valuation inputs")
        return reasons[:6]

    @staticmethod
    def _usable_core_field_count(payload: dict[str, Any]) -> int:
        sections = (
            payload.get("valuation", {}),
            payload.get("profitability_quality", {}),
            payload.get("growth", {}),
            payload.get("balance_sheet_risk", {}),
            payload.get("cash_flow", {}),
            payload.get("analyst_context", {}),
        )
        count = 0
        for section in sections:
            if not isinstance(section, dict):
                continue
            count += sum(1 for value in section.values() if value not in (None, "", [], {}))
        return count

    @staticmethod
    def _coverage_status(
        info: dict[str, Any], *, missing_inputs: list[str], usable_core_fields: int
    ) -> str:
        if not info:
            return "blocked"
        if usable_core_fields < 3:
            return "degraded"
        if usable_core_fields < 8 or len(missing_inputs) >= 8:
            return "degraded"
        return "ok"

    @staticmethod
    def _percent_delta(target: Any, price: Any) -> float | None:
        try:
            t = float(target)
            p = float(price)
        except (TypeError, ValueError):
            return None
        return round(((t - p) / p) * 100.0, 2) if p else None

    @staticmethod
    def _event_iso(value: Any) -> str | None:
        parsed = FundamentalAnalysisService._dt(value)
        return parsed.isoformat() if parsed is not None else None

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    def _source_name(self) -> str:
        return str(getattr(self.provider, "source_name", "provider"))

    @staticmethod
    def _empty_payload() -> dict[str, Any]:
        payload = {
            key: {}
            for key in (
                "business_profile",
                "valuation",
                "profitability_quality",
                "growth",
                "balance_sheet_risk",
                "cash_flow",
                "analyst_context",
                "event_calendar",
                "feature_buckets",
                "provider_diagnostics",
                "raw_payload_refs",
            )
        }
        payload["valuation_context"] = {
            "schema_version": "fundamental-valuation-v1",
            "coverage_status": "blocked",
            "mispricing_signal": "unknown",
            "mispricing_score": 0.0,
            "valuation_bucket": "unknown",
            "directional_support": {"long": "unknown", "short": "unknown"},
            "confidence_contribution": {
                "positive_boost": 0.0,
                "risk_penalty": 0.0,
                "cap_multiplier": 1.0,
            },
            "reasons": ["insufficient usable valuation inputs"],
            "warnings": ["fundamental provider unavailable"],
        }
        return payload
