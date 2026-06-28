from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.persistence.models import (
    HistoricalReplayBatchRecord,
    HistoricalReplaySliceRecord,
    RecommendationPlanRecord,
    ReplayEligibilityRecord,
    ReplayPlanOutcomeRecord,
)
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.replay_eligibility import ReplayEligibilityRepository
from trade_proposer_app.services.historical_bars_access import HistoricalBarsAccessService
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.input_access import normalize_input_access_policy, stable_hash
from trade_proposer_app.services.job_execution import JobExecutionService


@dataclass(frozen=True)
class ReplayEligibilityReclassificationSummary:
    replay_batch_id: int
    outcome_count: int
    reclassified_count: int
    before_tier_counts: dict[str, int]
    after_tier_counts: dict[str, int]
    before_eligible_count: int
    after_eligible_count: int
    blocker_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "replay_batch_id": self.replay_batch_id,
            "outcome_count": self.outcome_count,
            "reclassified_count": self.reclassified_count,
            "before_tier_counts": self.before_tier_counts,
            "after_tier_counts": self.after_tier_counts,
            "before_eligible_count": self.before_eligible_count,
            "after_eligible_count": self.after_eligible_count,
            "blocker_counts": self.blocker_counts,
        }


class ReplayEligibilityReclassificationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.eligibility = ReplayEligibilityRepository(session)
        self.market_data = HistoricalMarketDataService(HistoricalMarketDataRepository(session))

    def reclassify_batch(self, replay_batch_id: int, *, input_access_policy: str = "cache_only") -> ReplayEligibilityReclassificationSummary:
        policy = normalize_input_access_policy(input_access_policy, default="cache_only")
        before_rows = self.session.scalars(
            select(ReplayEligibilityRecord).where(ReplayEligibilityRecord.replay_batch_id == replay_batch_id)
        ).all()
        before_tiers = Counter(str(row.tier or "") for row in before_rows)
        before_eligible = sum(1 for row in before_rows if row.eligible_for_tuning)
        outcome_rows = self.session.scalars(
            select(ReplayPlanOutcomeRecord)
            .where(ReplayPlanOutcomeRecord.replay_batch_id == replay_batch_id)
            .order_by(ReplayPlanOutcomeRecord.id.asc())
        ).all()
        reclassified = 0
        blockers: Counter[str] = Counter()
        for outcome_row in outcome_rows:
            slice_row = self.session.get(HistoricalReplaySliceRecord, outcome_row.replay_slice_id)
            plan_row = self.session.get(RecommendationPlanRecord, outcome_row.recommendation_plan_id)
            if slice_row is None or plan_row is None:
                blockers["missing_slice_or_plan"] += 1
                continue
            input_summary = self._loads(slice_row.input_summary_json)
            ticker = str(plan_row.ticker or "").strip().upper()
            coverage_report = self._coverage_report_for_slice(input_summary, slice_row, input_access_policy=policy)
            coverage = self._coverage_for_ticker(coverage_report, ticker)
            signal_breakdown = self._loads(plan_row.signal_breakdown_json)
            replay_provenance = signal_breakdown.get("replay_provenance")
            if not isinstance(replay_provenance, dict):
                replay_provenance = self._fallback_replay_provenance(
                    input_summary=input_summary,
                    coverage_report=coverage_report,
                    outcome_row=outcome_row,
                )
                signal_breakdown["replay_provenance"] = replay_provenance
                plan_row.signal_breakdown_json = json.dumps(signal_breakdown, sort_keys=True, default=str)
            outcome_payload = self._loads(outcome_row.outcome_json)
            outcome_dict = {
                "id": outcome_row.id,
                "outcome": outcome_row.outcome,
                "status": outcome_row.status,
                "outcome_payload": outcome_payload,
            }
            classification = JobExecutionService._classify_replay_eligibility(
                ticker=ticker,
                coverage=coverage,
                resolution_source=str(outcome_row.resolution_source or ""),
                outcome=outcome_dict,
                candidate_config_hash=str(outcome_row.candidate_config_hash or ""),
                replay_provenance=replay_provenance if isinstance(replay_provenance, dict) else {},
            )
            for reason in classification["rejection_reasons"]:
                blockers[str(reason)] += 1
            self.eligibility.upsert_record(
                replay_batch_id=replay_batch_id,
                replay_slice_id=outcome_row.replay_slice_id,
                replay_plan_outcome_id=outcome_row.id,
                recommendation_plan_id=outcome_row.recommendation_plan_id,
                run_id=outcome_row.run_id,
                ticker=ticker,
                candidate_config_hash=str(outcome_row.candidate_config_hash or ""),
                tier=str(classification["tier"]),
                eligible_for_tuning=bool(classification["eligible_for_tuning"]),
                resolution_source=str(outcome_row.resolution_source or ""),
                outcome=str(outcome_row.outcome or ""),
                rejection_reasons=list(classification["rejection_reasons"]),
                diagnostics=dict(classification["diagnostics"]),
            )
            reclassified += 1
        self.session.commit()
        after_rows = self.session.scalars(
            select(ReplayEligibilityRecord).where(ReplayEligibilityRecord.replay_batch_id == replay_batch_id)
        ).all()
        after_tiers = Counter(str(row.tier or "") for row in after_rows)
        after_eligible = sum(1 for row in after_rows if row.eligible_for_tuning)
        return ReplayEligibilityReclassificationSummary(
            replay_batch_id=replay_batch_id,
            outcome_count=len(outcome_rows),
            reclassified_count=reclassified,
            before_tier_counts=dict(before_tiers),
            after_tier_counts=dict(after_tiers),
            before_eligible_count=before_eligible,
            after_eligible_count=after_eligible,
            blocker_counts=dict(blockers),
        )

    def _coverage_report_for_slice(
        self,
        input_summary: dict[str, object],
        slice_row: HistoricalReplaySliceRecord,
        *,
        input_access_policy: str,
    ) -> dict[str, object] | None:
        stored = input_summary.get("replay_coverage_report")
        if isinstance(stored, dict) and isinstance(stored.get("tickers"), list) and stored.get("tickers"):
            return stored
        batch = self.session.get(HistoricalReplayBatchRecord, slice_row.replay_batch_id)
        if batch is None:
            return stored if isinstance(stored, dict) else None
        tickers = self._loads_list(batch.tickers_json)
        if not tickers:
            return stored if isinstance(stored, dict) else None
        access = HistoricalBarsAccessService(self.market_data).replay_market_inputs(
            tickers=tickers,
            batch_start=batch.as_of_start,
            batch_end=batch.as_of_end,
            as_of=slice_row.as_of,
            policy=input_access_policy,
        )
        access.coverage_report["source"] = "cache_reclassification" if input_access_policy == "cache_only" else "reclassification_with_remote"
        return access.coverage_report

    @staticmethod
    def _fallback_replay_provenance(
        *,
        input_summary: dict[str, object],
        coverage_report: dict[str, object] | None,
        outcome_row: ReplayPlanOutcomeRecord,
    ) -> dict[str, object]:
        coverage = coverage_report if isinstance(coverage_report, dict) else {}
        return {
            "source": "historical_replay_reclassification",
            "replay_batch_id": outcome_row.replay_batch_id,
            "replay_slice_id": outcome_row.replay_slice_id,
            "as_of": input_summary.get("as_of"),
            "run_id": outcome_row.run_id,
            "code_version": os.environ.get("GIT_COMMIT") or os.environ.get("SOURCE_VERSION") or "unknown",
            "settings_hash": stable_hash({"weights_file_path": settings.weights_file_path}),
            "input_coverage_hash": str(coverage.get("input_coverage_hash") or stable_hash(coverage)),
            "input_coverage_summary": {
                "ticker_count": coverage.get("ticker_count"),
                "tier_counts": coverage.get("tier_counts"),
                "tier_a_ratio": coverage.get("tier_a_ratio"),
            },
        }

    @staticmethod
    def _loads(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _loads_list(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(loaded, list):
            return []
        return [str(item).strip().upper() for item in loaded if str(item).strip()]

    @staticmethod
    def _coverage_for_ticker(coverage: object, ticker: str) -> dict[str, object] | None:
        if not isinstance(coverage, dict):
            return None
        rows = coverage.get("tickers")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, dict) and str(row.get("ticker") or "").strip().upper() == ticker:
                return row
        return None
