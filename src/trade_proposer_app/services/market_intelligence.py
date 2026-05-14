from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import math

import pandas as pd
import yfinance as yf

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import ProviderCredential


@dataclass(frozen=True)
class MarketIntelligenceServiceConfig:
    source_name: str = "yfinance"
    replay_days_cutoff: int = 1
    enabled: bool = False


class MarketIntelligenceService:
    def __init__(self, *, provider_credentials: dict[str, ProviderCredential] | None = None, config: MarketIntelligenceServiceConfig | None = None) -> None:
        self.provider_credentials = provider_credentials or {}
        self.config = config or MarketIntelligenceServiceConfig()

    def analyze(self, ticker: str, *, as_of: datetime | None = None, horizon: StrategyHorizon | None = None) -> dict[str, Any]:
        normalized_ticker = ticker.strip().upper()
        snapshot = self._neutral_snapshot(normalized_ticker, as_of=as_of)
        if not normalized_ticker:
            snapshot["coverage_status"] = "blocked"
            snapshot["warnings"].append("ticker is required for market intelligence")
            return snapshot
        if not self.config.enabled:
            snapshot["coverage_status"] = "disabled"
            snapshot["freshness_status"] = "disabled"
            snapshot["summary"] = "Market intelligence disabled."
            return snapshot
        if not normalized_ticker:
            snapshot["coverage_status"] = "blocked"
            snapshot["warnings"].append("ticker is required for market intelligence")
            return snapshot
        if as_of is not None and as_of.date() < self._live_cutoff_date():
            snapshot["coverage_status"] = "replay_unavailable"
            snapshot["freshness_status"] = "stale"
            snapshot["warnings"].append("market intelligence replay unavailable without stored historical vendor snapshots")
            return snapshot

        try:
            ticker_obj = yf.Ticker(normalized_ticker)
        except Exception as exc:  # noqa: BLE001
            snapshot["coverage_status"] = "blocked"
            snapshot["provider_diagnostics"]["errors"].append(f"yfinance ticker unavailable: {exc}")
            snapshot["warnings"].append("market intelligence provider unavailable")
            return snapshot

        info = self._safe_info(ticker_obj)
        earnings = self._event_intelligence(ticker_obj, info, as_of=as_of)
        options = self._options_intelligence(ticker_obj, info, as_of=as_of, horizon=horizon)
        analyst = self._analyst_intelligence(ticker_obj, info, as_of=as_of)

        warnings = list(dict.fromkeys([*earnings["warnings"], *options["warnings"], *analyst["warnings"]]))
        conflict_flags = list(dict.fromkeys([*earnings["conflict_flags"], *options["conflict_flags"], *analyst["conflict_flags"]]))
        combined = self._combine_scores(earnings, options, analyst)
        summary = self._summary_text(earnings, options, analyst)
        source_set = [self.config.source_name]
        if self.provider_credentials:
            source_set.extend(sorted({str(key).strip() for key in self.provider_credentials if str(key).strip()}))

        snapshot.update(
            {
                "source_set": list(dict.fromkeys(source_set)),
                "coverage_status": "ok" if combined["combined"] >= 35.0 else ("degraded" if warnings else "ok"),
                "freshness_status": self._freshness_status(earnings, options, analyst),
                "event_intelligence": earnings,
                "options_intelligence": options,
                "analyst_intelligence": analyst,
                "confidence_contribution": combined,
                "conflict_flags": conflict_flags,
                "warnings": warnings,
                "provider_diagnostics": {
                    "source_name": self.config.source_name,
                    "provider_keys": list(self.provider_credentials.keys()),
                    "info_available": bool(info),
                    "errors": [],
                },
                "raw_payload_refs": {
                    "info": self._compact_info(info),
                    "calendar": self._safe_table(ticker_obj, "calendar"),
                    "earnings_dates": self._safe_table(ticker_obj, "earnings_dates"),
                    "recommendations": self._safe_table(ticker_obj, "recommendations"),
                },
            }
        )
        if snapshot["coverage_status"] == "ok" and warnings:
            snapshot["coverage_status"] = "degraded"
        if not any([earnings["available"], options["available"], analyst["available"]]):
            snapshot["coverage_status"] = "degraded"
            snapshot["warnings"].append("no usable market intelligence sources returned data")
        snapshot["summary"] = summary
        return snapshot

    def summarize(self, snapshot: dict[str, Any]) -> str:
        return str(snapshot.get("summary", ""))

    def _live_cutoff_date(self) -> date:
        return datetime.now(timezone.utc).date() - timedelta(days=self.config.replay_days_cutoff)

    @staticmethod
    def _neutral_snapshot(ticker: str, *, as_of: datetime | None) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "as_of": as_of.isoformat() if as_of is not None else datetime.now(timezone.utc).isoformat(),
            "source_set": [],
            "coverage_status": "degraded",
            "freshness_status": "unknown",
            "event_intelligence": {
                "available": False,
                "source": None,
                "event_class": None,
                "event_label": None,
                "event_at": None,
                "imminence_days": None,
                "window_label": "unknown",
                "bias": "neutral",
                "score": 0.0,
                "warnings": ["event coverage unavailable"],
                "conflict_flags": [],
            },
            "options_intelligence": {
                "available": False,
                "source": None,
                "expiry": None,
                "days_to_expiry": None,
                "put_call_ratio": None,
                "call_open_interest": None,
                "put_open_interest": None,
                "call_volume": None,
                "put_volume": None,
                "implied_volatility": None,
                "pressure_bias": "neutral",
                "score": 0.0,
                "warnings": ["options coverage unavailable"],
                "conflict_flags": [],
            },
            "analyst_intelligence": {
                "available": False,
                "source": None,
                "recommendation_key": None,
                "recommendation_mean": None,
                "price_target_mean": None,
                "price_target_upside_percent": None,
                "recent_action": None,
                "bias": "neutral",
                "score": 0.0,
                "warnings": ["analyst coverage unavailable"],
                "conflict_flags": [],
            },
            "confidence_contribution": {"event": 0.0, "options": 0.0, "analyst": 0.0, "combined": 0.0},
            "conflict_flags": [],
            "warnings": [],
            "provider_diagnostics": {"source_name": "yfinance", "provider_keys": [], "info_available": False, "errors": []},
            "raw_payload_refs": {},
            "summary": "Market intelligence unavailable.",
        }

    @staticmethod
    def _safe_info(ticker_obj: Any) -> dict[str, Any]:
        try:
            info = ticker_obj.info
        except Exception:  # noqa: BLE001
            return {}
        return info if isinstance(info, dict) else {}

    @staticmethod
    def _safe_table(ticker_obj: Any, attribute: str) -> list[dict[str, Any]]:
        try:
            raw = getattr(ticker_obj, attribute)
        except Exception:  # noqa: BLE001
            return []
        if isinstance(raw, pd.DataFrame):
            return raw.reset_index().head(5).to_dict(orient="records")
        if isinstance(raw, list):
            return [item for item in raw[:5] if isinstance(item, dict)]
        return []

    def _event_intelligence(self, ticker_obj: Any, info: dict[str, Any], *, as_of: datetime | None) -> dict[str, Any]:
        warnings: list[str] = []
        event_at = self._coerce_datetime(
            info.get("earningsTimestamp")
            or info.get("earningsTimestampStart")
            or info.get("earningsTimestampEnd")
            or info.get("nextEarningsDate")
            or self._calendar_date(ticker_obj)
        )
        event_label = None
        event_class = None
        if event_at is not None:
            event_class = "earnings"
            event_label = "earnings"
        elif isinstance(info.get("exDividendDate"), (int, float)):
            event_at = self._coerce_datetime(info.get("exDividendDate"))
            event_class = "dividend"
            event_label = "dividend"
        if event_at is None:
            warnings.append("event calendar unavailable")
        imminence_days = self._days_between(as_of or datetime.now(timezone.utc), event_at) if event_at is not None else None
        score = self._event_score(imminence_days)
        bias = "neutral"
        if score >= 65.0:
            bias = "bullish"
        if event_at is not None and imminence_days is not None and imminence_days < -1:
            warnings.append("event appears stale relative to the requested as-of date")
        return {
            "available": event_at is not None,
            "source": self.config.source_name,
            "event_class": event_class,
            "event_label": event_label,
            "event_at": event_at.isoformat() if event_at is not None else None,
            "imminence_days": imminence_days,
            "window_label": self._event_window_label(imminence_days),
            "bias": bias,
            "score": round(score, 2),
            "warnings": warnings,
            "conflict_flags": [],
        }

    def _options_intelligence(self, ticker_obj: Any, info: dict[str, Any], *, as_of: datetime | None, horizon: StrategyHorizon | None) -> dict[str, Any]:
        warnings: list[str] = []
        expiries = self._safe_expiries(ticker_obj)
        selected_expiry = self._select_expiry(expiries, horizon=horizon, as_of=as_of)
        if selected_expiry is None:
            warnings.append("options chain unavailable")
            return {
                "available": False,
                "source": self.config.source_name,
                "expiry": None,
                "days_to_expiry": None,
                "put_call_ratio": None,
                "call_open_interest": None,
                "put_open_interest": None,
                "call_volume": None,
                "put_volume": None,
                "implied_volatility": None,
                "pressure_bias": "neutral",
                "score": 0.0,
                "warnings": warnings,
                "conflict_flags": [],
            }
        try:
            chain = ticker_obj.option_chain(selected_expiry)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"options chain fetch failed: {exc}")
            return {
                "available": False,
                "source": self.config.source_name,
                "expiry": selected_expiry,
                "days_to_expiry": self._days_to_expiry(selected_expiry),
                "put_call_ratio": None,
                "call_open_interest": None,
                "put_open_interest": None,
                "call_volume": None,
                "put_volume": None,
                "implied_volatility": None,
                "pressure_bias": "neutral",
                "score": 0.0,
                "warnings": warnings,
                "conflict_flags": [],
            }
        calls = chain.calls if isinstance(chain.calls, pd.DataFrame) else pd.DataFrame()
        puts = chain.puts if isinstance(chain.puts, pd.DataFrame) else pd.DataFrame()
        call_open_interest = self._numeric_sum(calls, "openInterest")
        put_open_interest = self._numeric_sum(puts, "openInterest")
        call_volume = self._numeric_sum(calls, "volume")
        put_volume = self._numeric_sum(puts, "volume")
        call_iv = self._numeric_mean(calls, "impliedVolatility")
        put_iv = self._numeric_mean(puts, "impliedVolatility")
        put_call_ratio = self._ratio(put_open_interest + put_volume, call_open_interest + call_volume)
        pressure_bias = "neutral"
        if put_call_ratio is not None:
            if put_call_ratio > 1.2:
                pressure_bias = "bearish"
            elif put_call_ratio < 0.8:
                pressure_bias = "bullish"
        days_to_expiry = self._days_to_expiry(selected_expiry)
        score = self._options_score(put_call_ratio, days_to_expiry, call_iv, put_iv)
        if call_open_interest == 0 and put_open_interest == 0:
            warnings.append("thin options coverage")
        if days_to_expiry is not None and days_to_expiry > 45:
            warnings.append("options expiry is far outside the default thesis window")
        return {
            "available": True,
            "source": self.config.source_name,
            "expiry": selected_expiry,
            "days_to_expiry": days_to_expiry,
            "put_call_ratio": round(put_call_ratio, 3) if put_call_ratio is not None else None,
            "call_open_interest": int(call_open_interest),
            "put_open_interest": int(put_open_interest),
            "call_volume": int(call_volume),
            "put_volume": int(put_volume),
            "implied_volatility": round(self._coalesce_iv(call_iv, put_iv), 4) if self._coalesce_iv(call_iv, put_iv) is not None else None,
            "pressure_bias": pressure_bias,
            "score": round(score, 2),
            "warnings": warnings,
            "conflict_flags": [],
        }

    def _analyst_intelligence(self, ticker_obj: Any, info: dict[str, Any], *, as_of: datetime | None) -> dict[str, Any]:
        warnings: list[str] = []
        recommendation_mean = self._safe_float(info.get("recommendationMean"))
        recommendation_key = info.get("recommendationKey")
        target_mean = self._safe_float(info.get("targetMeanPrice"))
        current_price = self._safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        upside_percent = None
        if target_mean is not None and current_price not in {None, 0.0}:
            upside_percent = ((target_mean - current_price) / current_price) * 100.0
        recent_action = None
        try:
            recs = ticker_obj.recommendations
        except Exception:  # noqa: BLE001
            recs = None
        latest_recs = recs.tail(5) if isinstance(recs, pd.DataFrame) and not recs.empty else pd.DataFrame()
        if isinstance(latest_recs, pd.DataFrame) and not latest_recs.empty:
            row = latest_recs.iloc[-1].to_dict()
            recent_action = self._classify_analyst_action(row)
        elif recommendation_key is None and recommendation_mean is None:
            warnings.append("analyst coverage unavailable")
        bias = self._analyst_bias(recommendation_key, recommendation_mean, upside_percent, recent_action)
        score = self._analyst_score(recommendation_mean, upside_percent, recent_action)
        if recommendation_mean is None and recommendation_key is None:
            warnings.append("analyst estimates unavailable")
        return {
            "available": recommendation_mean is not None or recommendation_key is not None or recent_action is not None,
            "source": self.config.source_name,
            "recommendation_key": recommendation_key,
            "recommendation_mean": recommendation_mean,
            "price_target_mean": target_mean,
            "price_target_upside_percent": round(upside_percent, 2) if upside_percent is not None else None,
            "recent_action": recent_action,
            "bias": bias,
            "score": round(score, 2),
            "warnings": warnings,
            "conflict_flags": [],
        }

    def _combine_scores(self, event: dict[str, Any], options: dict[str, Any], analyst: dict[str, Any]) -> dict[str, float]:
        event_score = float(event.get("score", 0.0) or 0.0)
        options_score = float(options.get("score", 0.0) or 0.0)
        analyst_score = float(analyst.get("score", 0.0) or 0.0)
        combined = round((event_score * 0.45) + (options_score * 0.25) + (analyst_score * 0.3), 2)
        return {"event": round(event_score, 2), "options": round(options_score, 2), "analyst": round(analyst_score, 2), "combined": combined}

    def _summary_text(self, event: dict[str, Any], options: dict[str, Any], analyst: dict[str, Any]) -> str:
        parts: list[str] = []
        if event.get("available"):
            event_label = str(event.get("event_label") or event.get("event_class") or "event")
            event_window = str(event.get("window_label") or "unknown")
            parts.append(f"{event_label} {event_window}")
        if options.get("available"):
            parts.append(f"options {options.get('pressure_bias', 'neutral')}")
        if analyst.get("available"):
            parts.append(f"analyst {analyst.get('bias', 'neutral')}")
        if not parts:
            return "Market intelligence unavailable."
        return " · ".join(parts)

    @staticmethod
    def _freshness_status(event: dict[str, Any], options: dict[str, Any], analyst: dict[str, Any]) -> str:
        scores = [item.get("available") for item in (event, options, analyst)]
        if not any(scores):
            return "unknown"
        if any(item.get("warnings") for item in (event, options, analyst)):
            return "degraded"
        return "fresh"

    @staticmethod
    def _safe_expiries(ticker_obj: Any) -> list[str]:
        try:
            expiries = ticker_obj.options
        except Exception:  # noqa: BLE001
            return []
        return [str(item) for item in expiries if isinstance(item, str) and item.strip()]

    def _select_expiry(self, expiries: list[str], *, horizon: StrategyHorizon | None, as_of: datetime | None) -> str | None:
        if not expiries:
            return None
        target_days = self._target_days(horizon)
        parsed = [(expiry, self._days_to_expiry(expiry, as_of=as_of)) for expiry in expiries]
        parsed = [(expiry, days) for expiry, days in parsed if days is not None and days >= 0]
        if not parsed:
            return expiries[0]
        parsed.sort(key=lambda item: abs(item[1] - target_days))
        return parsed[0][0]

    @staticmethod
    def _target_days(horizon: StrategyHorizon | None) -> int:
        if horizon == StrategyHorizon.ONE_DAY:
            return 7
        if horizon == StrategyHorizon.ONE_MONTH:
            return 30
        return 14

    @staticmethod
    def _days_to_expiry(expiry: str, as_of: datetime | None = None) -> int | None:
        try:
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except ValueError:
            return None
        reference = (as_of or datetime.now(timezone.utc)).date()
        return (expiry_date - reference).days

    @staticmethod
    def _calendar_date(ticker_obj: Any) -> datetime | None:
        try:
            calendar = ticker_obj.calendar
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(calendar, pd.DataFrame) or calendar.empty:
            return None
        index_text = " ".join(str(value) for value in calendar.index.to_list()).lower()
        if "earnings" in index_text:
            try:
                value = calendar.iloc[0, 0]
            except Exception:  # noqa: BLE001
                return None
            return MarketIntelligenceService._coerce_datetime(value)
        return None

    @staticmethod
    def _coerce_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str):
            try:
                normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                try:
                    parsed = datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    return None
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        return None

    @staticmethod
    def _days_between(reference: datetime, event_at: datetime | None) -> int | None:
        if event_at is None:
            return None
        return (event_at.date() - reference.date()).days

    @staticmethod
    def _event_window_label(imminence_days: int | None) -> str:
        if imminence_days is None:
            return "unknown"
        if imminence_days < 0:
            return "past"
        if imminence_days <= 1:
            return "0d_1d"
        if imminence_days <= 5:
            return "2d_5d"
        if imminence_days <= 21:
            return "1w_1m"
        return "1m_plus"

    @staticmethod
    def _event_score(imminence_days: int | None) -> float:
        if imminence_days is None:
            return 0.0
        if imminence_days < 0:
            return 10.0
        if imminence_days <= 1:
            return 92.0
        if imminence_days <= 3:
            return 86.0
        if imminence_days <= 5:
            return 78.0
        if imminence_days <= 10:
            return 62.0
        if imminence_days <= 21:
            return 40.0
        return 20.0

    @staticmethod
    def _numeric_sum(frame: pd.DataFrame, column: str) -> float:
        if column not in frame.columns or frame.empty:
            return 0.0
        series = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        return float(series.sum())

    @staticmethod
    def _numeric_mean(frame: pd.DataFrame, column: str) -> float | None:
        if column not in frame.columns or frame.empty:
            return None
        series = pd.to_numeric(frame[column], errors="coerce").dropna()
        if series.empty:
            return None
        return float(series.mean())

    @staticmethod
    def _ratio(numerator: float, denominator: float) -> float | None:
        if denominator <= 0:
            return None
        return numerator / denominator

    @staticmethod
    def _coalesce_iv(call_iv: float | None, put_iv: float | None) -> float | None:
        values = [value for value in (call_iv, put_iv) if value is not None and math.isfinite(value)]
        if not values:
            return None
        return float(sum(values) / len(values))

    @staticmethod
    def _options_score(put_call_ratio: float | None, days_to_expiry: int | None, call_iv: float | None, put_iv: float | None) -> float:
        base = 35.0
        if put_call_ratio is not None:
            if put_call_ratio < 0.8:
                base += 35.0
            elif put_call_ratio > 1.2:
                base += 30.0
            else:
                base += 15.0
        if days_to_expiry is not None:
            if days_to_expiry <= 7:
                base += 20.0
            elif days_to_expiry <= 21:
                base += 12.0
            else:
                base += 5.0
        if call_iv is not None or put_iv is not None:
            base += 10.0
        return max(0.0, min(100.0, base))

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(numeric):
            return None
        return numeric

    @staticmethod
    def _classify_analyst_action(row: dict[str, Any]) -> str | None:
        action = str(row.get("action", "") or "").strip().lower()
        if action:
            return action
        from_grade = str(row.get("fromGrade", "") or "").strip().lower()
        to_grade = str(row.get("toGrade", "") or "").strip().lower()
        if from_grade and to_grade and from_grade != to_grade:
            if any(token in to_grade for token in ("buy", "outperform", "overweight")):
                return "upgrade"
            if any(token in to_grade for token in ("sell", "underperform", "underweight")):
                return "downgrade"
        return None

    @staticmethod
    def _analyst_bias(recommendation_key: object, recommendation_mean: float | None, upside_percent: float | None, recent_action: str | None) -> str:
        key = str(recommendation_key or "").strip().lower()
        if recent_action in {"upgrade", "upgrades"}:
            return "bullish"
        if recent_action in {"downgrade", "downgrades"}:
            return "bearish"
        if key in {"strong_buy", "buy", "outperform", "overweight"}:
            return "bullish"
        if key in {"strong_sell", "sell", "underperform", "underweight"}:
            return "bearish"
        if recommendation_mean is not None:
            if recommendation_mean <= 2.0:
                return "bullish"
            if recommendation_mean >= 3.0:
                return "bearish"
        if upside_percent is not None:
            if upside_percent >= 10.0:
                return "bullish"
            if upside_percent <= -5.0:
                return "bearish"
        return "neutral"

    @staticmethod
    def _analyst_score(recommendation_mean: float | None, upside_percent: float | None, recent_action: str | None) -> float:
        score = 30.0
        if recommendation_mean is not None:
            score += max(0.0, min(35.0, (3.5 - recommendation_mean) * 18.0))
        if upside_percent is not None:
            score += max(0.0, min(25.0, abs(upside_percent) * 0.6))
        if recent_action in {"upgrade", "upgrades"}:
            score += 20.0
        if recent_action in {"downgrade", "downgrades"}:
            score += 15.0
        return max(0.0, min(100.0, score))

    @staticmethod
    def _compact_info(info: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "shortName",
            "longName",
            "sector",
            "industry",
            "country",
            "recommendationKey",
            "recommendationMean",
            "targetMeanPrice",
            "currentPrice",
            "regularMarketPrice",
            "earningsTimestamp",
            "earningsTimestampStart",
            "earningsTimestampEnd",
        )
        return {key: info.get(key) for key in keys if key in info}
