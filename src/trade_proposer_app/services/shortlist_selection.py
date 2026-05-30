from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import Watchlist
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class ShortlistCandidate(Protocol):
    ticker: str
    direction: str
    confidence_percent: float
    attention_score: float
    error_message: str | None
    cheap_scan_signal: object | None


@dataclass(frozen=True)
class ShortlistSelectionConfig:
    confidence_threshold: float
    signal_gating_tuning_config: dict[str, float]


class ShortlistSelectionService:
    """Owns shortlist eligibility/ranking so orchestration only coordinates the run."""

    def __init__(self, config: ShortlistSelectionConfig, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.config = config
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def evaluate(self, watchlist: Watchlist, candidates: list[ShortlistCandidate]) -> dict[str, object]:
        if not candidates:
            return {
                "shortlist": [],
                "rules": {
                    "horizon": watchlist.default_horizon.value,
                    "watchlist_size": 0,
                    "allow_shorts": watchlist.allow_shorts,
                    "limit": 0,
                    "minimum_confidence_percent": 0.0,
                    "minimum_attention_score": 0.0,
                },
                "decisions": [],
                "rejection_counts": {},
            }
        ticker_count = len(candidates)
        limit = self.shortlist_limit(watchlist.default_horizon, ticker_count)
        minimum_confidence = self.minimum_shortlist_confidence(watchlist.default_horizon, ticker_count)
        minimum_attention = self.minimum_shortlist_attention(watchlist.default_horizon, ticker_count)
        core_limit = ticker_count
        catalyst_threshold = self.minimum_catalyst_proxy_score(watchlist.default_horizon, ticker_count)
        ranked = self._rank_candidates(candidates, watchlist)
        eligibility = self._eligibility_by_ticker(
            ranked,
            watchlist,
            minimum_confidence=minimum_confidence,
            minimum_attention=minimum_attention,
        )
        shortlist, selection_lane = self._select_shortlist(
            ranked,
            watchlist,
            eligibility=eligibility,
            limit=limit,
            core_limit=core_limit,
            catalyst_lane_limit=ticker_count,
            minimum_confidence=minimum_confidence,
            minimum_attention=minimum_attention,
            catalyst_threshold=catalyst_threshold,
        )
        decisions, rejection_counts = self._decision_payloads(
            ranked,
            shortlist=shortlist,
            selection_lane=selection_lane,
            eligibility=eligibility,
            catalyst_threshold=catalyst_threshold,
        )
        return {
            "shortlist": shortlist,
            "rules": {
                "horizon": watchlist.default_horizon.value,
                "watchlist_size": ticker_count,
                "allow_shorts": watchlist.allow_shorts,
                "limit": limit,
                "core_limit": core_limit,
                "catalyst_lane_limit": ticker_count,
                "minimum_confidence_percent": minimum_confidence,
                "minimum_attention_score": minimum_attention,
                "minimum_catalyst_proxy_score": catalyst_threshold,
            },
            "decisions": decisions,
            "rejection_counts": rejection_counts,
        }

    @staticmethod
    def _rank_candidates(candidates: list[ShortlistCandidate], watchlist: Watchlist) -> list[ShortlistCandidate]:
        return sorted(
            candidates,
            key=lambda item: (
                0 if item.error_message else 1,
                0 if (item.direction == "short" and not watchlist.allow_shorts) else 1,
                item.attention_score,
                item.confidence_percent,
            ),
            reverse=True,
        )

    @staticmethod
    def _eligibility_by_ticker(
        ranked: list[ShortlistCandidate],
        watchlist: Watchlist,
        *,
        minimum_confidence: float,
        minimum_attention: float,
    ) -> dict[str, tuple[bool, list[str]]]:
        eligibility: dict[str, tuple[bool, list[str]]] = {}
        for candidate in ranked:
            reasons: list[str] = []
            eligible = True
            if candidate.error_message:
                reasons.append("cheap_scan_error")
                eligible = False
            if candidate.direction == "short" and not watchlist.allow_shorts:
                reasons.append("shorts_disabled")
                eligible = False
            if candidate.confidence_percent < minimum_confidence:
                reasons.append("below_confidence_threshold")
                eligible = False
            if candidate.attention_score < minimum_attention:
                reasons.append("below_attention_threshold")
                eligible = False
            eligibility[candidate.ticker] = (eligible, reasons)
        return eligibility

    def _select_shortlist(
        self,
        ranked: list[ShortlistCandidate],
        watchlist: Watchlist,
        *,
        eligibility: dict[str, tuple[bool, list[str]]],
        limit: int,
        core_limit: int,
        catalyst_lane_limit: int,
        minimum_confidence: float,
        minimum_attention: float,
        catalyst_threshold: float,
    ) -> tuple[list[str], dict[str, str]]:
        shortlist: list[str] = []
        selection_lane: dict[str, str] = {}
        for candidate in ranked:
            eligible, _ = eligibility[candidate.ticker]
            if eligible and len(shortlist) < core_limit:
                shortlist.append(candidate.ticker)
                selection_lane[candidate.ticker] = "technical"
        catalyst_ranked = sorted([candidate for candidate in ranked if candidate.ticker not in shortlist], key=self.catalyst_shortlist_score, reverse=True)
        for candidate in catalyst_ranked:
            if catalyst_lane_limit <= 0 or len(shortlist) >= limit:
                break
            eligible, reasons = eligibility[candidate.ticker]
            if candidate.ticker in shortlist:
                continue
            if self._catalyst_lane_eligible(
                candidate,
                watchlist,
                eligible=eligible,
                reasons=reasons,
                minimum_confidence=minimum_confidence,
                minimum_attention=minimum_attention,
                catalyst_threshold=catalyst_threshold,
            ):
                shortlist.append(candidate.ticker)
                selection_lane[candidate.ticker] = "catalyst"
                catalyst_lane_limit -= 1
        return shortlist, selection_lane

    def _catalyst_lane_eligible(
        self,
        candidate: ShortlistCandidate,
        watchlist: Watchlist,
        *,
        eligible: bool,
        reasons: list[str],
        minimum_confidence: float,
        minimum_attention: float,
        catalyst_threshold: float,
    ) -> bool:
        catalyst_score = self.catalyst_shortlist_score(candidate)
        relaxed_confidence_floor = max(40.0, minimum_confidence - 8.0)
        relaxed_attention_floor = max(55.0, minimum_attention)
        return (
            not candidate.error_message
            and not (candidate.direction == "short" and not watchlist.allow_shorts)
            and candidate.confidence_percent >= relaxed_confidence_floor
            and candidate.attention_score >= relaxed_attention_floor
            and catalyst_score >= catalyst_threshold
            and (eligible or "below_confidence_threshold" in reasons or "below_attention_threshold" in reasons)
        )

    def _decision_payloads(
        self,
        ranked: list[ShortlistCandidate],
        *,
        shortlist: list[str],
        selection_lane: dict[str, str],
        eligibility: dict[str, tuple[bool, list[str]]],
        catalyst_threshold: float,
    ) -> tuple[list[dict[str, object]], dict[str, int]]:
        decisions: list[dict[str, object]] = []
        rejection_counts: dict[str, int] = {}
        for rank, candidate in enumerate(ranked, start=1):
            eligible, reasons = eligibility[candidate.ticker]
            shortlisted = candidate.ticker in shortlist
            if eligible and not shortlisted:
                reasons = [*reasons, "outside_shortlist_limit"]
            if not shortlisted and self.catalyst_shortlist_score(candidate) < catalyst_threshold:
                reasons = [*reasons, "below_catalyst_lane_threshold"]
            deduped_reasons = list(dict.fromkeys(reasons))
            for reason in deduped_reasons:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            lane = selection_lane.get(candidate.ticker)
            decisions.append(
                {
                    "ticker": candidate.ticker,
                    "rank": rank,
                    "direction": candidate.direction,
                    "confidence_percent": candidate.confidence_percent,
                    "attention_score": candidate.attention_score,
                    "catalyst_proxy_score": self.catalyst_shortlist_score(candidate),
                    "shortlisted": shortlisted,
                    "shortlist_rank": shortlist.index(candidate.ticker) + 1 if shortlisted else None,
                    "selection_lane": lane,
                    "selection_lane_label": self.shortlist_selection_lane_label(lane),
                    "reasons": deduped_reasons,
                    "reason_details": self.shortlist_reason_details(deduped_reasons),
                    "eligible": eligible,
                    "error_message": candidate.error_message,
                }
            )
        return decisions, rejection_counts

    @staticmethod
    def shortlist_limit(_horizon: StrategyHorizon, ticker_count: int) -> int:
        return max(0, ticker_count)

    def minimum_shortlist_confidence(self, horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: max(48.0, self.config.confidence_threshold - 8.0),
            StrategyHorizon.ONE_WEEK: max(45.0, self.config.confidence_threshold - 12.0),
            StrategyHorizon.ONE_MONTH: max(42.0, self.config.confidence_threshold - 15.0),
        }[horizon]
        size_bump = 10.0 if ticker_count >= 20 else 5.0 if ticker_count >= 10 else 0.0
        tuning_relief = (
            self.signal_gating_value("threshold_offset", 0.0) * 0.35
            + self.signal_gating_value("confidence_adjustment", 0.0) * 0.25
            + self.signal_gating_value("shortlist_aggressiveness", 1.0) * 1.2
            + self.signal_gating_value("near_miss_gap_cutoff", 1.5) * 0.5
        )
        return min(95.0, max(35.0, base + size_bump - tuning_relief))

    def minimum_shortlist_attention(self, horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: 52.0,
            StrategyHorizon.ONE_WEEK: 45.0,
            StrategyHorizon.ONE_MONTH: 40.0,
        }[horizon]
        size_bump = 12.0 if ticker_count >= 20 else 6.0 if ticker_count >= 10 else 0.0
        tuning_relief = self.signal_gating_value("shortlist_aggressiveness", 1.0) * 1.0
        return min(95.0, max(35.0, base + size_bump - tuning_relief))

    @staticmethod
    def minimum_catalyst_proxy_score(horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: 72.0,
            StrategyHorizon.ONE_WEEK: 68.0,
            StrategyHorizon.ONE_MONTH: 64.0,
        }[horizon]
        if ticker_count >= 20:
            return min(90.0, base + 6.0)
        if ticker_count >= 10:
            return min(90.0, base + 3.0)
        return base

    @staticmethod
    def catalyst_shortlist_score(candidate: ShortlistCandidate) -> float:
        if candidate.cheap_scan_signal is None:
            return 0.0
        directional_score = getattr(candidate.cheap_scan_signal, "directional_score", 0.0)
        breakout_score = getattr(candidate.cheap_scan_signal, "breakout_score", 0.0)
        directional_component = abs(float(directional_score)) * 100.0
        return round((candidate.attention_score * 0.45) + (float(breakout_score) * 0.35) + (directional_component * 0.2), 2)

    def signal_gating_value(self, key: str, default: float) -> float:
        try:
            return float(self.config.signal_gating_tuning_config.get(key, default))
        except (TypeError, ValueError):
            return default

    def shortlist_reason_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            definition = self.taxonomy_service.get_shortlist_reason_definition(value)
            key = str(definition.get("key", value)).strip()
            label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
            if not key or key in seen:
                continue
            seen.add(key)
            details.append({"key": key, "label": label})
        return details

    def shortlist_selection_lane_label(self, value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_shortlist_selection_lane_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
