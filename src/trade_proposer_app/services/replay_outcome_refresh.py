from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import ReplayPlanOutcomeRecord
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
    ) -> ReplayOutcomeRefreshSummary:
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
        rows = self.session.scalars(query).all()
        before_status = Counter(str(row.status or "") for row in rows)
        before_outcomes = Counter(str(row.outcome or "") for row in rows)
        plans = []
        row_by_plan_id: dict[int, ReplayPlanOutcomeRecord] = {}
        for row in rows:
            try:
                plan = self.plans.get_plan(row.recommendation_plan_id)
            except ValueError:
                continue
            plans.append(plan)
            row_by_plan_id[plan.id or 0] = row
        resolution_as_of = self._resolve_as_of(
            plans,
            explicit_as_of=as_of,
            mode=resolution_as_of_mode,
        )
        price_history_cache, price_errors = self.evaluator._prepare_price_histories(  # noqa: SLF001
            plans,
            as_of=resolution_as_of,
            allow_remote_fetch=allow_remote_fetch,
        )
        refreshed = 0
        after_status: Counter[str] = Counter()
        after_outcomes: Counter[str] = Counter()
        for plan in plans:
            row = row_by_plan_id.get(plan.id or 0)
            if row is None:
                continue
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
            stored = self.replay_outcomes.upsert_outcome(
                replay_batch_id=row.replay_batch_id,
                replay_slice_id=row.replay_slice_id,
                run_id=row.run_id,
                recommendation_plan_id=row.recommendation_plan_id,
                candidate_config_hash=row.candidate_config_hash,
                resolution_source=source_mode,
                outcome=outcome,
            )
            refreshed += 1
            after_status[str(stored.get("status") or "")] += 1
            after_outcomes[str(stored.get("outcome") or "")] += 1
        reclassification = None
        if reclassify:
            reclassification = ReplayEligibilityReclassificationService(self.session).reclassify_batch(
                replay_batch_id,
                input_access_policy=policy,
            ).to_dict()
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
        )

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
