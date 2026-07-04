from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import ReplayEligibilityRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.services.input_access import stable_hash
from trade_proposer_app.services.plan_generation_tuning_parameters import candidate_validation_depth
from trade_proposer_app.utils.json_payloads import loads_json_object


@dataclass(frozen=True, slots=True)
class CandidateReplayPlan:
    candidate_id: int | None
    rank: int | None
    config: dict[str, object]
    config_hash: str
    validation_depth: str
    validation_depth_reason: str
    replay_required: bool
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_rank": self.rank,
            "candidate_config_hash": self.config_hash,
            "validation_depth": self.validation_depth,
            "validation_depth_reason": self.validation_depth_reason,
            "replay_required": self.replay_required,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True, slots=True)
class EarlyStopDecision:
    should_stop: bool
    reason: str | None
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "should_stop": self.should_stop,
            "reason": self.reason,
            "diagnostics": self.diagnostics,
        }


class CandidateReplayPlanner:
    """Small, deterministic planner for candidate replay efficiency.

    The planner deduplicates candidates, attaches validation-depth metadata, and avoids
    routing supported rescore-only candidates into expensive full replay execution.
    """

    def plan(self, candidates: Iterable[Any]) -> list[CandidateReplayPlan]:
        seen_hashes: dict[str, int | None] = {}
        plans: list[CandidateReplayPlan] = []
        for candidate in candidates:
            config = dict(getattr(candidate, "config", {}) or {})
            config_hash = stable_hash(config)
            depth_payload = candidate_validation_depth(list(getattr(candidate, "changed_keys", []) or []))
            validation_depth = str(depth_payload["validation_depth"])
            candidate_id = getattr(candidate, "id", None)
            rank = getattr(candidate, "rank", None)
            if config_hash in seen_hashes:
                plans.append(
                    CandidateReplayPlan(
                        candidate_id=candidate_id,
                        rank=rank,
                        config=config,
                        config_hash=config_hash,
                        validation_depth=validation_depth,
                        validation_depth_reason=str(depth_payload["validation_depth_reason"]),
                        replay_required=False,
                        skip_reason=f"duplicate config of candidate {seen_hashes[config_hash]}",
                    )
                )
                continue
            seen_hashes[config_hash] = candidate_id
            replay_required = validation_depth != "rescore_only"
            skip_reason = "rescore-only candidate can reuse existing replay artifacts" if not replay_required else None
            plans.append(
                CandidateReplayPlan(
                    candidate_id=candidate_id,
                    rank=rank,
                    config=config,
                    config_hash=config_hash,
                    validation_depth=validation_depth,
                    validation_depth_reason=str(depth_payload["validation_depth_reason"]),
                    replay_required=replay_required,
                    skip_reason=skip_reason,
                )
            )
        return plans


class ReplayValidationAggregateService:
    """Aggregate replay outcomes once for UI/promotion gates without rescanning in callers."""

    WIN_OUTCOMES = {"win", "target_hit", "take_profit_hit"}
    LOSS_OUTCOMES = {"loss", "stop_loss_hit", "stopped"}

    def __init__(self, session: Session) -> None:
        self.session = session

    def aggregate_batch(self, replay_batch_id: int, *, candidate_config_hash: str | None = None) -> dict[str, object]:
        eligibility_query = select(ReplayEligibilityRecord).where(ReplayEligibilityRecord.replay_batch_id == replay_batch_id)
        outcome_query = select(ReplayPlanOutcomeRecord).where(ReplayPlanOutcomeRecord.replay_batch_id == replay_batch_id)
        if candidate_config_hash is not None:
            eligibility_query = eligibility_query.where(ReplayEligibilityRecord.candidate_config_hash == candidate_config_hash)
            outcome_query = outcome_query.where(ReplayPlanOutcomeRecord.candidate_config_hash == candidate_config_hash)
        eligibility_rows = list(self.session.scalars(eligibility_query).all())
        outcome_rows = list(self.session.scalars(outcome_query).all())
        tier_counts: dict[str, int] = {}
        ticker_counts: dict[str, int] = {}
        outcome_counts: dict[str, int] = {}
        setup_counts: dict[str, int] = {}
        for row in eligibility_rows:
            tier_counts[row.tier] = tier_counts.get(row.tier, 0) + 1
            ticker_counts[row.ticker] = ticker_counts.get(row.ticker, 0) + 1
            if row.outcome:
                outcome_counts[row.outcome] = outcome_counts.get(row.outcome, 0) + 1
            diagnostics = loads_json_object(row.diagnostics_json)
            setup = str(diagnostics.get("setup_family") or diagnostics.get("family") or "unknown")
            setup_counts[setup] = setup_counts.get(setup, 0) + 1
        resolved_count = sum(1 for row in outcome_rows if row.status == "resolved")
        win_count = sum(count for outcome, count in outcome_counts.items() if outcome in self.WIN_OUTCOMES)
        loss_count = sum(count for outcome, count in outcome_counts.items() if outcome in self.LOSS_OUTCOMES)
        tier_a_count = tier_counts.get("tier_a", 0)
        top_ticker_count = max(ticker_counts.values(), default=0)
        return {
            "replay_batch_id": replay_batch_id,
            "candidate_config_hash": candidate_config_hash or None,
            "eligibility_count": len(eligibility_rows),
            "outcome_count": len(outcome_rows),
            "resolved_count": resolved_count,
            "tier_counts": tier_counts,
            "outcome_counts": outcome_counts,
            "ticker_counts": ticker_counts,
            "setup_family_counts": setup_counts,
            "tier_a_count": tier_a_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_percent": round((win_count / max(1, win_count + loss_count)) * 100.0, 2) if win_count or loss_count else None,
            "top_ticker_concentration_percent": round((top_ticker_count / max(1, len(eligibility_rows))) * 100.0, 2),
        }


class CandidateEarlyStopPolicy:
    """Reject hopeless candidate replay early; never promotes from partial evidence."""

    def __init__(
        self,
        *,
        min_evidence_count: int = 50,
        min_tier_a_ratio: float = 0.35,
        max_top_ticker_concentration_percent: float = 35.0,
        max_loss_to_win_ratio: float = 4.0,
    ) -> None:
        self.min_evidence_count = min_evidence_count
        self.min_tier_a_ratio = min_tier_a_ratio
        self.max_top_ticker_concentration_percent = max_top_ticker_concentration_percent
        self.max_loss_to_win_ratio = max_loss_to_win_ratio

    def evaluate(self, aggregate: Mapping[str, object]) -> EarlyStopDecision:
        eligibility_count = int(aggregate.get("eligibility_count") or 0)
        if eligibility_count < self.min_evidence_count:
            return EarlyStopDecision(False, None, {"reason": "minimum evidence not reached", "eligibility_count": eligibility_count})
        tier_a_count = int(aggregate.get("tier_a_count") or 0)
        tier_a_ratio = tier_a_count / max(1, eligibility_count)
        top_ticker_concentration = float(aggregate.get("top_ticker_concentration_percent") or 0.0)
        win_count = int(aggregate.get("win_count") or 0)
        loss_count = int(aggregate.get("loss_count") or 0)
        loss_to_win_ratio = loss_count / max(1, win_count)
        diagnostics = {
            "eligibility_count": eligibility_count,
            "tier_a_ratio": round(tier_a_ratio, 4),
            "top_ticker_concentration_percent": top_ticker_concentration,
            "loss_to_win_ratio": round(loss_to_win_ratio, 4),
        }
        if tier_a_ratio < self.min_tier_a_ratio:
            return EarlyStopDecision(True, "tier_a_ratio_too_low", diagnostics)
        if top_ticker_concentration > self.max_top_ticker_concentration_percent:
            return EarlyStopDecision(True, "ticker_concentration_too_high", diagnostics)
        if loss_to_win_ratio > self.max_loss_to_win_ratio:
            return EarlyStopDecision(True, "loss_to_win_ratio_too_high", diagnostics)
        return EarlyStopDecision(False, None, diagnostics)


def replay_candidate_efficiency_summary(session: Session, replay_batch_id: int) -> dict[str, object]:
    aggregate = ReplayValidationAggregateService(session).aggregate_batch(replay_batch_id)
    early_stop = CandidateEarlyStopPolicy().evaluate(aggregate)
    return {"aggregate": aggregate, "early_stop": early_stop.to_dict()}
