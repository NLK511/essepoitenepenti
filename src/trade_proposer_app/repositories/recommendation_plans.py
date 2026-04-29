import json
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerOrderExecution, KeyLabelDetail, RecommendationPlan, RecommendationPlanOutcome, RecommendationPlanStats
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository

from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.outcomes = RecommendationOutcomeRepository(session)
        self.broker_orders = BrokerOrderExecutionRepository(session)
        self.taxonomy_service = TickerTaxonomyService()

    def create_plan(self, plan: RecommendationPlan) -> RecommendationPlan:
        record = RecommendationPlanRecord(
            ticker=plan.ticker,
            horizon=plan.horizon.value,
            action=plan.action,
            status=plan.status,
            confidence_percent=plan.confidence_percent,
            entry_price_low=plan.entry_price_low,
            entry_price_high=plan.entry_price_high,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            holding_period_days=plan.holding_period_days,
            risk_reward_ratio=plan.risk_reward_ratio,
            thesis_summary=plan.thesis_summary,
            rationale_summary=plan.rationale_summary,
            risks_json=self._dump(plan.risks),
            warnings_json=self._dump(plan.warnings),
            missing_inputs_json=self._dump(plan.missing_inputs),
            evidence_summary_json=self._dump(plan.evidence_summary),
            signal_breakdown_json=self._dump(plan.signal_breakdown),
            computed_at=self._normalize_datetime(plan.computed_at),
            watchlist_id=plan.watchlist_id,
            ticker_signal_snapshot_id=plan.ticker_signal_snapshot_id,
            job_id=plan.job_id,
            run_id=plan.run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def get_plan(self, plan_id: int) -> RecommendationPlan:
        record = self.session.get(RecommendationPlanRecord, plan_id)
        if record is None:
            raise ValueError(f"Recommendation plan {plan_id} not found")
        plan = self._to_model(record)
        outcome_map = self.outcomes.get_outcomes_by_plan_ids([record.id])
        broker_order_map = self.broker_orders.get_latest_by_plan_ids([record.id])
        self._attach_execution_context(plan, latest_outcome=outcome_map.get(record.id), broker_order=broker_order_map.get(record.id))
        return plan

    def _base_plan_query(
        self,
        ticker: str | None = None,
        action: str | None = None,
        run_id: int | None = None,
        plan_id: int | None = None,
        computed_after: datetime | None = None,
        computed_before: datetime | None = None,
    ):
        query = select(RecommendationPlanRecord)
        if ticker:
            query = query.where(RecommendationPlanRecord.ticker == ticker.upper())
        if action:
            query = query.where(RecommendationPlanRecord.action == action)
        if run_id is not None:
            query = query.where(RecommendationPlanRecord.run_id == run_id)
        if plan_id is not None:
            query = query.where(RecommendationPlanRecord.id == plan_id)
        if computed_after is not None:
            query = query.where(RecommendationPlanRecord.computed_at >= computed_after)
        if computed_before is not None:
            query = query.where(RecommendationPlanRecord.computed_at <= computed_before)
        return query

    def _record_setup_family(self, record: RecommendationPlanRecord) -> str:
        signal_breakdown = self._load(record.signal_breakdown_json, {})
        if not isinstance(signal_breakdown, dict):
            return ""
        return str(signal_breakdown.get("setup_family") or "").strip().lower()

    def _record_shortlisted(self, record: RecommendationPlanRecord) -> bool:
        signal_breakdown = self._load(record.signal_breakdown_json, {})
        if isinstance(signal_breakdown, dict) and isinstance(signal_breakdown.get("shortlisted"), bool):
            return bool(signal_breakdown.get("shortlisted"))
        evidence_summary = self._load(record.evidence_summary_json, {})
        if isinstance(evidence_summary, dict):
            action_reason = str(evidence_summary.get("action_reason") or "").strip().lower()
            if action_reason == "not_shortlisted":
                return False
        return True

    def count_plans(
        self,
        ticker: str | None = None,
        action: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        plan_id: int | None = None,
        resolved: str | None = None,
        outcome: str | None = None,
        shortlisted: bool | None = None,
        entry_touched: bool | None = None,
        near_entry_miss: bool | None = None,
        direction_worked_without_entry: bool | None = None,
        computed_after: datetime | None = None,
        computed_before: datetime | None = None,
    ) -> int:
        query = self._base_plan_query(ticker=ticker, action=action, run_id=run_id, plan_id=plan_id, computed_after=computed_after, computed_before=computed_before)
        if setup_family or resolved or outcome or shortlisted is not None or entry_touched is not None or near_entry_miss is not None or direction_worked_without_entry is not None:
            rows = self.session.scalars(query).all()
            plan_ids = [row.id for row in rows if row.id is not None]
            outcome_map = self.outcomes.get_outcomes_by_plan_ids(plan_ids)
            broker_order_map = self.broker_orders.get_latest_by_plan_ids(plan_ids)
            normalized_setup_family = setup_family.strip().lower() if setup_family else None
            normalized_resolved = (resolved or "").strip().lower() or None
            normalized_outcome = (outcome or "").strip().lower() or None
            return sum(
                1
                for row in rows
                if self._matches_filters(
                    row,
                    outcome_map=outcome_map,
                    broker_order_map=broker_order_map,
                    setup_family=normalized_setup_family,
                    resolved=normalized_resolved,
                    outcome=normalized_outcome,
                    shortlisted=shortlisted,
                    entry_touched=entry_touched,
                    near_entry_miss=near_entry_miss,
                    direction_worked_without_entry=direction_worked_without_entry,
                )
            )
        count_query = select(func.count()).select_from(query.subquery())
        return int(self.session.scalar(count_query) or 0)

    def list_plans(
        self,
        ticker: str | None = None,
        action: str | None = None,
        limit: int = 50,
        offset: int = 0,
        run_id: int | None = None,
        setup_family: str | None = None,
        plan_id: int | None = None,
        resolved: str | None = None,
        outcome: str | None = None,
        shortlisted: bool | None = None,
        entry_touched: bool | None = None,
        near_entry_miss: bool | None = None,
        direction_worked_without_entry: bool | None = None,
        computed_after: datetime | None = None,
        computed_before: datetime | None = None,
    ) -> list[RecommendationPlan]:
        normalized_limit = max(1, limit)
        normalized_offset = max(0, offset)
        query = self._base_plan_query(ticker=ticker, action=action, run_id=run_id, plan_id=plan_id, computed_after=computed_after, computed_before=computed_before)
        normalized_setup_family = setup_family.strip().lower() if setup_family else None
        normalized_resolved = (resolved or "").strip().lower() or None
        normalized_outcome = (outcome or "").strip().lower() or None
        if normalized_setup_family or normalized_resolved or normalized_outcome or shortlisted is not None or entry_touched is not None or near_entry_miss is not None or direction_worked_without_entry is not None:
            rows = self.session.scalars(query.order_by(RecommendationPlanRecord.computed_at.desc())).all()
            plan_ids = [row.id for row in rows if row.id is not None]
            outcome_map = self.outcomes.get_outcomes_by_plan_ids(plan_ids)
            broker_order_map = self.broker_orders.get_latest_by_plan_ids(plan_ids)
            filtered_rows = [
                row
                for row in rows
                if self._matches_filters(
                    row,
                    outcome_map=outcome_map,
                    broker_order_map=broker_order_map,
                    setup_family=normalized_setup_family,
                    resolved=normalized_resolved,
                    outcome=normalized_outcome,
                    shortlisted=shortlisted,
                    entry_touched=entry_touched,
                    near_entry_miss=near_entry_miss,
                    direction_worked_without_entry=direction_worked_without_entry,
                )
            ]
            rows = filtered_rows[normalized_offset : normalized_offset + normalized_limit]
            plans = [self._to_model(row) for row in rows]
        else:
            rows = self.session.scalars(
                query.order_by(RecommendationPlanRecord.computed_at.desc()).offset(normalized_offset).limit(normalized_limit)
            ).all()
            plans = [self._to_model(row) for row in rows]
            outcome_map = self.outcomes.get_outcomes_by_plan_ids([plan.id for plan in plans if plan.id is not None])
            broker_order_map = self.broker_orders.get_latest_by_plan_ids([plan.id for plan in plans if plan.id is not None])
        for plan in plans:
            if plan.id is not None:
                self._attach_execution_context(
                    plan,
                    latest_outcome=outcome_map.get(plan.id),
                    broker_order=broker_order_map.get(plan.id),
                )
        return plans

    def _matches_filters(
        self,
        record: RecommendationPlanRecord,
        *,
        outcome_map: dict[int, object],
        broker_order_map: dict[int, BrokerOrderExecution],
        setup_family: str | None,
        resolved: str | None,
        outcome: str | None,
        shortlisted: bool | None,
        entry_touched: bool | None,
        near_entry_miss: bool | None,
        direction_worked_without_entry: bool | None,
    ) -> bool:
        if setup_family and self._record_setup_family(record) != setup_family:
            return False
        if shortlisted is not None and self._record_shortlisted(record) is not shortlisted:
            return False
        latest_outcome = outcome_map.get(record.id or 0)
        effective_outcome, effective_resolved = self._effective_filter_state(
            latest_outcome=latest_outcome,
            broker_order=broker_order_map.get(record.id or 0),
        )
        if resolved:
            if resolved == "resolved" and not effective_resolved:
                return False
            if resolved == "unresolved" and effective_resolved:
                return False
        if outcome and effective_outcome != outcome:
            return False
        if entry_touched is not None and (latest_outcome is None or getattr(latest_outcome, "entry_touched", None) is not entry_touched):
            return False
        if near_entry_miss is not None and (latest_outcome is None or getattr(latest_outcome, "near_entry_miss", None) is not near_entry_miss):
            return False
        if direction_worked_without_entry is not None and (latest_outcome is None or getattr(latest_outcome, "direction_worked_without_entry", None) is not direction_worked_without_entry):
            return False
        return True

    def _effective_filter_state(
        self,
        *,
        latest_outcome: object | None,
        broker_order: BrokerOrderExecution | None,
    ) -> tuple[str | None, bool]:
        if broker_order is not None and self._broker_evaluation_source(broker_order) == "broker":
            broker_label = self._broker_evaluation_label(broker_order)
            return broker_label, broker_label in {"win", "loss"}
        if latest_outcome is None:
            return None, False
        outcome = str(getattr(latest_outcome, "outcome", "") or "").strip().lower() or None
        return outcome, bool(getattr(latest_outcome, "status", None) == "resolved")

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @classmethod
    def _dump(cls, value: Any) -> str:
        return json.dumps(value, default=cls._json_default)

    @staticmethod
    def _load(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _transmission_bias_detail(self, value: object) -> KeyLabelDetail | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_transmission_bias_definition(value)
        key = str(definition.get("key", value)).strip() or value.strip()
        label = str(definition.get("label", value)).strip() or value.strip()
        return KeyLabelDetail(key=key, label=label)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _attach_execution_context(
        self,
        plan: RecommendationPlan,
        *,
        latest_outcome: RecommendationPlanOutcome | None,
        broker_order: BrokerOrderExecution | None,
    ) -> None:
        plan.latest_outcome = latest_outcome
        if broker_order is not None:
            plan.broker_order_id = broker_order.broker_order_id
            plan.broker_order_status = broker_order.status
            plan.broker_order_updated_at = broker_order.updated_at
            broker_source = self._broker_evaluation_source(broker_order)
            if broker_source == "broker":
                plan.effective_evaluation_source = "broker"
                plan.effective_evaluation = self._broker_evaluation_label(broker_order)
                plan.effective_evaluation_detail = self._broker_evaluation_detail(broker_order)
                return
            if broker_source == "simulated" and plan.latest_outcome is not None:
                plan.effective_evaluation_source = "simulated"
                plan.effective_evaluation = plan.latest_outcome.outcome
                plan.effective_evaluation_detail = f"{self._broker_evaluation_detail(broker_order)}; simulated outcome used as fallback"
                return
            plan.effective_evaluation_source = "missing"
            plan.effective_evaluation = None
            plan.effective_evaluation_detail = self._broker_evaluation_detail(broker_order)
            return
        if plan.latest_outcome is not None:
            plan.effective_evaluation_source = "simulated"
            plan.effective_evaluation = plan.latest_outcome.outcome
            plan.effective_evaluation_detail = plan.latest_outcome.notes
        else:
            plan.effective_evaluation_source = "missing"
            plan.effective_evaluation = None
            plan.effective_evaluation_detail = "broker evaluation unavailable"

    @staticmethod
    def _broker_evaluation_source(order: BrokerOrderExecution) -> str:
        status = str(order.status or "").strip().lower()
        if status in {"new", "submitted", "accepted", "partially_filled", "open", "closed_win", "closed_loss"}:
            return "broker"
        if status in {"canceled", "expired", "rejected", "failed"}:
            return "simulated"
        return "missing"

    @staticmethod
    def _broker_evaluation_label(order: BrokerOrderExecution) -> str:
        status = str(order.status or "").strip().lower()
        if status in {"new", "submitted", "accepted", "partially_filled"}:
            return "pending"
        if status == "open":
            return "entry"
        if status == "closed_win":
            return "win"
        if status == "closed_loss":
            return "loss"
        return "missing"

    @staticmethod
    def _broker_evaluation_detail(order: BrokerOrderExecution) -> str:
        status = str(order.status or "").strip().lower() or "unknown"
        if status == "open":
            return "broker entry filled; exit still open"
        if status == "closed_win":
            return "broker take-profit filled"
        if status == "closed_loss":
            return "broker stop-loss filled"
        if status in {"new", "submitted", "accepted", "partially_filled"}:
            return f"broker order {status}"
        if status in {"canceled", "expired", "rejected", "failed"}:
            return f"broker order {status}"
        return f"broker order {status}"

    def summarize_stats(
        self,
        *,
        ticker: str | None = None,
        action: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        plan_id: int | None = None,
        resolved: str | None = None,
        outcome: str | None = None,
        shortlisted: bool | None = None,
        entry_touched: bool | None = None,
        near_entry_miss: bool | None = None,
        direction_worked_without_entry: bool | None = None,
        computed_after: datetime | None = None,
        computed_before: datetime | None = None,
        window: str = "all",
    ) -> RecommendationPlanStats:
        normalized_window = (window or "all").strip().lower() or "all"
        window_start = self._window_start(normalized_window)
        effective_after = computed_after if computed_after is not None else window_start
        window_label = "custom" if computed_after is not None or computed_before is not None else normalized_window
        rows = self.session.scalars(
            self._base_plan_query(
                ticker=ticker,
                action=action,
                run_id=run_id,
                plan_id=plan_id,
                computed_after=effective_after,
                computed_before=computed_before,
            ).order_by(RecommendationPlanRecord.computed_at.desc())
        ).all()
        plan_ids = [row.id for row in rows if row.id is not None]
        outcome_map = self.outcomes.get_outcomes_by_plan_ids(plan_ids)
        broker_order_map = self.broker_orders.get_latest_by_plan_ids(plan_ids)
        normalized_setup_family = setup_family.strip().lower() if setup_family else None
        normalized_resolved = (resolved or "").strip().lower() or None
        normalized_outcome = (outcome or "").strip().lower() or None
        filtered_rows = [
            row
            for row in rows
            if self._matches_filters(
                row,
                outcome_map=outcome_map,
                broker_order_map=broker_order_map,
                setup_family=normalized_setup_family,
                resolved=normalized_resolved,
                outcome=normalized_outcome,
                shortlisted=shortlisted,
                entry_touched=entry_touched,
                near_entry_miss=near_entry_miss,
                direction_worked_without_entry=direction_worked_without_entry,
            )
        ]
        filtered_effective_states = [
            self._effective_filter_state(
                latest_outcome=outcome_map.get(row.id or 0),
                broker_order=broker_order_map.get(row.id or 0),
            )
            for row in filtered_rows
        ]
        open_plans = sum(1 for _, is_resolved in filtered_effective_states if not is_resolved)
        expired_plans = sum(1 for effective_outcome, _ in filtered_effective_states if effective_outcome == "expired")
        wins = sum(1 for effective_outcome, _ in filtered_effective_states if effective_outcome == "win")
        losses = sum(1 for effective_outcome, _ in filtered_effective_states if effective_outcome == "loss")
        no_action = sum(1 for effective_outcome, _ in filtered_effective_states if effective_outcome == "no_action")
        watchlist = sum(1 for effective_outcome, _ in filtered_effective_states if effective_outcome == "watchlist")
        scored_outcomes = wins + losses
        return RecommendationPlanStats(
            total_plans=len(filtered_rows),
            open_plans=open_plans,
            expired_plans=expired_plans,
            scored_outcomes=scored_outcomes,
            win_rate_percent=round((wins / scored_outcomes) * 100.0, 1) if scored_outcomes > 0 else None,
            window=window_label,
            resolved_outcomes=scored_outcomes,
            open_outcomes=open_plans,
            expired_outcomes=expired_plans,
            win_outcomes=wins,
            loss_outcomes=losses,
            no_action_outcomes=no_action,
            watchlist_outcomes=watchlist,
        )

    @staticmethod
    def _window_start(window: str | None) -> datetime | None:
        normalized = (window or "all").strip().lower()
        if normalized == "day":
            return datetime.now(timezone.utc) - timedelta(days=1)
        if normalized == "week":
            return datetime.now(timezone.utc) - timedelta(days=7)
        if normalized == "month":
            return datetime.now(timezone.utc) - timedelta(days=30)
        if normalized == "year":
            return datetime.now(timezone.utc) - timedelta(days=365)
        return None

    def _to_model(self, record: RecommendationPlanRecord) -> RecommendationPlan:
        try:
            horizon = StrategyHorizon(record.horizon)
        except ValueError:
            horizon = StrategyHorizon.ONE_WEEK
        return RecommendationPlan(
            id=record.id,
            ticker=record.ticker,
            horizon=horizon,
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
            risks=self._load(record.risks_json, []),
            warnings=self._load(record.warnings_json, []),
            missing_inputs=self._load(record.missing_inputs_json, []),
            evidence_summary=self._load(record.evidence_summary_json, {}),
            signal_breakdown=self._load(record.signal_breakdown_json, {}),
            computed_at=self._normalize_datetime(record.computed_at),
            run_id=record.run_id,
            job_id=record.job_id,
            watchlist_id=record.watchlist_id,
            ticker_signal_snapshot_id=record.ticker_signal_snapshot_id,
        )
