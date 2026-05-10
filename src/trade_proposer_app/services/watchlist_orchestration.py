from __future__ import annotations

import json
import math
import logging
from dataclasses import dataclass
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
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal, CheapScanSignalService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy
from trade_proposer_app.services.watchlist_plan_framing import WatchlistPlanFramingService
from trade_proposer_app.services.watchlist_decision_samples import WatchlistDecisionSampleService
from trade_proposer_app.services.watchlist_signal_builder import WatchlistSignalBuilder
from trade_proposer_app.services.watchlist_calibration_review import WatchlistCalibrationReviewService
from trade_proposer_app.services.watchlist_transmission import WatchlistTransmissionService

logger = logging.getLogger(__name__)

@dataclass
class _CheapScanCandidate:
    ticker: str
    direction: str
    confidence_percent: float
    attention_score: float
    warnings: list[str]
    indicator_summary: str
    cheap_scan_signal: CheapScanSignal | None = None
    raw_output: RunOutput | None = None
    error_message: str | None = None


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
        normalized_tickers = [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
        if not normalized_tickers:
            raise ValueError("watchlist job has no effective tickers configured")

        logger.info(f"Starting watchlist orchestration for '{watchlist.name}' ({len(normalized_tickers)} tickers)")
        if as_of:
            logger.info(f"  Simulation mode active: as_of {as_of.isoformat()}")

        calibration_summary = self._load_calibration_summary()
        
        logger.info("  Running cheap scans...")
        candidates = []
        for i, ticker in enumerate(normalized_tickers):
            if (i + 1) % 50 == 0:
                logger.info(f"    Cheap scan progress: {i+1}/{len(normalized_tickers)}")
            candidates.append(self._run_cheap_scan(ticker, watchlist.default_horizon, as_of=as_of))

        logger.info("  Evaluating shortlist...")
        shortlist_evaluation = self._evaluate_shortlist(watchlist, candidates)
        shortlist = shortlist_evaluation["shortlist"]
        shortlist_map = {ticker: rank for rank, ticker in enumerate(shortlist, start=1)}
        logger.info(f"  Shortlist selected: {len(shortlist)} tickers")

        stored_signals: list[TickerSignalSnapshot] = []
        stored_plans: list[RecommendationPlan] = []
        ticker_generation: list[dict[str, object]] = []
        warnings_found = False

        logger.info("  Processing candidates...")
        for i, candidate in enumerate(candidates):
            shortlist_rank = shortlist_map.get(candidate.ticker)
            if shortlist_rank is None:
                decision = self._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
                signal = self._build_signal_snapshot(
                    watchlist,
                    candidate,
                    deep_output=None,
                    job_id=job_id,
                    run_id=run_id,
                    shortlisted=False,
                    shortlist_rank=None,
                    shortlist_decision=decision,
                )
                stored_signal = self.context_snapshots.create_ticker_signal_snapshot(signal)
                stored_signals.append(stored_signal)
                self._record_non_shortlisted_decision_sample(
                    watchlist,
                    candidate,
                    signal=stored_signal,
                    calibration_summary=calibration_summary,
                    job_id=job_id,
                    run_id=run_id,
                    shortlist_decision=decision,
                )
                ticker_generation.append(
                    {
                        "ticker": candidate.ticker,
                        "status": "cheap_scan_only",
                        "shortlisted": False,
                        "attention_score": candidate.attention_score,
                        "shortlist_decision": decision,
                        "recommendation_plan_generated": False,
                        "cheap_scan_price_history": stored_signal.diagnostics.get("cheap_scan_price_history") if hasattr(stored_signal.diagnostics, "get") else None,
                        "deep_analysis_price_history": None,
                    }
                )
                if candidate.warnings or candidate.error_message:
                    warnings_found = True
                continue

            logger.info(f"    Running deep analysis for {candidate.ticker} (rank {shortlist_rank})...")
            deep_output, deep_error = self._run_deep_analysis(candidate.ticker, watchlist.default_horizon, as_of=as_of)
            decision = self._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
            signal = self._build_signal_snapshot(
                watchlist,
                candidate,
                deep_output=deep_output,
                job_id=job_id,
                run_id=run_id,
                shortlisted=True,
                shortlist_rank=shortlist_rank,
                shortlist_decision=decision,
                deep_error=deep_error,
            )
            stored_signal = self.context_snapshots.create_ticker_signal_snapshot(signal)
            stored_signals.append(stored_signal)
            plan = self._build_plan_from_signal(
                watchlist,
                candidate,
                stored_signal,
                deep_output=deep_output,
                deep_error=deep_error,
                calibration_summary=calibration_summary,
                job_id=job_id,
                run_id=run_id,
            )
            stored_plan = self.recommendation_plans.create_plan(self._with_trade_policy_snapshot(plan))
            self._record_decision_sample(
                stored_plan,
                candidate,
                signal=stored_signal,
                shortlisted=True,
                shortlist_rank=shortlist_rank,
                shortlist_decision=decision,
            )
            stored_plans.append(stored_plan)
            ticker_generation.append(
                {
                    "ticker": candidate.ticker,
                    "status": "deep_analysis" if deep_output is not None and deep_error is None else "deep_analysis_failed",
                    "shortlisted": True,
                    "shortlist_rank": shortlist_rank,
                    "attention_score": candidate.attention_score,
                    "plan_action": stored_plan.action,
                    "shortlist_decision": decision,
                    "cheap_scan_price_history": stored_signal.diagnostics.get("cheap_scan_price_history") if hasattr(stored_signal.diagnostics, "get") else None,
                    "deep_analysis_price_history": stored_signal.diagnostics.get("deep_analysis_price_history") if hasattr(stored_signal.diagnostics, "get") else None,
                }
            )
            if candidate.warnings or deep_error or plan.warnings:
                warnings_found = True

        summary = {
            "mode": "watchlist_orchestration",
            "watchlist_id": watchlist.id,
            "watchlist_name": watchlist.name,
            "horizon": watchlist.default_horizon.value,
            "ticker_count": len(normalized_tickers),
            "cheap_scan_count": len(candidates),
            "shortlist_count": len(shortlist),
            "deep_analysis_count": len(shortlist),
            "ticker_signal_snapshot_count": len(stored_signals),
            "recommendation_plan_count": len(stored_plans),
            "actionable_plan_count": len([plan for plan in stored_plans if plan.action in {"long", "short"}]),
            "no_action_plan_count": len([plan for plan in stored_plans if plan.action == "no_action"]),
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_rejections": shortlist_evaluation["rejection_counts"],
            "shortlist_rejection_details": self._counted_shortlist_reason_details(shortlist_evaluation["rejection_counts"]),
            "calibration_enabled": calibration_summary is not None,
            "warnings_found": warnings_found,
            "as_of": as_of.isoformat() if as_of else None,
        }
        artifact = {
            "mode": "watchlist_orchestration",
            "watchlist_id": watchlist.id,
            "shortlist": shortlist,
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_decisions": shortlist_evaluation["decisions"],
            "ticker_generation": ticker_generation,
            "calibration_enabled": calibration_summary is not None,
            "ticker_signal_snapshot_ids": [item.id for item in stored_signals],
            "recommendation_plan_ids": [item.id for item in stored_plans],
        }
        logger.info(f"Orchestration complete: {len(stored_plans)} plans generated.")
        return {
            "summary": summary,
            "artifact": artifact,
            "ticker_generation": ticker_generation,
            "warnings_found": warnings_found,
        }

    def _run_cheap_scan(self, ticker: str, horizon: StrategyHorizon, as_of: datetime | None = None) -> _CheapScanCandidate:
        try:
            signal = self.cheap_scan_service.score(ticker, horizon, as_of=as_of)
        except Exception as exc:
            return _CheapScanCandidate(
                ticker=ticker,
                direction="neutral",
                confidence_percent=0.0,
                attention_score=0.0,
                warnings=[str(exc)],
                indicator_summary="cheap scan failed",
                cheap_scan_signal=None,
                raw_output=None,
                error_message=str(exc),
            )
        return _CheapScanCandidate(
            ticker=ticker,
            direction=signal.directional_bias,
            confidence_percent=signal.confidence_percent,
            attention_score=signal.attention_score,
            warnings=list(signal.warnings),
            indicator_summary=signal.indicator_summary,
            cheap_scan_signal=signal,
            raw_output=None,
        )

    def _run_deep_analysis(self, ticker: str, horizon: StrategyHorizon, as_of: datetime | None = None) -> tuple[RunOutput | None, str | None]:
        try:
            if hasattr(self.deep_analysis_service, "analyze"):
                return self.deep_analysis_service.analyze(ticker, horizon=horizon, as_of=as_of), None
            return self.deep_analysis_service.generate(ticker, as_of=as_of), None
        except Exception as exc:
            return None, str(exc)

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
            return round(float(explicit), 2)
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

    @staticmethod
    def _rationale_summary(
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        setup_family: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        components = [candidate.indicator_summary]
        if setup_family and setup_family != "uncategorized":
            components.append(f"setup family {setup_family.replace('_', ' ')}")
        if isinstance(transmission_summary, dict):
            bias = transmission_summary.get("context_bias")
            if isinstance(bias, str) and bias:
                components.append(f"context {bias}")
            window = transmission_summary.get("expected_transmission_window")
            if isinstance(window, str) and window and window != "unknown":
                components.append(f"window {window}")
            driver_label = WatchlistOrchestrationService._primary_driver_label(transmission_summary)
            if driver_label:
                components.append(f"driver {driver_label}")
            relationship_summary = WatchlistOrchestrationService._relationship_summary(transmission_summary)
            if relationship_summary:
                components.append(f"relationship {relationship_summary}")
        components.append(f"attention {signal.attention_score:.1f}")
        components.append(f"confidence {signal.confidence_percent:.1f}")
        return " · ".join(component for component in components if component)

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
        calibration = calibration_review or {}
        return {
            "summary": summary_text,
            "setup_family": setup_family,
            "action_reason": action_reason,
            "action_reason_label": self._action_reason_label(action_reason),
            "action_reason_detail": self._action_reason_detail(setup_family, action_reason, transmission_summary=transmission_summary),
            "confidence_components": confidence_components,
            "raw_confidence_percent": calibration.get("raw_confidence_percent"),
            "calibrated_confidence_percent": calibration.get("calibrated_confidence_percent"),
            "confidence_adjustment": calibration.get("confidence_adjustment"),
            "calibration_review": calibration,
            "transmission_summary": transmission_summary or {},
            "entry_style": self._entry_style(setup_family),
            "stop_style": self._stop_style(setup_family),
            "target_style": self._target_style(setup_family),
            "timing_expectation": self._timing_expectation(setup_family, transmission_summary=transmission_summary),
            "evaluation_focus": self._evaluation_focus(setup_family),
            "invalidation_summary": self._invalidation_summary(setup_family, transmission_summary=transmission_summary),
        }

    def _no_action_thesis(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        relationship_summary = self._relationship_summary(transmission_summary)
        relationship_suffix = f" Read-through to watch: {relationship_summary}." if relationship_summary else ""
        if action_reason in {"below_action_confidence_threshold", "below_calibrated_action_threshold"}:
            family_text = {
                "breakout": "the breakout lacked enough confirmed follow-through",
                "breakdown": "the breakdown lacked enough confirmed follow-through",
                "continuation": "trend continuation evidence was too soft",
                "mean_reversion": "the reversion case was too weak against the prevailing move",
                "catalyst_follow_through": "the catalyst impulse was not strong enough to trust",
                "macro_beneficiary_loser": "the macro transmission case was not strong enough to express",
            }.get(setup_family, "conviction was too weak")
            return f"Detected a {setup_label} candidate, but {family_text} for an actionable trade plan.{relationship_suffix}"
        if action_reason == "shorts_disabled":
            return f"Detected a {setup_label} candidate, but the watchlist policy does not permit the required short expression.{relationship_suffix}"
        if action_reason == "direction_not_actionable":
            return f"Detected a {setup_label} structure, but direction remained too ambiguous for a trade plan.{relationship_suffix}"
        if action_reason == "not_shortlisted":
            family_text = {
                "breakout": "the breakout was not clean enough relative to stronger shortlist candidates",
                "breakdown": "the breakdown pressure was weaker than the selected names",
                "continuation": "trend continuation quality lagged stronger shortlist names",
                "mean_reversion": "the reversal setup lacked enough exhaustion confirmation",
                "catalyst_follow_through": "the catalyst lane found stronger event continuation candidates",
                "macro_beneficiary_loser": "macro transmission existed but did not rank highly enough for escalation",
            }.get(setup_family, "it did not rank highly enough for escalation")
            return f"Detected a {setup_label} structure, but {family_text}.{relationship_suffix}"
        if action_reason == "context_transmission_headwind":
            driver = self._primary_driver_label(transmission_summary)
            return f"Detected a {setup_label} structure, but macro and industry transmission remained a headwind to the proposed trade direction{f' ({driver})' if driver else ''}.{relationship_suffix}"
        if action_reason == "context_transmission_contradiction":
            driver = self._primary_driver_label(transmission_summary)
            return f"Detected a {setup_label} structure, but active context evidence was internally contradictory{f' around {driver}' if driver else ''}, so the trade case was not clean enough to promote.{relationship_suffix}"
        if action_reason == "context_quality_blocked":
            return f"Detected a {setup_label} structure, but context quality was blocked and the setup was not tradeable.{relationship_suffix}"
        return f"Signal quality was insufficient for an actionable trade plan.{relationship_suffix}".strip()

    def _actionable_thesis(
        self,
        action: str,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        direction = "bullish" if action == "long" else "bearish"
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        driver = self._primary_driver_label(transmission_summary)
        relationship_summary = self._relationship_summary(transmission_summary)
        entry_style = self._entry_style(setup_family).replace("_", " ")
        timing = self._timing_expectation(setup_family, transmission_summary=transmission_summary)
        family_text = {
            "continuation": f"Actionable {direction} continuation setup with trend structure still intact and a pullback-or-reclaim style trigger",
            "breakout": f"Actionable {direction} breakout setup with follow-through conditions in place and a break-or-retest trigger",
            "breakdown": f"Actionable {direction} breakdown setup with support failure or failed retest pressure visible",
            "mean_reversion": f"Actionable {direction} mean reversion setup with a defined reversal window and exhaustion-sensitive timing",
            "catalyst_follow_through": f"Actionable {direction} catalyst follow-through setup while event pressure remains active",
            "macro_beneficiary_loser": f"Actionable {direction} macro beneficiary / loser setup tied to broader context transmission",
        }.get(setup_family, f"Actionable {direction} {setup_label} setup identified")
        if driver and relationship_summary:
            return f"{family_text}; entry style is {entry_style}, expected window is {timing}, the primary driver is {driver}, and ticker read-through is supported by {relationship_summary}."
        if driver:
            return f"{family_text}; entry style is {entry_style}, expected window is {timing}, and the primary driver is {driver}."
        if relationship_summary:
            return f"{family_text}; entry style is {entry_style}, expected window is {timing}, and ticker read-through is supported by {relationship_summary}."
        return f"{family_text}; entry style is {entry_style} and expected window is {timing}."

    @staticmethod
    def _entry_style(setup_family: str) -> str:
        return {
            "continuation": "pullback_or_reclaim",
            "breakout": "break_or_retest",
            "breakdown": "break_or_failed_retest",
            "mean_reversion": "reversal_confirmation",
            "catalyst_follow_through": "post_catalyst_continuation",
            "macro_beneficiary_loser": "context_aligned_pullback",
        }.get(setup_family, "standard_entry")

    @staticmethod
    def _stop_style(setup_family: str) -> str:
        return {
            "continuation": "below_pullback_structure",
            "breakout": "below_break_level_with_buffer",
            "breakdown": "above_failed_retest_level",
            "mean_reversion": "beyond_exhaustion_extreme",
            "catalyst_follow_through": "beyond_catalyst_impulse_level",
            "macro_beneficiary_loser": "below_or_above_exposure_invalidation",
        }.get(setup_family, "generic_structure_stop")

    @staticmethod
    def _target_style(setup_family: str) -> str:
        return {
            "continuation": "trend_extension_or_next_level",
            "breakout": "measured_move_or_next_resistance",
            "breakdown": "measured_move_or_next_support",
            "mean_reversion": "range_midpoint_or_moving_average_retest",
            "catalyst_follow_through": "event_follow_through_extension",
            "macro_beneficiary_loser": "context_continuation_extension",
        }.get(setup_family, "generic_target")

    def _timing_expectation(
        self,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        explicit_window = None
        if isinstance(transmission_summary, dict):
            raw_window = transmission_summary.get("expected_transmission_window")
            if isinstance(raw_window, str) and raw_window and raw_window != "unknown":
                explicit_window = raw_window
        family_default = {
            "continuation": "2d_5d",
            "breakout": "1d_3d",
            "breakdown": "1d_3d",
            "mean_reversion": "2d_5d",
            "catalyst_follow_through": "1d_2d",
            "macro_beneficiary_loser": "1w_plus",
        }.get(setup_family, "unknown")
        return explicit_window or family_default

    @staticmethod
    def _evaluation_focus(setup_family: str) -> list[str]:
        return {
            "continuation": ["trend_persistence", "pullback_hold_quality", "stall_rate"],
            "breakout": ["follow_through_speed", "false_break_frequency", "retest_hold_quality"],
            "breakdown": ["support_failure_persistence", "reclaim_risk", "downside_extension_quality"],
            "mean_reversion": ["reversal_confirmation", "reversion_completion_rate", "trend_resumption_risk"],
            "catalyst_follow_through": ["catalyst_decay_speed", "day1_vs_day5_follow_through", "confirmation_quality"],
            "macro_beneficiary_loser": ["transmission_persistence", "context_regime_sensitivity", "sector_sympathy_quality"],
        }.get(setup_family, ["execution_quality", "follow_through", "risk_control"])

    def _action_reason_detail(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        driver = self._primary_driver_label(transmission_summary)
        relationship_summary = self._relationship_summary(transmission_summary)
        relationship_suffix = f" Relationship read-through: {relationship_summary}." if relationship_summary else ""
        family_label = setup_family.replace("_", " ") if setup_family else "setup"
        if action_reason == "actionable_setup":
            return f"Promoted because the {family_label} structure met the current execution and confidence requirements.{relationship_suffix}"
        if action_reason == "not_shortlisted":
            return f"Observed a potential {family_label} structure, but it did not clear shortlist competition for deep analysis.{relationship_suffix}"
        if action_reason in {"below_action_confidence_threshold", "below_calibrated_action_threshold"}:
            return f"The {family_label} structure remained visible, but conviction and execution clarity were not strong enough to justify promotion.{relationship_suffix}"
        if action_reason == "shorts_disabled":
            return f"The required short expression was blocked by watchlist policy.{relationship_suffix}".strip()
        if action_reason == "direction_not_actionable":
            return f"The {family_label} structure did not resolve into a tradeable direction.{relationship_suffix}"
        if action_reason == "deep_analysis_unavailable":
            return f"Cheap scan detected a possible {family_label} case, but deep analysis did not complete cleanly enough to frame a trade plan.{relationship_suffix}"
        if action_reason == "context_transmission_headwind":
            return f"Broader context remained a headwind to the setup{f' via {driver}' if driver else ''}.{relationship_suffix}"
        if action_reason == "context_transmission_contradiction":
            return f"Broader context evidence remained too contradictory to trust the setup cleanly{f' around {driver}' if driver else ''}.{relationship_suffix}"
        if action_reason == "context_quality_blocked":
            return f"Context quality was blocked, so the {family_label} setup was not tradeable.{relationship_suffix}"
        return f"The {family_label} setup was reviewed but did not earn promotion.{relationship_suffix}"

    def _invalidation_summary(
        self,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        driver = self._primary_driver_label(transmission_summary)
        relationship_summary = self._relationship_summary(transmission_summary)
        base = {
            "continuation": "invalidate if the trend pullback breaks and continuation structure fails",
            "breakout": "invalidate if the breakout loses the breakout level or fails its retest",
            "breakdown": "invalidate if the breakdown reclaims lost support or the failed retest resolves higher",
            "mean_reversion": "invalidate if the stretched move keeps extending and reversal confirmation fails",
            "catalyst_follow_through": "invalidate if the catalyst impulse loses confirmation or post-event continuation stalls",
            "macro_beneficiary_loser": "invalidate if the broader context transmission weakens or sector sympathy breaks",
        }.get(setup_family, "invalidate if the setup loses its defining structure")
        if driver and relationship_summary:
            return f"{base}; primary driver to monitor is {driver}; ticker read-through to monitor is {relationship_summary}"
        if driver:
            return f"{base}; primary driver to monitor is {driver}"
        if relationship_summary:
            return f"{base}; ticker read-through to monitor is {relationship_summary}"
        return base

    @staticmethod
    def _primary_driver_label(transmission_summary: dict[str, object] | None) -> str | None:
        if not isinstance(transmission_summary, dict):
            return None
        details = transmission_summary.get("primary_driver_details")
        if isinstance(details, list) and details:
            first = details[0]
            if isinstance(first, dict):
                label = first.get("label")
                if isinstance(label, str) and label.strip():
                    return label.strip()
        drivers = transmission_summary.get("primary_drivers")
        if not isinstance(drivers, list) or not drivers:
            return None
        first = drivers[0]
        return str(first).replace("_", " ") if isinstance(first, str) and first else None

    @staticmethod
    def _matched_ticker_relationships(transmission_summary: dict[str, object] | None) -> list[dict[str, object]]:
        if not isinstance(transmission_summary, dict):
            return []
        raw = transmission_summary.get("matched_ticker_relationships")
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def _relationship_label(relationship: dict[str, object]) -> str | None:
        relation_type = str(relationship.get("type_label", relationship.get("type", "")) or "").strip().replace("_", " ")
        target = str(relationship.get("target_label", relationship.get("target", "")) or "").strip()
        channel = str(relationship.get("channel_label", relationship.get("channel", "")) or "").strip().replace("_", " ")
        if relation_type and target and channel:
            return f"{relation_type} {target} via {channel}"
        if relation_type and target:
            return f"{relation_type} {target}"
        if target:
            return target
        return None

    @classmethod
    def _relationship_summary(cls, transmission_summary: dict[str, object] | None) -> str | None:
        labels = [
            cls._relationship_label(item)
            for item in cls._matched_ticker_relationships(transmission_summary)[:2]
        ]
        labels = [label for label in labels if label]
        if not labels:
            return None
        return " and ".join(labels)

    def _family_adjusted_trade_levels(
        self,
        recommendation: Recommendation,
        *,
        setup_family: str,
        action: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> tuple[float, float, float, float]:
        bias = transmission_summary.get("context_bias") if isinstance(transmission_summary, dict) else None
        return family_adjusted_trade_levels(
            entry_price=float(recommendation.entry_price),
            stop_loss=float(recommendation.stop_loss),
            take_profit=float(recommendation.take_profit),
            setup_family=setup_family,
            action=action,
            transmission_context_bias=str(bias) if bias is not None else None,
            tuning_config=self.plan_generation_tuning_config,
        )

    @staticmethod
    def _plan_risks(
        warnings: list[str],
        setup_family: str,
        action: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> list[str]:
        risks = list(dict.fromkeys(warnings))
        if setup_family in {"breakout", "breakdown"}:
            risks.append("failed follow-through can reverse quickly after entry")
        if setup_family == "mean_reversion":
            risks.append("countertrend timing can fail if momentum persists")
        if setup_family == "catalyst_follow_through":
            risks.append("catalyst impulse may fade quickly if confirmation weakens")
        if setup_family == "macro_beneficiary_loser":
            risks.append("macro transmission can weaken if the broader regime shifts")
        if isinstance(transmission_summary, dict):
            conflict_flags = transmission_summary.get("conflict_flags")
            if isinstance(conflict_flags, list):
                if "technical_context_conflict" in conflict_flags:
                    risks.append("price structure and broader context are not fully aligned")
                if "macro_industry_conflict" in conflict_flags or "industry_ticker_conflict" in conflict_flags:
                    risks.append("cross-layer context conflicts can weaken follow-through")
                if "context_quality_blocked" in conflict_flags:
                    risks.append("context quality is blocked; this setup should not be traded")
                if "context_quality_degraded" in conflict_flags:
                    risks.append("context quality is degraded; follow-through may be noisier")
            decay_state = transmission_summary.get("decay_state")
            if decay_state == "fading":
                risks.append("context support may already be fading for this horizon")
            if WatchlistOrchestrationService._relationship_summary(transmission_summary):
                risks.append("ticker relationship read-through can break if peer, supplier, or customer confirmation fades")
        if action in {"long", "short"} and warnings == []:
            risks.append("macro/industry transmission should keep confirming the trade after entry")
        if action == "short":
            risks.append("short squeeze risk remains elevated if sentiment reverses")
        return list(dict.fromkeys(risks))

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
