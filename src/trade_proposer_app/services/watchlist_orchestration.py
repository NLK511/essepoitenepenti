from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal, CheapScanSignalService


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
        deep_analysis_service,
        confidence_threshold: float = 60.0,
        calibration_service: RecommendationPlanCalibrationService | None = None,
    ) -> None:
        self.context_snapshots = context_snapshots
        self.recommendation_plans = recommendation_plans
        self.cheap_scan_service = cheap_scan_service
        self.deep_analysis_service = deep_analysis_service
        self.confidence_threshold = confidence_threshold
        self.calibration_service = calibration_service

    def execute(
        self,
        watchlist: Watchlist,
        tickers: list[str],
        *,
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> dict[str, object]:
        normalized_tickers = [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
        if not normalized_tickers:
            raise ValueError("watchlist job has no effective tickers configured")

        calibration_summary = self._load_calibration_summary()
        candidates = [self._run_cheap_scan(ticker, watchlist.default_horizon) for ticker in normalized_tickers]
        shortlist_evaluation = self._evaluate_shortlist(watchlist, candidates)
        shortlist = shortlist_evaluation["shortlist"]
        shortlist_map = {ticker: rank for rank, ticker in enumerate(shortlist, start=1)}

        stored_signals: list[TickerSignalSnapshot] = []
        stored_plans: list[RecommendationPlan] = []
        legacy_recommendations: list[Recommendation] = []
        ticker_generation: list[dict[str, object]] = []
        warnings_found = False

        for candidate in candidates:
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
                plan = self._build_no_action_plan(
                    watchlist,
                    candidate,
                    stored_signal,
                    calibration_summary=calibration_summary,
                    job_id=job_id,
                    run_id=run_id,
                    reason="Ticker did not make the deep-analysis shortlist.",
                )
                stored_plans.append(self.recommendation_plans.create_plan(plan))
                ticker_generation.append(
                    {
                        "ticker": candidate.ticker,
                        "status": "cheap_scan_only",
                        "shortlisted": False,
                        "attention_score": candidate.attention_score,
                        "shortlist_decision": decision,
                    }
                )
                if candidate.warnings or candidate.error_message:
                    warnings_found = True
                continue

            deep_output, deep_error = self._run_deep_analysis(candidate.ticker, watchlist.default_horizon)
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
            stored_plan = self.recommendation_plans.create_plan(plan)
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
                }
            )
            if plan.action in {"long", "short"} and deep_output is not None:
                legacy_recommendations.append(deep_output.recommendation)
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
            "legacy_recommendation_count": len(legacy_recommendations),
            "actionable_plan_count": len([plan for plan in stored_plans if plan.action in {"long", "short"}]),
            "no_action_plan_count": len([plan for plan in stored_plans if plan.action == "no_action"]),
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_rejections": shortlist_evaluation["rejection_counts"],
            "calibration_enabled": calibration_summary is not None,
            "warnings_found": warnings_found,
        }
        artifact = {
            "mode": "watchlist_orchestration",
            "watchlist_id": watchlist.id,
            "shortlist": shortlist,
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_decisions": shortlist_evaluation["decisions"],
            "calibration_enabled": calibration_summary is not None,
            "ticker_signal_snapshot_ids": [item.id for item in stored_signals],
            "recommendation_plan_ids": [item.id for item in stored_plans],
        }
        return {
            "legacy_recommendations": legacy_recommendations,
            "summary": summary,
            "artifact": artifact,
            "ticker_generation": ticker_generation,
            "warnings_found": warnings_found,
        }

    def _run_cheap_scan(self, ticker: str, horizon: StrategyHorizon) -> _CheapScanCandidate:
        try:
            signal = self.cheap_scan_service.score(ticker, horizon)
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

    def _run_deep_analysis(self, ticker: str, horizon: StrategyHorizon) -> tuple[RunOutput | None, str | None]:
        try:
            if hasattr(self.deep_analysis_service, "analyze"):
                return self.deep_analysis_service.analyze(ticker, horizon=horizon), None
            return self.deep_analysis_service.generate(ticker), None
        except Exception as exc:
            return None, str(exc)

    def _select_shortlist(self, watchlist: Watchlist, candidates: list[_CheapScanCandidate]) -> list[str]:
        evaluation = self._evaluate_shortlist(watchlist, candidates)
        return list(evaluation["shortlist"])

    def _evaluate_shortlist(self, watchlist: Watchlist, candidates: list[_CheapScanCandidate]) -> dict[str, object]:
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
        limit = self._shortlist_limit(watchlist.default_horizon, ticker_count)
        minimum_confidence = self._minimum_shortlist_confidence(watchlist.default_horizon, ticker_count)
        minimum_attention = self._minimum_shortlist_attention(watchlist.default_horizon, ticker_count)
        catalyst_lane_limit = 1 if limit >= 2 else 0
        core_limit = max(0, limit - catalyst_lane_limit)
        ranked = sorted(
            candidates,
            key=lambda item: (
                0 if item.error_message else 1,
                0 if (item.direction == "short" and not watchlist.allow_shorts) else 1,
                item.attention_score,
                item.confidence_percent,
            ),
            reverse=True,
        )
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

        shortlist: list[str] = []
        selection_lane: dict[str, str] = {}
        for candidate in ranked:
            eligible, _ = eligibility[candidate.ticker]
            if eligible and len(shortlist) < core_limit:
                shortlist.append(candidate.ticker)
                selection_lane[candidate.ticker] = "technical"

        catalyst_threshold = self._minimum_catalyst_proxy_score(watchlist.default_horizon, ticker_count)
        catalyst_ranked = sorted(
            [candidate for candidate in ranked if candidate.ticker not in shortlist],
            key=lambda item: self._catalyst_shortlist_score(item),
            reverse=True,
        )
        for candidate in catalyst_ranked:
            if catalyst_lane_limit <= 0 or len(shortlist) >= limit:
                break
            eligible, reasons = eligibility[candidate.ticker]
            catalyst_score = self._catalyst_shortlist_score(candidate)
            relaxed_confidence_floor = max(40.0, minimum_confidence - 8.0)
            relaxed_attention_floor = max(55.0, minimum_attention)
            catalyst_eligible = (
                not candidate.error_message
                and not (candidate.direction == "short" and not watchlist.allow_shorts)
                and candidate.confidence_percent >= relaxed_confidence_floor
                and candidate.attention_score >= relaxed_attention_floor
                and catalyst_score >= catalyst_threshold
            )
            if candidate.ticker in shortlist:
                continue
            if catalyst_eligible and (eligible or "below_confidence_threshold" in reasons or "below_attention_threshold" in reasons):
                shortlist.append(candidate.ticker)
                selection_lane[candidate.ticker] = "catalyst"
                catalyst_lane_limit -= 1

        decisions: list[dict[str, object]] = []
        rejection_counts: dict[str, int] = {}
        for rank, candidate in enumerate(ranked, start=1):
            eligible, reasons = eligibility[candidate.ticker]
            shortlisted = candidate.ticker in shortlist
            if eligible and not shortlisted:
                reasons = [*reasons, "outside_shortlist_limit"]
            if not shortlisted and self._catalyst_shortlist_score(candidate) < catalyst_threshold:
                reasons = [*reasons, "below_catalyst_lane_threshold"]
            deduped_reasons = list(dict.fromkeys(reasons))
            for reason in deduped_reasons:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            decisions.append(
                {
                    "ticker": candidate.ticker,
                    "rank": rank,
                    "direction": candidate.direction,
                    "confidence_percent": candidate.confidence_percent,
                    "attention_score": candidate.attention_score,
                    "catalyst_proxy_score": self._catalyst_shortlist_score(candidate),
                    "shortlisted": shortlisted,
                    "shortlist_rank": shortlist.index(candidate.ticker) + 1 if shortlisted else None,
                    "selection_lane": selection_lane.get(candidate.ticker),
                    "reasons": deduped_reasons,
                    "eligible": eligible,
                    "error_message": candidate.error_message,
                }
            )
        return {
            "shortlist": shortlist,
            "rules": {
                "horizon": watchlist.default_horizon.value,
                "watchlist_size": ticker_count,
                "allow_shorts": watchlist.allow_shorts,
                "limit": limit,
                "core_limit": core_limit,
                "catalyst_lane_limit": 1 if limit >= 2 else 0,
                "minimum_confidence_percent": minimum_confidence,
                "minimum_attention_score": minimum_attention,
                "minimum_catalyst_proxy_score": catalyst_threshold,
            },
            "decisions": decisions,
            "rejection_counts": rejection_counts,
        }

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
        analysis = self._analysis_payload(deep_output or candidate.raw_output)
        deep_recommendation = deep_output.recommendation if deep_output is not None else None
        technical_score = round(
            float(
                deep_recommendation.confidence
                if deep_recommendation is not None
                else (candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else candidate.confidence_percent)
            ),
            2,
        )
        ticker_sentiment_score = self._sentiment_score_to_percent(self._pluck(analysis, "sentiment", "ticker", "score"))
        macro_exposure_score = self._sentiment_score_to_percent(self._pluck(analysis, "sentiment", "macro", "score"))
        industry_alignment_score = self._sentiment_score_to_percent(self._pluck(analysis, "sentiment", "industry", "score"))
        expected_move_score = self._expected_move_score(deep_recommendation)
        execution_quality_score = self._execution_quality_score(deep_recommendation)
        warnings = list(candidate.warnings)
        if deep_output is not None:
            warnings.extend(deep_output.diagnostics.warnings)
        if candidate.direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
        if deep_error:
            warnings.append(deep_error)
        transmission_alignment_score = self._transmission_alignment_score(analysis)
        transmission_bias = self._transmission_bias(analysis)
        if transmission_bias == "unknown":
            transmission_alignment_score = round((macro_exposure_score * 0.45) + (industry_alignment_score * 0.55), 2)
            transmission_bias = self._bias_from_alignment(transmission_alignment_score)
        return TickerSignalSnapshot(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            status="degraded" if warnings else "ok",
            direction=(self._normalize_direction(deep_recommendation.direction) if deep_recommendation is not None else candidate.direction),
            swing_probability_percent=round(float(deep_recommendation.confidence if deep_recommendation is not None else candidate.confidence_percent), 2),
            confidence_percent=round(float(deep_recommendation.confidence if deep_recommendation is not None else candidate.confidence_percent), 2),
            attention_score=round(candidate.attention_score, 2),
            macro_exposure_score=macro_exposure_score,
            industry_alignment_score=industry_alignment_score,
            ticker_sentiment_score=ticker_sentiment_score,
            technical_setup_score=technical_score,
            catalyst_score=self._catalyst_score(analysis),
            expected_move_score=expected_move_score,
            execution_quality_score=execution_quality_score,
            warnings=list(dict.fromkeys(warnings)),
            missing_inputs=[],
            source_breakdown={
                "cheap_scan_summary": candidate.indicator_summary,
                "cheap_scan_model": candidate.cheap_scan_signal.diagnostics.get("model") if candidate.cheap_scan_signal is not None else None,
                "deep_analysis_available": deep_output is not None,
                "deep_analysis_model": self._pluck(analysis, "ticker_deep_analysis", "model"),
                "summary_method": getattr(deep_output.diagnostics, "summary_method", None) if deep_output is not None else None,
                "transmission_bias": transmission_bias,
                "transmission_tags": self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "transmission_tags") or [],
            },
            diagnostics={
                "mode": "deep_analysis" if shortlisted else "cheap_scan_only",
                "shortlisted": shortlisted,
                "shortlist_rank": shortlist_rank,
                "shortlist_reasons": list(shortlist_decision.get("reasons", [])) if isinstance(shortlist_decision, dict) and isinstance(shortlist_decision.get("reasons"), list) else [],
                "shortlist_eligible": bool(shortlist_decision.get("eligible")) if isinstance(shortlist_decision, dict) and shortlist_decision.get("eligible") is not None else shortlisted,
                "selection_lane": shortlist_decision.get("selection_lane") if isinstance(shortlist_decision, dict) else None,
                "cheap_scan_confidence_percent": candidate.confidence_percent,
                "cheap_scan_directional_score": candidate.cheap_scan_signal.directional_score if candidate.cheap_scan_signal is not None else None,
                "cheap_scan_component_scores": {
                    "trend_score": candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else None,
                    "momentum_score": candidate.cheap_scan_signal.momentum_score if candidate.cheap_scan_signal is not None else None,
                    "breakout_score": candidate.cheap_scan_signal.breakout_score if candidate.cheap_scan_signal is not None else None,
                    "volatility_score": candidate.cheap_scan_signal.volatility_score if candidate.cheap_scan_signal is not None else None,
                    "liquidity_score": candidate.cheap_scan_signal.liquidity_score if candidate.cheap_scan_signal is not None else None,
                },
                "deep_analysis_error": deep_error,
                "transmission_alignment_score": transmission_alignment_score,
                "transmission_bias": transmission_bias,
            },
            job_id=job_id,
            run_id=run_id,
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
        analysis = self._analysis_payload(deep_output)
        summary_text = self._pluck(analysis, "summary", "text") or signal.source_breakdown.get("cheap_scan_summary") or ""
        setup_family = self._plan_setup_family(signal, analysis, candidate)
        confidence_components = self._plan_confidence_components(signal, analysis, candidate)
        transmission_summary = self._transmission_summary(signal, analysis, candidate)
        calibration_review = self._calibration_review(
            calibration_summary,
            setup_family,
            signal.confidence_percent,
            horizon=watchlist.default_horizon.value,
            transmission_summary=transmission_summary,
        )
        rationale = self._rationale_summary(signal, candidate, setup_family, transmission_summary)
        warnings = list(signal.warnings)
        if deep_output is None or deep_error is not None:
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action="no_action",
                status="degraded",
                confidence_percent=signal.confidence_percent,
                thesis_summary="Deep analysis did not complete; no actionable plan emitted.",
                rationale_summary=rationale,
                warnings=warnings,
                evidence_summary=self._evidence_summary(summary_text, setup_family, confidence_components, action_reason="deep_analysis_unavailable", calibration_review=calibration_review, transmission_summary=transmission_summary),
                signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        recommendation = deep_output.recommendation
        direction = self._normalize_direction(recommendation.direction)
        action_reason = "actionable_setup"
        effective_threshold = float(calibration_review.get("effective_confidence_threshold", self.confidence_threshold))
        if direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
            action = "no_action"
            action_reason = "shorts_disabled"
        elif signal.confidence_percent < effective_threshold:
            action = "no_action"
            action_reason = "below_calibrated_action_threshold" if effective_threshold > self.confidence_threshold else "below_action_confidence_threshold"
        elif direction not in {"long", "short"}:
            action = "no_action"
            action_reason = "direction_not_actionable"
        elif transmission_summary.get("context_bias") == "headwind" and signal.confidence_percent < min(95.0, effective_threshold + 5.0):
            action = "no_action"
            action_reason = "context_transmission_headwind"
        else:
            action = direction

        if action == "no_action":
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action=action,
                status="ok" if not warnings else "partial",
                confidence_percent=signal.confidence_percent,
                thesis_summary=self._no_action_thesis(setup_family, action_reason),
                rationale_summary=rationale,
                warnings=list(dict.fromkeys(warnings)),
                evidence_summary=self._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
                signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        stop_loss = round(float(recommendation.stop_loss), 4)
        take_profit = round(float(recommendation.take_profit), 4)
        return RecommendationPlan(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            action=action,
            status="ok" if not warnings else "partial",
            confidence_percent=signal.confidence_percent,
            entry_price_low=round(float(recommendation.entry_price), 4),
            entry_price_high=round(float(recommendation.entry_price), 4),
            stop_loss=stop_loss,
            take_profit=take_profit,
            holding_period_days=self._holding_period_days(watchlist.default_horizon),
            risk_reward_ratio=self._risk_reward_ratio(recommendation),
            thesis_summary=summary_text or self._actionable_thesis(action, setup_family),
            rationale_summary=rationale,
            risks=self._plan_risks(warnings, setup_family, action),
            warnings=list(dict.fromkeys(warnings)),
            evidence_summary=self._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
            signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
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
        setup_family = self._cheap_scan_setup_family(candidate)
        confidence_components = self._plan_confidence_components(signal, {}, candidate)
        transmission_summary = self._transmission_summary(signal, {}, candidate)
        calibration_review = self._calibration_review(
            calibration_summary,
            setup_family,
            signal.confidence_percent,
            horizon=watchlist.default_horizon.value,
            transmission_summary=transmission_summary,
        )
        return RecommendationPlan(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            action="no_action",
            status="ok" if not signal.warnings else "partial",
            confidence_percent=signal.confidence_percent,
            thesis_summary=reason,
            rationale_summary=self._rationale_summary(signal, candidate, setup_family, transmission_summary),
            warnings=list(signal.warnings),
            evidence_summary=self._evidence_summary(candidate.indicator_summary, setup_family, confidence_components, action_reason="not_shortlisted", calibration_review=calibration_review, transmission_summary=transmission_summary),
            signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
        )

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
            if not isinstance(current, dict):
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

    @staticmethod
    def _transmission_bias(analysis: dict[str, Any]) -> str:
        value = WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "context_bias")
        return value.strip() if isinstance(value, str) and value.strip() else "unknown"

    @staticmethod
    def _bias_from_alignment(alignment_percent: float) -> str:
        if alignment_percent >= 62.0:
            return "tailwind"
        if alignment_percent <= 42.0:
            return "headwind"
        return "mixed"

    @staticmethod
    def _signal_breakdown(
        signal: TickerSignalSnapshot,
        *,
        setup_family: str,
        confidence_components: dict[str, float],
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "attention_score": signal.attention_score,
            "macro_exposure_score": signal.macro_exposure_score,
            "industry_alignment_score": signal.industry_alignment_score,
            "ticker_sentiment_score": signal.ticker_sentiment_score,
            "technical_setup_score": signal.technical_setup_score,
            "catalyst_score": signal.catalyst_score,
            "expected_move_score": signal.expected_move_score,
            "execution_quality_score": signal.execution_quality_score,
            "setup_family": setup_family,
            "confidence_components": confidence_components,
            "confidence_bucket": WatchlistOrchestrationService._confidence_bucket(signal.confidence_percent),
            "calibration_review": calibration_review or {},
            "transmission_summary": transmission_summary or {},
            "mode": signal.diagnostics.get("mode"),
        }

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
        explicit = self._pluck(analysis, "ticker_deep_analysis", "confidence_components")
        if isinstance(explicit, dict) and explicit:
            return {str(key): round(float(value), 2) for key, value in explicit.items() if self._is_number(value)}
        return {
            "context_confidence": round((signal.macro_exposure_score * 0.45) + (signal.industry_alignment_score * 0.55), 2),
            "directional_confidence": round(max(signal.ticker_sentiment_score, candidate.confidence_percent), 2),
            "catalyst_confidence": round(signal.catalyst_score, 2),
            "technical_clarity": round(signal.technical_setup_score, 2),
            "execution_clarity": round(signal.execution_quality_score if signal.execution_quality_score > 0 else signal.attention_score, 2),
            "data_quality_cap": round(max(25.0, 100.0 - (len(signal.warnings) * 10.0)), 2),
        }

    def _transmission_summary(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
    ) -> dict[str, object]:
        explicit = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis")
        if isinstance(explicit, dict) and explicit:
            return {
                "alignment_percent": round(float(explicit.get("alignment_percent", 0.0)), 2) if self._is_number(explicit.get("alignment_percent")) else 0.0,
                "context_bias": self._transmission_bias(analysis),
                "catalyst_intensity_percent": round(float(explicit.get("catalyst_intensity_percent", 0.0)), 2) if self._is_number(explicit.get("catalyst_intensity_percent")) else signal.catalyst_score,
                "transmission_tags": explicit.get("transmission_tags", []) if isinstance(explicit.get("transmission_tags"), list) else [],
                "lane_hint": "event" if self._transmission_bias(analysis) == "tailwind" and signal.catalyst_score >= 65.0 else "technical",
            }
        context_alignment = round((signal.macro_exposure_score * 0.45) + (signal.industry_alignment_score * 0.55), 2)
        if context_alignment >= 62.0:
            bias = "tailwind"
        elif context_alignment <= 42.0:
            bias = "headwind"
        else:
            bias = "mixed"
        return {
            "alignment_percent": context_alignment,
            "context_bias": bias,
            "catalyst_intensity_percent": signal.catalyst_score,
            "transmission_tags": [],
            "lane_hint": "event" if signal.catalyst_score >= 65.0 else "technical",
        }

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
        components.append(f"attention {signal.attention_score:.1f}")
        components.append(f"confidence {signal.confidence_percent:.1f}")
        return " · ".join(component for component in components if component)

    @staticmethod
    def _evidence_summary(
        summary_text: str,
        setup_family: str,
        confidence_components: dict[str, float],
        *,
        action_reason: str,
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "summary": summary_text,
            "setup_family": setup_family,
            "action_reason": action_reason,
            "confidence_components": confidence_components,
            "calibration_review": calibration_review or {},
            "transmission_summary": transmission_summary or {},
        }

    @staticmethod
    def _no_action_thesis(setup_family: str, action_reason: str) -> str:
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        if action_reason in {"below_action_confidence_threshold", "below_calibrated_action_threshold"}:
            return f"Detected a {setup_label} candidate, but conviction was too weak for an actionable trade plan."
        if action_reason == "shorts_disabled":
            return f"Detected a {setup_label} candidate, but the watchlist policy does not permit the required short expression."
        if action_reason == "direction_not_actionable":
            return f"Detected a {setup_label} structure, but direction remained too ambiguous for a trade plan."
        if action_reason == "context_transmission_headwind":
            return f"Detected a {setup_label} structure, but macro and industry transmission remained a headwind to the proposed trade direction."
        return "Signal quality was insufficient for an actionable trade plan."

    @staticmethod
    def _actionable_thesis(action: str, setup_family: str) -> str:
        direction = "bullish" if action == "long" else "bearish"
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        return f"Actionable {direction} {setup_label} setup identified."

    @staticmethod
    def _plan_risks(warnings: list[str], setup_family: str, action: str) -> list[str]:
        risks = list(dict.fromkeys(warnings))
        if setup_family in {"breakout", "breakdown"}:
            risks.append("failed follow-through can reverse quickly after entry")
        if setup_family == "mean_reversion":
            risks.append("countertrend timing can fail if momentum persists")
        if setup_family == "catalyst_follow_through":
            risks.append("catalyst impulse may fade quickly if confirmation weakens")
        if setup_family == "macro_beneficiary_loser":
            risks.append("macro transmission can weaken if the broader regime shifts")
        if action in {"long", "short"} and warnings == []:
            risks.append("macro/industry transmission should keep confirming the trade after entry")
        if action == "short":
            risks.append("short squeeze risk remains elevated if sentiment reverses")
        return list(dict.fromkeys(risks))

    @staticmethod
    def _confidence_bucket(confidence_percent: float) -> str:
        if confidence_percent >= 80.0:
            return "80_plus"
        if confidence_percent >= 65.0:
            return "65_to_79"
        if confidence_percent >= 50.0:
            return "50_to_64"
        return "below_50"

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
        if calibration_summary is None:
            return {
                "enabled": False,
                "base_confidence_threshold": round(self.confidence_threshold, 2),
                "effective_confidence_threshold": round(self.confidence_threshold, 2),
                "threshold_adjustment": 0.0,
                "reasons": [],
            }
        bucket_key = self._confidence_bucket(confidence_percent)
        base_threshold = float(self.confidence_threshold)
        overall_win_rate = self._safe_rate(getattr(calibration_summary, "overall_win_rate_percent", None))
        transmission_bias = self._calibration_transmission_bias(transmission_summary)
        context_regime = self._calibration_context_regime(transmission_summary)
        horizon_setup_key = f"{horizon}__{setup_family}"

        setup_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_setup_family", []), setup_family)
        confidence_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_confidence_bucket", []), bucket_key)
        horizon_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_horizon", []), horizon)
        transmission_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_transmission_bias", []), transmission_bias)
        context_regime_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_context_regime", []), context_regime)
        horizon_setup_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_horizon_setup_family", []), horizon_setup_key)

        threshold_adjustment = 0.0
        reasons: list[str] = []
        reviewed_buckets = (
            ("setup_family", setup_bucket, 10.0, 5.0, -3.0),
            ("confidence_bucket", confidence_bucket, 10.0, 5.0, -3.0),
            ("horizon", horizon_bucket, 4.0, 2.0, -1.5),
            ("transmission_bias", transmission_bucket, 4.0, 2.0, -1.5),
            ("context_regime", context_regime_bucket, 4.0, 2.0, -1.5),
            ("horizon_setup_family", horizon_setup_bucket, 6.0, 3.0, -2.0),
        )
        for label, bucket, hard_penalty, soft_penalty, reward in reviewed_buckets:
            adjustment, bucket_reasons = self._bucket_threshold_adjustment(
                label,
                bucket,
                overall_win_rate=overall_win_rate,
                hard_penalty=hard_penalty,
                soft_penalty=soft_penalty,
                reward=reward,
            )
            threshold_adjustment += adjustment
            reasons.extend(bucket_reasons)
        effective_threshold = max(45.0, min(90.0, base_threshold + threshold_adjustment))
        return {
            "enabled": True,
            "base_confidence_threshold": round(base_threshold, 2),
            "effective_confidence_threshold": round(effective_threshold, 2),
            "threshold_adjustment": round(threshold_adjustment, 2),
            "overall_win_rate_percent": overall_win_rate,
            "setup_family": self._bucket_snapshot(setup_family, setup_bucket),
            "confidence_bucket": self._bucket_snapshot(bucket_key, confidence_bucket),
            "horizon": self._bucket_snapshot(horizon, horizon_bucket),
            "transmission_bias": self._bucket_snapshot(transmission_bias, transmission_bucket),
            "context_regime": self._bucket_snapshot(context_regime, context_regime_bucket),
            "horizon_setup_family": self._bucket_snapshot(horizon_setup_key, horizon_setup_bucket),
            "reasons": list(dict.fromkeys(reasons)),
        }

    @staticmethod
    def _find_calibration_bucket(buckets: object, key: str) -> object | None:
        if not isinstance(buckets, list):
            return None
        for bucket in buckets:
            if getattr(bucket, "key", None) == key:
                return bucket
        return None

    def _bucket_threshold_adjustment(
        self,
        label: str,
        bucket: object | None,
        *,
        overall_win_rate: float | None,
        hard_penalty: float,
        soft_penalty: float,
        reward: float,
    ) -> tuple[float, list[str]]:
        if bucket is None:
            return 0.0, []
        resolved_count = int(getattr(bucket, "resolved_count", 0) or 0)
        win_rate = self._safe_rate(getattr(bucket, "win_rate_percent", None))
        if resolved_count < 3 or win_rate is None or overall_win_rate is None:
            return 0.0, []
        if win_rate <= max(35.0, overall_win_rate - 15.0):
            return hard_penalty, [f"{label}_underperforming"]
        if win_rate <= max(45.0, overall_win_rate - 8.0):
            return soft_penalty, [f"{label}_soft_underperformance"]
        if win_rate >= min(80.0, overall_win_rate + 12.0):
            return reward, [f"{label}_outperforming"]
        return 0.0, []

    def _bucket_snapshot(self, key: str, bucket: object | None) -> dict[str, object]:
        return {
            "key": key,
            "resolved_count": int(getattr(bucket, "resolved_count", 0) or 0) if bucket is not None else 0,
            "win_rate_percent": self._safe_rate(getattr(bucket, "win_rate_percent", None)) if bucket is not None else None,
        }

    @staticmethod
    def _calibration_transmission_bias(transmission_summary: dict[str, object] | None) -> str:
        if isinstance(transmission_summary, dict):
            value = transmission_summary.get("context_bias")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "unknown"

    def _calibration_context_regime(self, transmission_summary: dict[str, object] | None) -> str:
        if not isinstance(transmission_summary, dict):
            return "mixed_context"
        tags = transmission_summary.get("transmission_tags")
        normalized_tags = {str(item).strip() for item in tags} if isinstance(tags, list) else set()
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
        bias = self._calibration_transmission_bias(transmission_summary)
        if bias == "tailwind":
            return "tailwind_without_dominant_tag"
        if bias == "headwind":
            return "headwind_without_dominant_tag"
        return "mixed_context"

    @staticmethod
    def _safe_rate(value: object) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _catalyst_shortlist_score(candidate: _CheapScanCandidate) -> float:
        if candidate.cheap_scan_signal is None:
            return 0.0
        directional_component = abs(float(candidate.cheap_scan_signal.directional_score)) * 100.0
        return round(
            (candidate.attention_score * 0.45)
            + (float(candidate.cheap_scan_signal.breakout_score) * 0.35)
            + (directional_component * 0.2),
            2,
        )

    @staticmethod
    def _minimum_catalyst_proxy_score(horizon: StrategyHorizon, ticker_count: int) -> float:
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
    def _holding_period_days(horizon: StrategyHorizon) -> int:
        if horizon == StrategyHorizon.ONE_DAY:
            return 1
        if horizon == StrategyHorizon.ONE_MONTH:
            return 20
        return 5

    @staticmethod
    def _shortlist_limit(horizon: StrategyHorizon, ticker_count: int) -> int:
        if ticker_count <= 0:
            return 0
        if horizon == StrategyHorizon.ONE_DAY:
            if ticker_count <= 5:
                return min(ticker_count, 3)
            if ticker_count <= 12:
                return min(ticker_count, 4)
            return min(ticker_count, 5)
        if horizon == StrategyHorizon.ONE_MONTH:
            if ticker_count <= 8:
                return min(ticker_count, 2)
            if ticker_count <= 20:
                return min(ticker_count, 3)
            return min(ticker_count, 4)
        if ticker_count <= 6:
            return min(ticker_count, 2)
        if ticker_count <= 15:
            return min(ticker_count, 3)
        return min(ticker_count, 4)

    def _minimum_shortlist_confidence(self, horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: max(48.0, self.confidence_threshold - 8.0),
            StrategyHorizon.ONE_WEEK: max(45.0, self.confidence_threshold - 12.0),
            StrategyHorizon.ONE_MONTH: max(42.0, self.confidence_threshold - 15.0),
        }[horizon]
        size_bump = 0.0
        if ticker_count >= 20:
            size_bump = 10.0
        elif ticker_count >= 10:
            size_bump = 5.0
        return min(95.0, base + size_bump)

    @staticmethod
    def _minimum_shortlist_attention(horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: 52.0,
            StrategyHorizon.ONE_WEEK: 45.0,
            StrategyHorizon.ONE_MONTH: 40.0,
        }[horizon]
        size_bump = 0.0
        if ticker_count >= 20:
            size_bump = 12.0
        elif ticker_count >= 10:
            size_bump = 6.0
        return min(95.0, base + size_bump)
