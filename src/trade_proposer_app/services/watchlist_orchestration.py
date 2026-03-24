from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
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
        deep_analysis_proposals,
        confidence_threshold: float = 60.0,
    ) -> None:
        self.context_snapshots = context_snapshots
        self.recommendation_plans = recommendation_plans
        self.cheap_scan_service = cheap_scan_service
        self.deep_analysis_proposals = deep_analysis_proposals
        self.confidence_threshold = confidence_threshold

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
                signal = self._build_signal_snapshot(
                    watchlist,
                    candidate,
                    deep_output=None,
                    job_id=job_id,
                    run_id=run_id,
                    shortlisted=False,
                    shortlist_rank=None,
                )
                stored_signal = self.context_snapshots.create_ticker_signal_snapshot(signal)
                stored_signals.append(stored_signal)
                plan = self._build_no_action_plan(
                    watchlist,
                    candidate,
                    stored_signal,
                    job_id=job_id,
                    run_id=run_id,
                    reason="Ticker did not make the deep-analysis shortlist.",
                )
                stored_plans.append(self.recommendation_plans.create_plan(plan))
                decision = self._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
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

            deep_output, deep_error = self._run_deep_analysis(candidate.ticker)
            signal = self._build_signal_snapshot(
                watchlist,
                candidate,
                deep_output=deep_output,
                job_id=job_id,
                run_id=run_id,
                shortlisted=True,
                shortlist_rank=shortlist_rank,
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
                job_id=job_id,
                run_id=run_id,
            )
            stored_plan = self.recommendation_plans.create_plan(plan)
            stored_plans.append(stored_plan)
            decision = self._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
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
            "warnings_found": warnings_found,
        }
        artifact = {
            "mode": "watchlist_orchestration",
            "watchlist_id": watchlist.id,
            "shortlist": shortlist,
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_decisions": shortlist_evaluation["decisions"],
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

    def _run_deep_analysis(self, ticker: str) -> tuple[RunOutput | None, str | None]:
        try:
            return self.deep_analysis_proposals.generate(ticker), None
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
        shortlist: list[str] = []
        decisions: list[dict[str, object]] = []
        rejection_counts: dict[str, int] = {}
        for rank, candidate in enumerate(ranked, start=1):
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
            shortlisted = eligible and len(shortlist) < limit
            if eligible and not shortlisted:
                reasons.append("outside_shortlist_limit")
            if shortlisted:
                shortlist.append(candidate.ticker)
            for reason in reasons:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            decisions.append(
                {
                    "ticker": candidate.ticker,
                    "rank": rank,
                    "direction": candidate.direction,
                    "confidence_percent": candidate.confidence_percent,
                    "attention_score": candidate.attention_score,
                    "shortlisted": shortlisted,
                    "shortlist_rank": len(shortlist) if shortlisted else None,
                    "reasons": reasons,
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
                "minimum_confidence_percent": minimum_confidence,
                "minimum_attention_score": minimum_attention,
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
                "summary_method": getattr(deep_output.diagnostics, "summary_method", None) if deep_output is not None else None,
            },
            diagnostics={
                "mode": "deep_analysis" if shortlisted else "cheap_scan_only",
                "shortlisted": shortlisted,
                "shortlist_rank": shortlist_rank,
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
        job_id: int | None,
        run_id: int | None,
    ) -> RecommendationPlan:
        analysis = self._analysis_payload(deep_output)
        summary_text = self._pluck(analysis, "summary", "text") or signal.source_breakdown.get("cheap_scan_summary") or ""
        rationale = signal.source_breakdown.get("cheap_scan_summary") or ""
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
                evidence_summary={"summary": summary_text},
                signal_breakdown=self._signal_breakdown(signal),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        recommendation = deep_output.recommendation
        direction = self._normalize_direction(recommendation.direction)
        if direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
            action = "no_action"
        elif signal.confidence_percent < self.confidence_threshold:
            action = "no_action"
        elif direction not in {"long", "short"}:
            action = "no_action"
        else:
            action = direction

        if action == "no_action":
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action=action,
                status="ok" if not warnings else "partial",
                confidence_percent=signal.confidence_percent,
                thesis_summary="Signal quality was insufficient for an actionable trade plan.",
                rationale_summary=rationale,
                warnings=list(dict.fromkeys(warnings)),
                evidence_summary={"summary": summary_text},
                signal_breakdown=self._signal_breakdown(signal),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        entry_low = round(min(recommendation.entry_price, recommendation.take_profit), 4)
        entry_high = round(max(recommendation.entry_price, recommendation.entry_price), 4)
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
            thesis_summary=summary_text or "Actionable setup identified.",
            rationale_summary=rationale,
            risks=list(dict.fromkeys(warnings)),
            warnings=list(dict.fromkeys(warnings)),
            evidence_summary={"summary": summary_text},
            signal_breakdown=self._signal_breakdown(signal),
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
        job_id: int | None,
        run_id: int | None,
        reason: str,
    ) -> RecommendationPlan:
        return RecommendationPlan(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            action="no_action",
            status="ok" if not signal.warnings else "partial",
            confidence_percent=signal.confidence_percent,
            thesis_summary=reason,
            rationale_summary=candidate.indicator_summary,
            warnings=list(signal.warnings),
            evidence_summary={"cheap_scan_summary": candidate.indicator_summary},
            signal_breakdown=self._signal_breakdown(signal),
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
        news_item_count = WatchlistOrchestrationService._pluck(analysis, "news", "item_count")
        try:
            count = float(news_item_count)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(100.0, count * 10.0)), 2)

    @staticmethod
    def _signal_breakdown(signal: TickerSignalSnapshot) -> dict[str, object]:
        return {
            "attention_score": signal.attention_score,
            "macro_exposure_score": signal.macro_exposure_score,
            "industry_alignment_score": signal.industry_alignment_score,
            "ticker_sentiment_score": signal.ticker_sentiment_score,
            "technical_setup_score": signal.technical_setup_score,
            "catalyst_score": signal.catalyst_score,
            "expected_move_score": signal.expected_move_score,
            "execution_quality_score": signal.execution_quality_score,
            "mode": signal.diagnostics.get("mode"),
        }

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
