from __future__ import annotations

import json
import math
import logging
from typing import Any
from datetime import datetime, timezone

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.shortlist_selection import ShortlistSelectionConfig, ShortlistSelectionService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignalService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy
from trade_proposer_app.services.watchlist_plan_framing import WatchlistPlanFramingService
from trade_proposer_app.services.watchlist_decision_samples import WatchlistDecisionSampleService
from trade_proposer_app.services.watchlist_signal_builder import WatchlistSignalBuilder
from trade_proposer_app.services.watchlist_calibration_review import WatchlistCalibrationReviewService
from trade_proposer_app.services.watchlist_transmission import WatchlistTransmissionService
from trade_proposer_app.services.watchlist_plan_narrative import WatchlistPlanNarrativeService
from trade_proposer_app.services.watchlist_candidates import CheapScanCandidate as _CheapScanCandidate
from trade_proposer_app.services.watchlist_scan_runner import WatchlistScanRunnerService
from trade_proposer_app.services.watchlist_execution import WatchlistExecutionService

logger = logging.getLogger(__name__)

class WatchlistOrchestrationService:
    def __init__(
        self,
        *,
        context_snapshots: ContextSnapshotRepository,
        recommendation_plans: RecommendationPlanRepository,
        cheap_scan_service: CheapScanSignalService,
        decision_samples: RecommendationDecisionSampleRepository | None = None,
        deep_analysis_service,
        confidence_threshold: float = 60.0,
        signal_gating_tuning_config: dict[str, float] | None = None,
        plan_generation_tuning_config: dict[str, float] | None = None,
        trade_decision_policy: TradeDecisionPolicy | None = None,
        calibration_service: RecommendationPlanCalibrationService | None = None,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.context_snapshots = context_snapshots
        self.recommendation_plans = recommendation_plans
        self.decision_samples = decision_samples
        self.cheap_scan_service = cheap_scan_service
        self.deep_analysis_service = deep_analysis_service
        self.trade_decision_policy = trade_decision_policy
        self.confidence_threshold = trade_decision_policy.confidence_threshold if trade_decision_policy is not None else confidence_threshold
        self.action_confidence_threshold = trade_decision_policy.action_confidence_threshold() if trade_decision_policy is not None else confidence_threshold
        self.signal_gating_tuning_config = trade_decision_policy.signal_gating.to_dict() if trade_decision_policy is not None else self._normalize_signal_gating_tuning_config(signal_gating_tuning_config)
        self.plan_generation_tuning_config = dict(trade_decision_policy.plan_generation_config) if trade_decision_policy is not None else normalize_plan_generation_tuning_config(plan_generation_tuning_config)
        self.calibration_service = calibration_service
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.shortlist_selection = ShortlistSelectionService(
            ShortlistSelectionConfig(
                confidence_threshold=self.confidence_threshold,
                signal_gating_tuning_config=self.signal_gating_tuning_config,
            ),
            taxonomy_service=self.taxonomy_service,
        )
        self.scan_runner = WatchlistScanRunnerService(self.cheap_scan_service, self.deep_analysis_service)
        self.execution_service = WatchlistExecutionService(self)
        self.plan_narrative = WatchlistPlanNarrativeService(action_reason_label=self._action_reason_label)
        self.transmission_service = WatchlistTransmissionService(self)
        self.calibration_review_service = WatchlistCalibrationReviewService(self)
        self.signal_builder = WatchlistSignalBuilder(self)
        self.plan_framing = WatchlistPlanFramingService(self)
        self.decision_sample_recorder = WatchlistDecisionSampleService(self)

    @staticmethod
    def _normalize_signal_gating_tuning_config(signal_gating_tuning_config: dict[str, float] | None) -> dict[str, float]:
        defaults = {
            "threshold_offset": 0.0,
            "confidence_adjustment": 0.0,
            "near_miss_gap_cutoff": 0.0,
            "shortlist_aggressiveness": 0.0,
            "degraded_penalty": 0.0,
        }
        if not signal_gating_tuning_config:
            return defaults
        normalized = dict(defaults)
        for key, default in defaults.items():
            raw_value = signal_gating_tuning_config.get(key, default)
            try:
                normalized[key] = float(raw_value)
            except (TypeError, ValueError):
                normalized[key] = default
        return normalized

    def _signal_gating_tuning_value(self, key: str, default: float) -> float:
        try:
            return float(self.signal_gating_tuning_config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _plan_generation_tuning_value(self, key: str, default: float) -> float:
        try:
            return float(self.plan_generation_tuning_config.get(key, default))
        except (TypeError, ValueError):
            return default

    def execute(
        self,
        watchlist: Watchlist,
        tickers: list[str],
        *,
        job_id: int | None = None,
        run_id: int | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, object]:
        return self.execution_service.execute(watchlist, tickers, job_id=job_id, run_id=run_id, as_of=as_of)

    def _run_cheap_scan(self, ticker: str, horizon: StrategyHorizon, as_of: datetime | None = None) -> _CheapScanCandidate:
        return self.scan_runner.run_cheap_scan(ticker, horizon, as_of=as_of)

    def _run_deep_analysis(self, ticker: str, horizon: StrategyHorizon, as_of: datetime | None = None) -> tuple[RunOutput | None, str | None]:
        return self.scan_runner.run_deep_analysis(ticker, horizon, as_of=as_of)

    def _select_shortlist(self, watchlist: Watchlist, candidates: list[_CheapScanCandidate]) -> list[str]:
        evaluation = self._evaluate_shortlist(watchlist, candidates)
        return list(evaluation["shortlist"])

    def _evaluate_shortlist(self, watchlist: Watchlist, candidates: list[_CheapScanCandidate]) -> dict[str, object]:
        return self.shortlist_selection.evaluate(watchlist, candidates)

    @staticmethod
    def _shortlist_decision_for_ticker(evaluation: dict[str, object], ticker: str) -> dict[str, object] | None:
        decisions = evaluation.get("decisions")
        if not isinstance(decisions, list):
            return None
        for decision in decisions:
            if isinstance(decision, dict) and decision.get("ticker") == ticker:
                return decision
        return None

    def _build_signal_snapshot(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        *,
        deep_output: RunOutput | None,
        job_id: int | None,
        run_id: int | None,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None = None,
        deep_error: str | None = None,
    ) -> TickerSignalSnapshot:
        return self.signal_builder.build_signal_snapshot(
            watchlist,
            candidate,
            deep_output=deep_output,
            job_id=job_id,
            run_id=run_id,
            shortlisted=shortlisted,
            shortlist_rank=shortlist_rank,
            shortlist_decision=shortlist_decision,
            deep_error=deep_error,
        )

    def _with_trade_policy_snapshot(self, plan: RecommendationPlan) -> RecommendationPlan:
        if self.trade_decision_policy is None:
            return plan
        snapshot = self.trade_decision_policy.to_dict()
        return plan.model_copy(
            update={
                "trade_policy_id": self.trade_decision_policy.policy_id,
                "trade_policy_snapshot": snapshot,
            }
        )

    def _build_plan_from_signal(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        signal: TickerSignalSnapshot,
        *,
        deep_output: RunOutput | None,
        deep_error: str | None,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
    ) -> RecommendationPlan:
        return self.plan_framing.build_plan_from_signal(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=deep_error,
            calibration_summary=calibration_summary,
            job_id=job_id,
            run_id=run_id,
        )

    def _build_no_action_plan(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        signal: TickerSignalSnapshot,
        *,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
        reason: str,
    ) -> RecommendationPlan:
        return self.plan_framing.build_no_action_plan(
            watchlist,
            candidate,
            signal,
            calibration_summary=calibration_summary,
            job_id=job_id,
            run_id=run_id,
            reason=reason,
        )

    def _record_non_shortlisted_decision_sample(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        *,
        signal: TickerSignalSnapshot,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
        shortlist_decision: dict[str, object] | None,
    ) -> None:
        self.decision_sample_recorder.record_non_shortlisted_decision_sample(
            watchlist,
            candidate,
            signal=signal,
            calibration_summary=calibration_summary,
            job_id=job_id,
            run_id=run_id,
            shortlist_decision=shortlist_decision,
        )

    def _record_decision_sample(
        self,
        plan: RecommendationPlan,
        candidate: _CheapScanCandidate,
        *,
        signal: TickerSignalSnapshot,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None,
    ) -> None:
        self.decision_sample_recorder.record_decision_sample(
            plan,
            candidate,
            signal=signal,
            shortlisted=shortlisted,
            shortlist_rank=shortlist_rank,
            shortlist_decision=shortlist_decision,
        )

    @staticmethod
    def _mapping(payload: object | None) -> dict[str, object]:
        return WatchlistDecisionSampleService.mapping(payload)

    @staticmethod
    def _float_from_mapping(payload: object, key: str) -> float | None:
        return WatchlistDecisionSampleService.float_from_mapping(payload, key)

    @staticmethod
    def _decision_type(
        action: str,
        status: str,
        action_reason: str,
        confidence_gap: float | None,
        *,
        shortlisted: bool,
    ) -> str:
        return WatchlistDecisionSampleService.decision_type(
            action,
            status,
            action_reason,
            confidence_gap,
            shortlisted=shortlisted,
        )

    @staticmethod
    def _review_priority(
        decision_type: str,
        *,
        confidence_gap: float | None,
        shortlisted: bool,
        status: str,
    ) -> str:
        return WatchlistDecisionSampleService.review_priority(
            decision_type,
            confidence_gap=confidence_gap,
            shortlisted=shortlisted,
            status=status,
        )

    @staticmethod
    def _deep_analysis_confidence(output: RunOutput | None, *, deep_error: str | None = None) -> float | None:
        if output is None or deep_error is not None:
            return None
        try:
            return round(float(output.recommendation.confidence), 2)
        except (TypeError, ValueError):
            return None

    def _plan_gate_confidence(
        self,
        signal: TickerSignalSnapshot,
        *,
        deep_output: RunOutput | None,
        deep_error: str | None = None,
    ) -> float:
        deep_confidence = self._deep_analysis_confidence(deep_output, deep_error=deep_error)
        if deep_confidence is not None:
            return deep_confidence
        return round(float(signal.confidence_percent), 2)

    @staticmethod
    def _analysis_payload(output: RunOutput | None) -> dict[str, Any]:
        if output is None or not output.diagnostics.analysis_json:
            return {}
        try:
            payload = json.loads(output.diagnostics.analysis_json)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _normalize_direction(direction: RecommendationDirection | str | None) -> str:
        if isinstance(direction, RecommendationDirection):
            raw = direction.value
        else:
            raw = str(direction or "neutral")
        normalized = raw.strip().lower()
        if normalized == "long":
            return "long"
        if normalized == "short":
            return "short"
        return "neutral"

    @staticmethod
    def _pluck(payload: dict[str, Any], *path: str) -> Any:
        current: Any = payload
        for key in path:
            if not hasattr(current, "get"):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _sentiment_score_to_percent(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(100.0, (numeric + 1.0) * 50.0)), 2)

    @staticmethod
    def _expected_move_score(recommendation: Recommendation | None) -> float:
        if recommendation is None or recommendation.entry_price == 0:
            return 0.0
        distance = abs(float(recommendation.take_profit) - float(recommendation.entry_price)) / abs(float(recommendation.entry_price))
        return round(max(0.0, min(100.0, distance * 1000.0)), 2)

    @staticmethod
    def _execution_quality_score(recommendation: Recommendation | None) -> float:
        if recommendation is None:
            return 0.0
        reward = abs(float(recommendation.take_profit) - float(recommendation.entry_price))
        risk = abs(float(recommendation.entry_price) - float(recommendation.stop_loss))
        if risk <= 0:
            return 0.0
        return round(max(0.0, min(100.0, (reward / risk) * 40.0)), 2)

    @staticmethod
    def _risk_reward_ratio(recommendation: Recommendation) -> float | None:
        reward = abs(float(recommendation.take_profit) - float(recommendation.entry_price))
        risk = abs(float(recommendation.entry_price) - float(recommendation.stop_loss))
        if risk <= 0:
            return None
        return round(reward / risk, 4)

    @staticmethod
    def _catalyst_score(analysis: dict[str, Any]) -> float:
        explicit = WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "catalyst_intensity_percent")
        if WatchlistOrchestrationService._is_number(explicit):
            market_support = WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "market_intelligence_support_percent")
            support = float(market_support) if WatchlistOrchestrationService._is_number(market_support) else 0.0
            return round(max(0.0, min(100.0, float(explicit) + (support * 0.2))), 2)
        market_intelligence = WatchlistOrchestrationService._pluck(analysis, "market_intelligence") or WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "market_intelligence")
        if isinstance(market_intelligence, dict):
            combined = market_intelligence.get("confidence_contribution", {}) if isinstance(market_intelligence.get("confidence_contribution"), dict) else {}
            if isinstance(combined, dict):
                score = float(combined.get("combined", 0.0) or 0.0)
                if score > 0.0:
                    return round(max(0.0, min(100.0, score)), 2)
        news_item_count = WatchlistOrchestrationService._pluck(analysis, "news", "item_count")
        try:
            count = float(news_item_count)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(100.0, count * 10.0)), 2)

    @staticmethod
    def _transmission_alignment_score(analysis: dict[str, Any]) -> float:
        value = WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "alignment_percent")
        if WatchlistOrchestrationService._is_number(value):
            return round(float(value), 2)
        return 0.0

    def _transmission_bias(self, analysis: dict[str, Any]) -> str:
        transmission = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis")
        if isinstance(transmission, dict):
            return self.taxonomy_service.derive_transmission_bias(transmission)
        return "unknown"

    def _transmission_bias_detail(self, value: object) -> dict[str, str] | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_transmission_bias_definition(value)
        key = str(definition.get("key", value)).strip() or value.strip()
        label = str(definition.get("label", value)).strip() or value.strip()
        return {"key": key, "label": label}

    @staticmethod
    def _bias_from_alignment(alignment_percent: float) -> str:
        if alignment_percent >= 62.0:
            return "tailwind"
        if alignment_percent <= 42.0:
            return "headwind"
        return "mixed"

    def _transmission_confidence_adjustment(
        self,
        analysis: dict[str, Any],
        *,
        transmission_bias: str,
        alignment_score: float,
    ) -> float:
        return self.transmission_service.transmission_confidence_adjustment(
            analysis,
            transmission_bias=transmission_bias,
            alignment_score=alignment_score,
        )

    def _signal_breakdown(
        self,
        signal: TickerSignalSnapshot,
        *,
        setup_family: str,
        confidence_components: dict[str, float],
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
        intended_action: str | None = None,
        shortlisted: bool | None = None,
        shortlist_rank: int | None = None,
        deep_analysis_confidence_percent: float | None = None,
    ) -> dict[str, object]:
        return self.transmission_service.signal_breakdown(
            signal,
            setup_family=setup_family,
            confidence_components=confidence_components,
            calibration_review=calibration_review,
            transmission_summary=transmission_summary,
            intended_action=intended_action,
            shortlisted=shortlisted,
            shortlist_rank=shortlist_rank,
            deep_analysis_confidence_percent=deep_analysis_confidence_percent,
        )

    @staticmethod
    def _should_block_for_transmission_contradiction(
        transmission_summary: dict[str, object],
        calibrated_confidence: float,
        effective_threshold: float,
    ) -> bool:
        return WatchlistTransmissionService.should_block_for_transmission_contradiction(
            transmission_summary,
            calibrated_confidence,
            effective_threshold,
        )

    @staticmethod
    def _trade_context_quality_status(transmission_summary: dict[str, object]) -> str:
        return WatchlistTransmissionService.trade_context_quality_status(transmission_summary)

    def _plan_setup_family(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
    ) -> str:
        explicit = self._pluck(analysis, "ticker_deep_analysis", "setup_family")
        if isinstance(explicit, str) and explicit.strip() and explicit.strip() not in {"uncategorized", "no_action"}:
            return explicit.strip()
        return self._cheap_scan_setup_family(candidate, signal=signal)

    def _plan_confidence_components(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
    ) -> dict[str, float]:
        return self.transmission_service.plan_confidence_components(signal, analysis, candidate)

    def _transmission_summary(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
    ) -> dict[str, object]:
        return self.transmission_service.transmission_summary(signal, analysis, candidate)

    def _fallback_primary_drivers(
        self,
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        bias: str,
    ) -> list[str]:
        drivers: list[tuple[str, float]] = [
            ("industry_context_support" if bias != "headwind" else "industry_context_headwind", signal.industry_alignment_score),
            ("macro_context_support" if bias != "headwind" else "macro_context_headwind", signal.macro_exposure_score),
            ("ticker_sentiment_confirmation" if bias != "headwind" else "ticker_sentiment_conflict", signal.ticker_sentiment_score),
            ("fresh_catalyst_pressure", signal.catalyst_score),
            ("attention_leader", candidate.attention_score),
        ]
        ranked = [key for key, score in sorted(drivers, key=lambda item: item[1], reverse=True) if score >= 45.0]
        return ranked[:3]

    @staticmethod
    def _string_value(value: object, *, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @staticmethod
    def _fallback_industry_exposure_channels(signal: TickerSignalSnapshot) -> list[str]:
        channels: list[str] = []
        if signal.macro_exposure_score >= 55.0:
            channels.append("macro_regime")
        if signal.industry_alignment_score >= 55.0:
            channels.append("industry_demand")
        if signal.industry_alignment_score >= 65.0:
            channels.append("industry_read_through")
        return channels

    @staticmethod
    def _fallback_ticker_exposure_channels(signal: TickerSignalSnapshot, candidate: _CheapScanCandidate) -> list[str]:
        channels: list[str] = []
        if signal.ticker_sentiment_score >= 55.0:
            channels.append("ticker_sentiment")
        if signal.catalyst_score >= 45.0:
            channels.append("news_catalyst")
        if signal.catalyst_score >= 70.0:
            channels.append("event_follow_through")
        if candidate.attention_score >= 70.0:
            channels.append("attention_leader")
        return channels

    @staticmethod
    def _channel_detail_fallback(channels: list[str]) -> list[dict[str, str]]:
        return [
            {"key": str(channel), "label": str(channel).replace("_", " ")}
            for channel in list(dict.fromkeys(channels))
            if isinstance(channel, str) and channel.strip()
        ]

    def _relationship_detail_fallback(self, relationships: list[dict[str, object]]) -> list[dict[str, object]]:
        details: list[dict[str, object]] = []
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            enriched = {**rel}
            rel_type = str(rel.get("type", "")).strip()
            if rel_type:
                type_def = self.taxonomy_service.get_relationship_type_definition(rel_type)
                enriched["type_label"] = type_def.get("label", rel_type.replace("_", " "))
            channel = str(rel.get("channel", "")).strip()
            if channel:
                channel_def = self.taxonomy_service.get_transmission_channel_definition(channel)
                enriched["channel_label"] = channel_def.get("label", channel.replace("_", " "))
            details.append(enriched)
        return details

    def _transmission_window_detail(self, value: str | None) -> dict[str, str] | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_transmission_window_definition(value)
        key = str(definition.get("key", value)).strip()
        label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
        if not key:
            return None
        return {"key": key, "label": label}

    @staticmethod
    def _detail_fallback(values: list[str]) -> list[dict[str, str]]:
        return [
            {"key": str(value), "label": str(value).replace("_", " ")}
            for value in list(dict.fromkeys(values))
            if isinstance(value, str) and value.strip()
        ]

    def _shortlist_reason_details(self, values: list[str]) -> list[dict[str, str]]:
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

    def _shortlist_selection_lane_label(self, value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_shortlist_selection_lane_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")

    def _counted_shortlist_reason_details(self, counts: dict[str, int]) -> list[dict[str, object]]:
        details: list[dict[str, object]] = []
        for key, count in counts.items():
            definition = self.taxonomy_service.get_shortlist_reason_definition(key)
            details.append({
                "key": str(definition.get("key", key)).strip() or key,
                "label": str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " "),
                "count": int(count or 0),
            })
        return details

    def _calibration_reason_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            definition = self.taxonomy_service.get_calibration_reason_definition(value)
            key = str(definition.get("key", value)).strip()
            label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
            if not key or key in seen:
                continue
            seen.add(key)
            details.append({"key": key, "label": label})
        return details

    def _calibration_review_status_label(self, value: str) -> str:
        definition = self.taxonomy_service.get_calibration_review_status_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")

    def _action_reason_label(self, value: str) -> str:
        definition = self.taxonomy_service.get_action_reason_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")

    @staticmethod
    def _fallback_transmission_window(signal: TickerSignalSnapshot) -> str:
        if signal.catalyst_score >= 70.0:
            return "1d"
        if signal.catalyst_score >= 45.0:
            return "2d_5d"
        if signal.macro_exposure_score >= 60.0 or signal.industry_alignment_score >= 60.0:
            return "1w_plus"
        return "unknown"

    @staticmethod
    def _fallback_transmission_window_placeholder(horizon: StrategyHorizon) -> str:
        if horizon == StrategyHorizon.ONE_DAY:
            return "1d"
        if horizon == StrategyHorizon.ONE_WEEK:
            return "2d_5d"
        if horizon == StrategyHorizon.ONE_MONTH:
            return "1w_plus"
        return "unknown"

    @staticmethod
    def _fallback_decay_state(signal: TickerSignalSnapshot) -> str:
        if signal.catalyst_score >= 75.0:
            return "fresh"
        if signal.catalyst_score >= 45.0:
            return "active"
        if signal.catalyst_score > 0.0:
            return "fading"
        return "unknown"

    @staticmethod
    def _fallback_conflict_flags(
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        bias: str,
    ) -> list[str]:
        flags: list[str] = []
        if bias == "headwind" and candidate.direction in {"long", "short"} and signal.technical_setup_score >= 60.0:
            flags.append("technical_context_conflict")
        if signal.macro_exposure_score >= 55.0 and signal.industry_alignment_score <= 45.0:
            flags.append("macro_industry_conflict")
            flags.append("context_contradiction")
        if signal.ticker_sentiment_score <= 40.0 and candidate.direction == "long":
            flags.append("directional_conflict")
        if signal.ticker_sentiment_score >= 60.0 and candidate.direction == "short":
            flags.append("directional_conflict")
        if signal.catalyst_score >= 65.0 and 45.0 <= signal.industry_alignment_score <= 60.0:
            flags.append("timing_conflict")
        return list(dict.fromkeys(flags))

    def _cheap_scan_setup_family(
        self,
        candidate: _CheapScanCandidate,
        *,
        signal: TickerSignalSnapshot | None = None,
    ) -> str:
        technical = signal.technical_setup_score if signal is not None else (candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else candidate.confidence_percent)
        breakout = candidate.cheap_scan_signal.breakout_score if candidate.cheap_scan_signal is not None else 0.0
        momentum = candidate.cheap_scan_signal.momentum_score if candidate.cheap_scan_signal is not None else 0.0
        catalyst = signal.catalyst_score if signal is not None else 0.0
        macro = signal.macro_exposure_score if signal is not None else 0.0
        industry = signal.industry_alignment_score if signal is not None else 0.0
        direction = candidate.direction
        if candidate.error_message:
            return "no_action"
        if catalyst >= 55.0:
            return "catalyst_follow_through"
        if breakout >= 70.0 and momentum >= 60.0:
            return "breakout" if direction != "short" else "breakdown"
        if technical >= 70.0 and momentum >= 55.0:
            return "continuation"
        if direction == "short" and technical >= 55.0:
            return "macro_beneficiary_loser" if macro >= 55.0 or industry >= 55.0 else "mean_reversion"
        if direction == "long" and technical >= 55.0 and (macro >= 55.0 or industry >= 55.0):
            return "macro_beneficiary_loser"
        if technical >= 50.0:
            return "mean_reversion"
        return "no_action"

    def _rationale_summary(
        self,
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        setup_family: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        return self.plan_narrative.rationale_summary(signal, candidate, setup_family, transmission_summary)

    def _evidence_summary(
        self,
        summary_text: str,
        setup_family: str,
        confidence_components: dict[str, float],
        *,
        action_reason: str,
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self.plan_narrative.evidence_summary(
            summary_text,
            setup_family,
            confidence_components,
            action_reason=action_reason,
            calibration_review=calibration_review,
            transmission_summary=transmission_summary,
        )

    def _no_action_thesis(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        return self.plan_narrative.no_action_thesis(setup_family, action_reason, transmission_summary=transmission_summary)

    def _actionable_thesis(
        self,
        action: str,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        return self.plan_narrative.actionable_thesis(action, setup_family, transmission_summary=transmission_summary)

    @staticmethod
    def _entry_style(setup_family: str) -> str:
        return WatchlistPlanNarrativeService.entry_style(setup_family)

    @staticmethod
    def _stop_style(setup_family: str) -> str:
        return WatchlistPlanNarrativeService.stop_style(setup_family)

    @staticmethod
    def _target_style(setup_family: str) -> str:
        return WatchlistPlanNarrativeService.target_style(setup_family)

    @staticmethod
    def _timing_expectation(setup_family: str, *, transmission_summary: dict[str, object] | None = None) -> str:
        return WatchlistPlanNarrativeService.timing_expectation(setup_family, transmission_summary=transmission_summary)

    @staticmethod
    def _evaluation_focus(setup_family: str) -> list[str]:
        return WatchlistPlanNarrativeService.evaluation_focus(setup_family)

    def _action_reason_detail(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        return self.plan_narrative.action_reason_detail(setup_family, action_reason, transmission_summary=transmission_summary)

    def _invalidation_summary(
        self,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        return self.plan_narrative.invalidation_summary(setup_family, transmission_summary=transmission_summary)

    @staticmethod
    def _primary_driver_label(transmission_summary: dict[str, object] | None) -> str | None:
        return WatchlistPlanNarrativeService.primary_driver_label(transmission_summary)

    @staticmethod
    def _matched_ticker_relationships(transmission_summary: dict[str, object] | None) -> list[dict[str, object]]:
        return WatchlistPlanNarrativeService.matched_ticker_relationships(transmission_summary)

    @staticmethod
    def _relationship_label(relationship: dict[str, object]) -> str | None:
        return WatchlistPlanNarrativeService.relationship_label(relationship)

    @classmethod
    def _relationship_summary(cls, transmission_summary: dict[str, object] | None) -> str | None:
        return WatchlistPlanNarrativeService.relationship_summary(transmission_summary)

    def _family_adjusted_trade_levels(
        self,
        recommendation: Recommendation,
        *,
        setup_family: str,
        action: str,
        transmission_summary: dict[str, object] | None = None,
        volatility_score: float | None = None,
    ) -> tuple[float, float, float, float]:
        bias = transmission_summary.get("context_bias") if isinstance(transmission_summary, dict) else None
        return family_adjusted_trade_levels(
            entry_price=float(recommendation.entry_price),
            stop_loss=float(recommendation.stop_loss),
            take_profit=float(recommendation.take_profit),
            setup_family=setup_family,
            action=action,
            transmission_context_bias=str(bias) if bias is not None else None,
            volatility_score=volatility_score,
            tuning_config=self.plan_generation_tuning_config,
        )

    def _plan_risks(
        self,
        warnings: list[str],
        setup_family: str,
        action: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> list[str]:
        return self.plan_narrative.plan_risks(warnings, setup_family, action, transmission_summary)

    @staticmethod
    def _confidence_bucket(confidence_percent: float) -> str:
        return WatchlistCalibrationReviewService.confidence_bucket(confidence_percent)

    @staticmethod
    def _is_number(value: Any) -> bool:
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True

    def _load_calibration_summary(self) -> object | None:
        if self.calibration_service is None:
            return None
        try:
            return self.calibration_service.summarize(limit=500)
        except Exception:
            return None

    def _calibration_review(
        self,
        calibration_summary: object | None,
        setup_family: str,
        confidence_percent: float,
        *,
        horizon: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self.calibration_review_service.calibration_review(
            calibration_summary,
            setup_family,
            confidence_percent,
            horizon=horizon,
            transmission_summary=transmission_summary,
        )

    def _calibration_curve_snapshot(self, calibration_summary: object | None, confidence_percent: float) -> dict[str, object] | None:
        return self.calibration_review_service.calibration_curve_snapshot(calibration_summary, confidence_percent)

    @staticmethod
    def _safe_rate(value: object) -> float | None:
        return WatchlistCalibrationReviewService.safe_rate(value)

    @staticmethod
    def _holding_period_days(horizon: StrategyHorizon) -> int:
        if horizon == StrategyHorizon.ONE_DAY:
            return 1
        if horizon == StrategyHorizon.ONE_MONTH:
            return 20
        return 5
