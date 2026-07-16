from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

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
        price_history_cache, price_errors = self.evaluator._prepare_price_histories(  # noqa: SLF001
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
            ticker = (plan.ticker or "").strip().upper()
            daily_data = price_history_cache.get((ticker, False))
            intraday_data = price_history_cache.get((ticker, True))
            outcome, source_mode = self.evaluator._resolve_plan_outcome(  # noqa: SLF001
                plan,
                daily_data,
                intraday_data,
                run_id=row.run_id,
                as_of=resolution_as_of,
            )
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
            price_error_count=len(price_errors),
            eligibility_reclassification=reclassification,
            timing_seconds=timings,
        )

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
