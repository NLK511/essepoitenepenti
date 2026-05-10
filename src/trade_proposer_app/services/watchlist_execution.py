from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from trade_proposer_app.domain.models import RecommendationPlan, TickerSignalSnapshot, Watchlist

logger = logging.getLogger(__name__)


class WatchlistExecutionService:
    """Coordinate one full watchlist orchestration run."""

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def execute(
        self,
        watchlist: Watchlist,
        tickers: list[str],
        *,
        job_id: int | None = None,
        run_id: int | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, object]:
        o = self._orchestration
        normalized_tickers = self._normalize_tickers(tickers)
        if not normalized_tickers:
            raise ValueError("watchlist job has no effective tickers configured")

        logger.info(f"Starting watchlist orchestration for '{watchlist.name}' ({len(normalized_tickers)} tickers)")
        if as_of:
            logger.info(f"  Simulation mode active: as_of {as_of.isoformat()}")

        calibration_summary = o._load_calibration_summary()
        candidates = self._run_cheap_scans(watchlist, normalized_tickers, as_of=as_of)
        shortlist_evaluation = self._evaluate_shortlist(o, watchlist, candidates)
        shortlist = shortlist_evaluation["shortlist"]
        shortlist_map = {ticker: rank for rank, ticker in enumerate(shortlist, start=1)}

        stored_signals: list[TickerSignalSnapshot] = []
        stored_plans: list[RecommendationPlan] = []
        ticker_generation: list[dict[str, object]] = []
        warnings_found = False

        logger.info("  Processing candidates...")
        for candidate in candidates:
            shortlist_rank = shortlist_map.get(candidate.ticker)
            if shortlist_rank is None:
                warnings_found = self._process_non_shortlisted_candidate(
                    o,
                    watchlist,
                    candidate,
                    shortlist_evaluation=shortlist_evaluation,
                    calibration_summary=calibration_summary,
                    stored_signals=stored_signals,
                    ticker_generation=ticker_generation,
                    warnings_found=warnings_found,
                    job_id=job_id,
                    run_id=run_id,
                )
                continue

            warnings_found = self._process_shortlisted_candidate(
                o,
                watchlist,
                candidate,
                shortlist_rank=shortlist_rank,
                shortlist_evaluation=shortlist_evaluation,
                calibration_summary=calibration_summary,
                stored_signals=stored_signals,
                stored_plans=stored_plans,
                ticker_generation=ticker_generation,
                warnings_found=warnings_found,
                job_id=job_id,
                run_id=run_id,
                as_of=as_of,
            )

        result = self._build_result(
            watchlist,
            normalized_tickers=normalized_tickers,
            candidates=candidates,
            shortlist=shortlist,
            shortlist_evaluation=shortlist_evaluation,
            stored_signals=stored_signals,
            stored_plans=stored_plans,
            ticker_generation=ticker_generation,
            calibration_enabled=calibration_summary is not None,
            warnings_found=warnings_found,
            as_of=as_of,
        )
        logger.info(f"Orchestration complete: {len(stored_plans)} plans generated.")
        return result

    @staticmethod
    def _normalize_tickers(tickers: list[str]) -> list[str]:
        return [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]

    @staticmethod
    def _price_history(signal: TickerSignalSnapshot, key: str) -> object | None:
        return signal.diagnostics.get(key) if hasattr(signal.diagnostics, "get") else None

    def _run_cheap_scans(self, watchlist: Watchlist, tickers: list[str], *, as_of: datetime | None) -> list[Any]:
        o = self._orchestration
        logger.info("  Running cheap scans...")
        candidates = []
        for i, ticker in enumerate(tickers):
            if (i + 1) % 50 == 0:
                logger.info(f"    Cheap scan progress: {i + 1}/{len(tickers)}")
            candidates.append(o._run_cheap_scan(ticker, watchlist.default_horizon, as_of=as_of))
        return candidates

    @staticmethod
    def _evaluate_shortlist(o: Any, watchlist: Watchlist, candidates: list[Any]) -> dict[str, object]:
        logger.info("  Evaluating shortlist...")
        shortlist_evaluation = o._evaluate_shortlist(watchlist, candidates)
        logger.info(f"  Shortlist selected: {len(shortlist_evaluation['shortlist'])} tickers")
        return shortlist_evaluation

    def _process_non_shortlisted_candidate(
        self,
        o: Any,
        watchlist: Watchlist,
        candidate: Any,
        *,
        shortlist_evaluation: dict[str, object],
        calibration_summary: dict[str, object] | None,
        stored_signals: list[TickerSignalSnapshot],
        ticker_generation: list[dict[str, object]],
        warnings_found: bool,
        job_id: int | None,
        run_id: int | None,
    ) -> bool:
        decision = o._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
        signal = o._build_signal_snapshot(
            watchlist,
            candidate,
            deep_output=None,
            job_id=job_id,
            run_id=run_id,
            shortlisted=False,
            shortlist_rank=None,
            shortlist_decision=decision,
        )
        stored_signal = o.context_snapshots.create_ticker_signal_snapshot(signal)
        stored_signals.append(stored_signal)
        o._record_non_shortlisted_decision_sample(
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
                "cheap_scan_price_history": self._price_history(stored_signal, "cheap_scan_price_history"),
                "deep_analysis_price_history": None,
            }
        )
        return warnings_found or bool(candidate.warnings or candidate.error_message)

    def _process_shortlisted_candidate(
        self,
        o: Any,
        watchlist: Watchlist,
        candidate: Any,
        *,
        shortlist_rank: int,
        shortlist_evaluation: dict[str, object],
        calibration_summary: dict[str, object] | None,
        stored_signals: list[TickerSignalSnapshot],
        stored_plans: list[RecommendationPlan],
        ticker_generation: list[dict[str, object]],
        warnings_found: bool,
        job_id: int | None,
        run_id: int | None,
        as_of: datetime | None,
    ) -> bool:
        logger.info(f"    Running deep analysis for {candidate.ticker} (rank {shortlist_rank})...")
        deep_output, deep_error = o._run_deep_analysis(candidate.ticker, watchlist.default_horizon, as_of=as_of)
        decision = o._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
        signal = o._build_signal_snapshot(
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
        stored_signal = o.context_snapshots.create_ticker_signal_snapshot(signal)
        stored_signals.append(stored_signal)
        plan = o._build_plan_from_signal(
            watchlist,
            candidate,
            stored_signal,
            deep_output=deep_output,
            deep_error=deep_error,
            calibration_summary=calibration_summary,
            job_id=job_id,
            run_id=run_id,
        )
        stored_plan = o.recommendation_plans.create_plan(o._with_trade_policy_snapshot(plan))
        o._record_decision_sample(
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
                "cheap_scan_price_history": self._price_history(stored_signal, "cheap_scan_price_history"),
                "deep_analysis_price_history": self._price_history(stored_signal, "deep_analysis_price_history"),
            }
        )
        return warnings_found or bool(candidate.warnings or deep_error or plan.warnings)

    def _build_result(
        self,
        watchlist: Watchlist,
        *,
        normalized_tickers: list[str],
        candidates: list[Any],
        shortlist: list[str],
        shortlist_evaluation: dict[str, object],
        stored_signals: list[TickerSignalSnapshot],
        stored_plans: list[RecommendationPlan],
        ticker_generation: list[dict[str, object]],
        calibration_enabled: bool,
        warnings_found: bool,
        as_of: datetime | None,
    ) -> dict[str, object]:
        o = self._orchestration
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
            "shortlist_rejection_details": o._counted_shortlist_reason_details(shortlist_evaluation["rejection_counts"]),
            "calibration_enabled": calibration_enabled,
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
            "calibration_enabled": calibration_enabled,
            "ticker_signal_snapshot_ids": [item.id for item in stored_signals],
            "recommendation_plan_ids": [item.id for item in stored_plans],
        }
        return {
            "summary": summary,
            "artifact": artifact,
            "ticker_generation": ticker_generation,
            "warnings_found": warnings_found,
        }
