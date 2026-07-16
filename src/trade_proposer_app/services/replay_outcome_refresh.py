from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.persistence.models import RecommendationPlanRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.replay_plan_outcomes import ReplayPlanOutcomeRepository
from trade_proposer_app.services.input_access import input_policy_allows_remote_fetch, normalize_input_access_policy
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService
from trade_proposer_app.services.replay_bar_coverage import ReplayBarCoverageService
from trade_proposer_app.services.replay_eligibility_reclassification import ReplayEligibilityReclassificationService


@dataclass(frozen=True)
class ReplayOutcomeRefreshSummary:
    replay_batch_id: int
    selected_outcome_count: int
    refreshed_outcome_count: int
    before_status_counts: dict[str, int]
    after_status_counts: dict[str, int]
    before_outcome_counts: dict[str, int]
    after_outcome_counts: dict[str, int]
    price_error_count: int
    eligibility_reclassification: dict[str, object] | None
    timing_seconds: dict[str, float]
    price_history_diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "replay_batch_id": self.replay_batch_id,
            "selected_outcome_count": self.selected_outcome_count,
            "refreshed_outcome_count": self.refreshed_outcome_count,
            "before_status_counts": self.before_status_counts,
            "after_status_counts": self.after_status_counts,
            "before_outcome_counts": self.before_outcome_counts,
            "after_outcome_counts": self.after_outcome_counts,
            "price_error_count": self.price_error_count,
            "eligibility_reclassification": self.eligibility_reclassification,
            "timing_seconds": self.timing_seconds,
            "price_history_diagnostics": self.price_history_diagnostics,
        }


class ReplayOutcomeRefreshService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.plans = RecommendationPlanRepository(session)
        self.replay_outcomes = ReplayPlanOutcomeRepository(session)
        self.evaluator = RecommendationPlanEvaluationService(session)

    def refresh_batch(
        self,
        replay_batch_id: int,
        *,
        as_of: datetime | None = None,
        include_resolved: bool = False,
        reclassify: bool = True,
        input_access_policy: str = "cache_only",
        resolution_sources: set[str] | None = None,
        resolution_as_of_mode: str = "plan_horizon",
        limit: int | None = None,
        profile: bool = False,
        bulk_chunk_size: int = 500,
    ) -> ReplayOutcomeRefreshSummary:
        timings: dict[str, float] = {}

        def timed(stage: str, started_at: float) -> None:
            if profile:
                timings[stage] = round(time.perf_counter() - started_at, 6)

        stage_started = time.perf_counter()
        policy = normalize_input_access_policy(input_access_policy, default="cache_only")
        allow_remote_fetch = input_policy_allows_remote_fetch(policy)
        source_filter = {str(item).strip() for item in resolution_sources or set() if str(item).strip()}
        query = (
            select(ReplayPlanOutcomeRecord)
            .where(ReplayPlanOutcomeRecord.replay_batch_id == replay_batch_id)
            .order_by(ReplayPlanOutcomeRecord.id.asc())
        )
        if not include_resolved:
            query = query.where(ReplayPlanOutcomeRecord.status != "resolved")
        if source_filter:
            query = query.where(ReplayPlanOutcomeRecord.resolution_source.in_(source_filter))
        if limit is not None:
            query = query.limit(max(1, int(limit)))
        rows = self.session.scalars(query).all()
        timed("row_selection", stage_started)
        stage_started = time.perf_counter()
        before_status = Counter(str(row.status or "") for row in rows)
        before_outcomes = Counter(str(row.outcome or "") for row in rows)
        plans_by_id = self._load_refresh_plans(rows)
        plan_row_pairs = [
            (plans_by_id[row.recommendation_plan_id], row)
            for row in rows
            if row.recommendation_plan_id in plans_by_id
        ]
        plans = [plan for plan, _ in plan_row_pairs]
        timed("plan_loading", stage_started)
        stage_started = time.perf_counter()
        resolution_as_of = self._resolve_as_of(
            plans,
            explicit_as_of=as_of,
            mode=resolution_as_of_mode,
        )
        timed("as_of_resolution", stage_started)
        stage_started = time.perf_counter()
        price_inputs = self._prepare_replay_price_inputs(
            plans,
            as_of=resolution_as_of,
            allow_remote_fetch=allow_remote_fetch,
        )
        timed("price_history_preparation", stage_started)
        stage_started = time.perf_counter()
        refreshed = 0
        after_status: Counter[str] = Counter()
        after_outcomes: Counter[str] = Counter()
        bulk_items: list[dict[str, object]] = []
        for plan, row in plan_row_pairs:
            precomputed = price_inputs["precomputed_outcomes"].get(plan.id or 0)
            if precomputed is None:
                ticker = (plan.ticker or "").strip().upper()
                daily_data = price_inputs["daily_cache"].get(ticker)
                intraday_data = price_inputs["intraday_cache"].get(ticker)
                outcome, source_mode = self.evaluator._resolve_plan_outcome(  # noqa: SLF001
                    plan,
                    daily_data,
                    intraday_data,
                    run_id=row.run_id,
                    as_of=resolution_as_of,
                )
            else:
                outcome, source_mode = precomputed
                outcome = outcome.model_copy(update={"run_id": row.run_id})
            bulk_items.append(
                {
                    "replay_batch_id": row.replay_batch_id,
                    "replay_slice_id": row.replay_slice_id,
                    "run_id": row.run_id,
                    "recommendation_plan_id": row.recommendation_plan_id,
                    "candidate_config_hash": row.candidate_config_hash,
                    "resolution_source": source_mode,
                    "outcome": outcome,
                }
            )
            refreshed += 1
            after_status[str(outcome.status or "")] += 1
            after_outcomes[str(outcome.outcome or "")] += 1
        timed("outcome_resolution", stage_started)
        stage_started = time.perf_counter()
        chunk_size = max(1, int(bulk_chunk_size))
        for index in range(0, len(bulk_items), chunk_size):
            self.replay_outcomes.bulk_upsert_outcomes(bulk_items[index : index + chunk_size])
        timed("outcome_persistence", stage_started)
        reclassification = None
        if reclassify:
            stage_started = time.perf_counter()
            reclassification = ReplayEligibilityReclassificationService(self.session).reclassify_batch(
                replay_batch_id,
                input_access_policy=policy,
            ).to_dict()
            timed("eligibility_reclassification", stage_started)
        return ReplayOutcomeRefreshSummary(
            replay_batch_id=replay_batch_id,
            selected_outcome_count=len(rows),
            refreshed_outcome_count=refreshed,
            before_status_counts=dict(before_status),
            after_status_counts=dict(after_status),
            before_outcome_counts=dict(before_outcomes),
            after_outcome_counts=dict(after_outcomes),
            price_error_count=len(price_inputs["errors"]),
            eligibility_reclassification=reclassification,
            timing_seconds=timings,
            price_history_diagnostics=price_inputs["diagnostics"],
        )

    def _prepare_replay_price_inputs(
        self,
        plans: list[RecommendationPlan],
        *,
        as_of: datetime,
        allow_remote_fetch: bool,
    ) -> dict[str, object]:
        groups = self.evaluator._group_by_ticker(plans)  # noqa: SLF001
        daily_cache: dict[str, object] = {}
        intraday_cache: dict[str, object] = {}
        precomputed: dict[int, tuple[object, str]] = {}
        intraday_required: list[RecommendationPlan] = []
        errors: list[str] = []
        diagnostics: dict[str, object] = {
            "ticker_count": len(groups),
            "plan_count": len(plans),
            "daily_loaded_ticker_count": 0,
            "intraday_loaded_ticker_count": 0,
            "daily_prefilter_plan_count": 0,
            "intraday_required_plan_count": 0,
            "non_trade_plan_count": 0,
        }
        for ticker, grouped_plans in groups.items():
            trade_like = [
                plan
                for plan in grouped_plans
                if plan.action in {"long", "short"} or self.evaluator._phantom_intended_action(plan) is not None  # noqa: SLF001
            ]
            trade_like_ids = {id(plan) for plan in trade_like}
            for plan in grouped_plans:
                if id(plan) not in trade_like_ids:
                    outcome, source = self.evaluator._resolve_plan_outcome(  # noqa: SLF001
                        plan,
                        None,
                        None,
                        run_id=None,
                        as_of=as_of,
                    )
                    precomputed[plan.id or 0] = (outcome, source)
                    diagnostics["non_trade_plan_count"] = int(diagnostics["non_trade_plan_count"]) + 1
            if not trade_like:
                continue
            normalized_times = [
                normalized
                for plan in trade_like
                if (normalized := self.evaluator._normalize_datetime(plan.computed_at)) is not None  # noqa: SLF001
            ]
            if not normalized_times:
                intraday_required.extend(trade_like)
                continue
            start_time = min(normalized_times)
            start_time = start_time - timedelta(days=2)
            daily_data = self.evaluator._load_price_history(  # noqa: SLF001
                ticker,
                start_time,
                as_of,
                intraday_only=False,
                require_full_coverage=True,
                plan_ids=[plan.id for plan in trade_like if plan.id is not None],
                allow_remote_fetch=allow_remote_fetch,
            )
            daily_cache[ticker] = daily_data.sort_index() if daily_data is not None and not daily_data.empty else None
            if daily_cache[ticker] is None:
                errors.append(f"{ticker}: daily price history is unavailable")
                intraday_required.extend(trade_like)
                continue
            diagnostics["daily_loaded_ticker_count"] = int(diagnostics["daily_loaded_ticker_count"]) + 1
            for plan in trade_like:
                daily_outcome = self.evaluator._evaluate_plan(  # noqa: SLF001
                    plan,
                    daily_cache[ticker],
                    intended_action=self.evaluator._phantom_intended_action(plan),  # noqa: SLF001
                    run_id=None,
                    as_of=as_of,
                    intraday_only=False,
                )
                if daily_outcome.outcome in {"no_entry", "open", "phantom_no_entry", "phantom_pending"}:
                    precomputed[plan.id or 0] = (
                        self.evaluator._finalize_outcome(plan, daily_outcome, as_of=as_of),  # noqa: SLF001
                        "daily_prefilter",
                    )
                    diagnostics["daily_prefilter_plan_count"] = int(diagnostics["daily_prefilter_plan_count"]) + 1
                else:
                    intraday_required.append(plan)
        diagnostics["intraday_required_plan_count"] = len(intraday_required)
        for ticker, grouped_plans in self.evaluator._group_by_ticker(intraday_required).items():  # noqa: SLF001
            normalized_times = [
                self.evaluator._normalize_datetime(plan.computed_at)  # noqa: SLF001
                for plan in grouped_plans
                if self.evaluator._normalize_datetime(plan.computed_at) is not None  # noqa: SLF001
            ]
            if not normalized_times:
                continue
            start_time = min(normalized_times) - timedelta(days=2)
            intraday_data = self.evaluator._load_price_history(  # noqa: SLF001
                ticker,
                start_time,
                as_of,
                intraday_only=True,
                require_full_coverage=True,
                plan_ids=[plan.id for plan in grouped_plans if plan.id is not None],
                allow_remote_fetch=allow_remote_fetch,
            )
            intraday_cache[ticker] = intraday_data.sort_index() if intraday_data is not None and not intraday_data.empty else None
            if intraday_cache[ticker] is None:
                errors.append(f"{ticker}: intraday price history is unavailable")
            else:
                diagnostics["intraday_loaded_ticker_count"] = int(diagnostics["intraday_loaded_ticker_count"]) + 1
        diagnostics["price_error_count"] = len(errors)
        return {
            "daily_cache": daily_cache,
            "intraday_cache": intraday_cache,
            "precomputed_outcomes": precomputed,
            "errors": errors,
            "diagnostics": diagnostics,
        }

    def _load_refresh_plans(self, rows: list[ReplayPlanOutcomeRecord]) -> dict[int, RecommendationPlan]:
        plan_ids = sorted({row.recommendation_plan_id for row in rows})
        if not plan_ids:
            return {}
        records = self.session.scalars(
            select(RecommendationPlanRecord).where(RecommendationPlanRecord.id.in_(plan_ids))
        ).all()
        return {record.id: self._plan_from_record(record) for record in records if record.id is not None}

    @classmethod
    def _plan_from_record(cls, record: RecommendationPlanRecord) -> RecommendationPlan:
        return RecommendationPlan(
            id=record.id,
            ticker=record.ticker,
            horizon=record.horizon,
            action=record.action,
            status=record.status,
            confidence_percent=record.confidence_percent,
            entry_price_low=record.entry_price_low,
            entry_price_high=record.entry_price_high,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            holding_period_days=record.holding_period_days,
            risk_reward_ratio=record.risk_reward_ratio,
            thesis_summary=record.thesis_summary,
            rationale_summary=record.rationale_summary,
            risks=cls._load_json(record.risks_json, []),
            warnings=cls._load_json(record.warnings_json, []),
            missing_inputs=cls._load_json(record.missing_inputs_json, []),
            evidence_summary=cls._load_json(record.evidence_summary_json, {}),
            signal_breakdown=cls._load_json(record.signal_breakdown_json, {}),
            trade_policy_id=record.trade_policy_id,
            trade_policy_snapshot=cls._load_json(record.trade_policy_snapshot_json, {}),
            computed_at=record.computed_at,
            run_id=record.run_id,
            job_id=record.job_id,
            watchlist_id=record.watchlist_id,
            ticker_signal_snapshot_id=record.ticker_signal_snapshot_id,
        )

    @staticmethod
    def _load_json(value: str | None, default: object) -> object:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _resolve_as_of(
        self,
        plans: list[object],
        *,
        explicit_as_of: datetime | None,
        mode: str,
    ) -> datetime:
        if explicit_as_of is not None:
            return self._normalize(explicit_as_of)
        normalized_mode = str(mode or "now").strip()
        if normalized_mode == "latest_complete_cached_session":
            tickers = [str(getattr(plan, "ticker", "") or "").strip().upper() for plan in plans]
            cached = ReplayBarCoverageService(self.session).latest_complete_cached_session_as_of(tickers)
            if cached is not None:
                return cached
        if normalized_mode == "plan_horizon":
            coverage = ReplayBarCoverageService(self.session)
            cutoffs = [coverage.plan_horizon_cutoff(plan) for plan in plans]
            cached = coverage.latest_complete_cached_session_as_of(
                [str(getattr(plan, "ticker", "") or "").strip().upper() for plan in plans]
            )
            if cutoffs and cached is not None:
                return min(max(cutoffs), cached)
            if cutoffs:
                return max(cutoffs)
        return datetime.now(timezone.utc)
