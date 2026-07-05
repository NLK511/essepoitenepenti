from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import CandidatePlanArtifactRecord, HistoricalMarketBarRecord, RecommendationPlanRecord, ReplayEligibilityRecord, ReplayPlanOutcomeRecord
from trade_proposer_app.services.plan_resolution_engine import PlanResolutionEngine
from trade_proposer_app.services.input_access import stable_hash
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
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
class CandidateOutcomeResolutionResult:
    status: str
    outcome_label: str
    resolution_source: str
    entry_triggered: bool | None
    evaluated_at: datetime
    bars_loaded_count: int
    local_only: bool
    remote_fetch_used: bool
    diagnostics: dict[str, object]
    plan_outcome: RecommendationPlanOutcome | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "outcome": self.outcome_label,
            "resolution_source": self.resolution_source,
            "entry_triggered": self.entry_triggered,
            "evaluated_at": self.evaluated_at.isoformat(),
            "bars_loaded_count": self.bars_loaded_count,
            "local_only": self.local_only,
            "remote_fetch_used": self.remote_fetch_used,
            "diagnostics": self.diagnostics,
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


class FrozenInputPlanRegenerationService:
    """Regenerate downstream plan geometry from a frozen stored plan artifact.

    This service intentionally does not fetch inputs, rerun cheap scan, or mutate live settings.
    It is the deterministic plan-framing core that later replay execution can pair with
    canonical outcome resolution.
    """

    def regenerate_levels(
        self,
        plan: RecommendationPlanRecord,
        *,
        tuning_config: Mapping[str, float],
    ) -> dict[str, object]:
        missing = [
            field
            for field, value in {
                "entry_price_low": plan.entry_price_low,
                "entry_price_high": plan.entry_price_high,
                "stop_loss": plan.stop_loss,
                "take_profit": plan.take_profit,
            }.items()
            if value is None
        ]
        if missing:
            return {
                "status": "incomplete",
                "rejection_reasons": [f"missing {field}" for field in missing],
                "source_plan_id": plan.id,
            }
        entry_price = (float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0
        evidence = loads_json_object(plan.evidence_summary_json)
        signal = loads_json_object(plan.signal_breakdown_json)
        setup_family = str(evidence.get("setup_family") or signal.get("setup_family") or "unknown")
        context_bias = str(evidence.get("transmission_context_bias") or signal.get("transmission_context_bias") or "")
        volatility_score = self._optional_float(evidence.get("volatility_score") or signal.get("volatility_score"))
        entry_low, entry_high, stop_loss, take_profit = family_adjusted_trade_levels(
            entry_price=entry_price,
            stop_loss=float(plan.stop_loss),
            take_profit=float(plan.take_profit),
            setup_family=setup_family,
            action=str(plan.action),
            transmission_context_bias=context_bias,
            volatility_score=volatility_score,
            tuning_config=dict(tuning_config),
        )
        rejection_reasons = self._geometry_rejection_reasons(str(plan.action), entry_low, entry_high, stop_loss, take_profit)
        return {
            "status": "invalid" if rejection_reasons else "ok",
            "source_plan_id": plan.id,
            "validation_depth": "frozen_input_plan_regeneration",
            "setup_family": setup_family,
            "entry_price_low": entry_low,
            "entry_price_high": entry_high,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rejection_reasons": rejection_reasons,
            "remote_fetch_used": False,
        }

    @staticmethod
    def _optional_float(value: object) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _geometry_rejection_reasons(action: str, entry_low: float, entry_high: float, stop_loss: float, take_profit: float) -> list[str]:
        midpoint = (entry_low + entry_high) / 2.0
        if midpoint <= 0:
            return ["entry price must be positive"]
        normalized_action = action.strip().lower()
        if normalized_action == "short":
            if stop_loss <= midpoint:
                return ["short stop must be above entry"]
            if take_profit >= midpoint:
                return ["short take-profit must be below entry"]
        else:
            if stop_loss >= midpoint:
                return ["long stop must be below entry"]
            if take_profit <= midpoint:
                return ["long take-profit must be above entry"]
        return []


class CandidatePlanArtifactService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_artifact(
        self,
        *,
        replay_batch_id: int,
        replay_slice_id: int,
        as_of: datetime,
        source_plan: RecommendationPlanRecord,
        source_replay_eligibility_id: int | None,
        candidate_config_hash: str,
        validation_depth: str,
        candidate_config: Mapping[str, object],
        regeneration: Mapping[str, object],
    ) -> CandidatePlanArtifactRecord:
        source_geometry = self.geometry_payload(source_plan)
        candidate_geometry = {
            "action": str(source_plan.action),
            "entry_price_low": self._float_or_none(regeneration.get("entry_price_low")) if regeneration.get("entry_price_low") is not None else source_plan.entry_price_low,
            "entry_price_high": self._float_or_none(regeneration.get("entry_price_high")) if regeneration.get("entry_price_high") is not None else source_plan.entry_price_high,
            "stop_loss": self._float_or_none(regeneration.get("stop_loss")) if regeneration.get("stop_loss") is not None else source_plan.stop_loss,
            "take_profit": self._float_or_none(regeneration.get("take_profit")) if regeneration.get("take_profit") is not None else source_plan.take_profit,
            "holding_period_days": source_plan.holding_period_days,
        }
        geometry_hash = stable_hash(candidate_geometry)
        source_geometry_hash = stable_hash(source_geometry)
        record = self.session.scalar(
            select(CandidatePlanArtifactRecord).where(
                CandidatePlanArtifactRecord.replay_slice_id == replay_slice_id,
                CandidatePlanArtifactRecord.source_baseline_plan_id == (source_plan.id or 0),
                CandidatePlanArtifactRecord.candidate_config_hash == candidate_config_hash,
            )
        )
        if record is None:
            record = CandidatePlanArtifactRecord(
                replay_batch_id=replay_batch_id,
                replay_slice_id=replay_slice_id,
                ticker=source_plan.ticker,
                as_of=as_of,
                source_baseline_plan_id=source_plan.id or 0,
                source_replay_eligibility_id=source_replay_eligibility_id,
                candidate_config_hash=candidate_config_hash,
            )
            self.session.add(record)
        record.replay_batch_id = replay_batch_id
        record.ticker = source_plan.ticker
        record.as_of = as_of
        record.source_replay_eligibility_id = source_replay_eligibility_id
        record.validation_depth = validation_depth
        record.candidate_config_json = self._json(candidate_config)
        record.source_plan_payload_json = self._json(self.plan_payload(source_plan))
        record.candidate_plan_payload_json = self._json({**self.plan_payload(source_plan), **candidate_geometry})
        record.action = str(candidate_geometry["action"])
        record.entry_price_low = candidate_geometry["entry_price_low"]  # type: ignore[assignment]
        record.entry_price_high = candidate_geometry["entry_price_high"]  # type: ignore[assignment]
        record.stop_loss = candidate_geometry["stop_loss"]  # type: ignore[assignment]
        record.take_profit = candidate_geometry["take_profit"]  # type: ignore[assignment]
        record.holding_period_days = candidate_geometry["holding_period_days"]  # type: ignore[assignment]
        record.geometry_hash = geometry_hash
        record.source_geometry_hash = source_geometry_hash
        record.regeneration_status = "invalid" if regeneration.get("status") == "invalid" else ("unchanged" if geometry_hash == source_geometry_hash else "regenerated")
        record.invalid_geometry_reasons_json = self._json(regeneration.get("rejection_reasons") or [])
        record.settings_snapshot_hash = stable_hash(candidate_config)
        record.code_version_hash = "runtime"
        record.diagnostics_json = self._json({
            "regeneration": dict(regeneration),
            "geometry_unchanged": geometry_hash == source_geometry_hash,
            "remote_fetch_used": False,
        })
        self.session.flush()
        return record

    @staticmethod
    def geometry_payload(plan: RecommendationPlanRecord) -> dict[str, object]:
        return {
            "action": plan.action,
            "entry_price_low": plan.entry_price_low,
            "entry_price_high": plan.entry_price_high,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "holding_period_days": plan.holding_period_days,
        }

    @staticmethod
    def plan_payload(plan: RecommendationPlanRecord) -> dict[str, object]:
        return {
            "id": plan.id,
            "ticker": plan.ticker,
            "horizon": plan.horizon,
            "action": plan.action,
            "status": plan.status,
            "confidence_percent": plan.confidence_percent,
            "entry_price_low": plan.entry_price_low,
            "entry_price_high": plan.entry_price_high,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "holding_period_days": plan.holding_period_days,
            "risk_reward_ratio": plan.risk_reward_ratio,
            "evidence_summary": loads_json_object(plan.evidence_summary_json),
            "signal_breakdown": loads_json_object(plan.signal_breakdown_json),
            "computed_at": plan.computed_at.isoformat() if isinstance(plan.computed_at, datetime) else None,
        }

    @staticmethod
    def _json(value: object) -> str:
        import json

        return json.dumps(value, sort_keys=True, default=str)

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None


class LocalCandidateOutcomeResolver:
    def __init__(self, session: Session, *, engine: PlanResolutionEngine | None = None) -> None:
        self.session = session
        self.engine = engine or PlanResolutionEngine()
        self._bar_cache: dict[tuple[str, str, int, str], tuple[pd.DataFrame, dict[str, object]]] = {}

    def resolve_artifact(self, artifact: CandidatePlanArtifactRecord, *, run_id: int | None = None) -> CandidateOutcomeResolutionResult:
        if artifact.regeneration_status == "invalid":
            import json

            try:
                invalid_reasons = json.loads(artifact.invalid_geometry_reasons_json or "[]")
            except (TypeError, ValueError):
                invalid_reasons = []
            diagnostics = {
                "invalid_geometry_reasons": invalid_reasons if isinstance(invalid_reasons, list) else [],
                "local_only": True,
                "remote_fetch_used": False,
            }
            now = datetime.now(timezone.utc)
            return CandidateOutcomeResolutionResult(
                status="invalid_geometry",
                outcome_label="unknown",
                resolution_source="unavailable",
                entry_triggered=None,
                evaluated_at=now,
                bars_loaded_count=0,
                local_only=True,
                remote_fetch_used=False,
                diagnostics=diagnostics,
            )
        plan = self._artifact_to_plan(artifact)
        horizon_days = int(artifact.holding_period_days or 7)
        bars, coverage = self.get_outcome_bars(artifact.ticker, artifact.as_of, horizon_days, resolution_source="daily")
        if bars.empty:
            now = datetime.now(timezone.utc)
            return CandidateOutcomeResolutionResult(
                status="missing_local_bars",
                outcome_label="unknown",
                resolution_source="unavailable",
                entry_triggered=None,
                evaluated_at=now,
                bars_loaded_count=0,
                local_only=True,
                remote_fetch_used=False,
                diagnostics={"bar_coverage": coverage, "local_only": True, "remote_fetch_used": False},
            )
        outcome = self.engine.evaluate_plan(plan, bars, intended_action=plan.action, run_id=run_id, as_of=artifact.as_of)
        diagnostics = {
            "bar_coverage": coverage,
            "resolver_version": "plan_resolution_engine_v1",
            "candidate_plan_artifact_id": artifact.id,
            "geometry_hash": artifact.geometry_hash,
            "source_geometry_hash": artifact.source_geometry_hash,
            "geometry_unchanged": artifact.geometry_hash == artifact.source_geometry_hash,
            "local_only": True,
            "remote_fetch_used": False,
        }
        return CandidateOutcomeResolutionResult(
            status=outcome.status,
            outcome_label=outcome.outcome,
            resolution_source="daily",
            entry_triggered=outcome.entry_touched,
            evaluated_at=outcome.evaluated_at,
            bars_loaded_count=len(bars),
            local_only=True,
            remote_fetch_used=False,
            diagnostics=diagnostics,
            plan_outcome=outcome,
        )

    def get_outcome_bars(self, ticker: str, as_of: datetime, horizon_days: int, *, resolution_source: str) -> tuple[pd.DataFrame, dict[str, object]]:
        normalized_as_of = self._normalize(as_of)
        key = (ticker.upper(), normalized_as_of.date().isoformat(), horizon_days, resolution_source)
        if key in self._bar_cache:
            return self._bar_cache[key]
        end_at = normalized_as_of + timedelta(days=max(1, horizon_days))
        rows = list(
            self.session.scalars(
                select(HistoricalMarketBarRecord)
                .where(
                    HistoricalMarketBarRecord.ticker == ticker.upper(),
                    HistoricalMarketBarRecord.timeframe == "1d",
                    HistoricalMarketBarRecord.bar_time > normalized_as_of,
                    HistoricalMarketBarRecord.bar_time <= end_at,
                )
                .order_by(HistoricalMarketBarRecord.bar_time.asc())
            ).all()
        )
        frame = pd.DataFrame(
            [
                {
                    "bar_time": self._normalize(row.bar_time),
                    "Open": row.open_price,
                    "High": row.high_price,
                    "Low": row.low_price,
                    "Close": row.close_price,
                    "Volume": row.volume,
                    "available_at": self._normalize(row.available_at or row.bar_time),
                }
                for row in rows
            ]
        )
        if not frame.empty:
            frame = frame.set_index("bar_time")
        coverage = {
            "ticker": ticker.upper(),
            "timeframe": "1d",
            "as_of": normalized_as_of.isoformat(),
            "window_end": end_at.isoformat(),
            "horizon_days": horizon_days,
            "loaded_bars": len(rows),
            "first_bar_time": self._normalize(rows[0].bar_time).isoformat() if rows else None,
            "last_bar_time": self._normalize(rows[-1].bar_time).isoformat() if rows else None,
            "sufficient": bool(rows),
            "remote_fetch_used": False,
        }
        self._bar_cache[key] = (frame, coverage)
        return frame, coverage

    def _artifact_to_plan(self, artifact: CandidatePlanArtifactRecord) -> RecommendationPlan:
        payload = loads_json_object(artifact.candidate_plan_payload_json)
        return RecommendationPlan(
            id=artifact.source_baseline_plan_id,
            ticker=artifact.ticker,
            horizon=str(payload.get("horizon") or "1w"),
            action=artifact.action,
            status=str(payload.get("status") or "ok"),
            confidence_percent=float(payload.get("confidence_percent") or 0.0),
            entry_price_low=artifact.entry_price_low,
            entry_price_high=artifact.entry_price_high,
            stop_loss=artifact.stop_loss,
            take_profit=artifact.take_profit,
            holding_period_days=artifact.holding_period_days,
            risk_reward_ratio=payload.get("risk_reward_ratio"),
            evidence_summary=payload.get("evidence_summary") if isinstance(payload.get("evidence_summary"), dict) else {},
            signal_breakdown=payload.get("signal_breakdown") if isinstance(payload.get("signal_breakdown"), dict) else {},
            computed_at=artifact.as_of,
        )

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


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
