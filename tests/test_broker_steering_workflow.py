from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import (
    BrokerOrderExecution,
    BrokerPosition,
    BrokerReconciliationSnapshot,
    HistoricalMarketBar,
    RecommendationPlan,
)
from trade_proposer_app.persistence.models import (
    Base,
    BrokerOrderExecutionRecord,
    BrokerPositionRecord,
    BrokerSteeringDecisionRecord,
    ObservabilityEventRecord,
)
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import (
    BrokerReconciliationSnapshotRepository,
)
from trade_proposer_app.repositories.broker_steering_decisions import (
    BrokerSteeringDecisionRepository,
)
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.broker_position_steering import (
    BrokerSteeringConfig,
    BrokerSteeringEngine,
)
from trade_proposer_app.services.broker_position_steering_workflow import (
    BrokerSteeringService,
    BrokerSteeringStateBuilder,
)

NOW = datetime(2026, 5, 1, 15, 0, tzinfo=UTC)


class SuccessfulBrokerRefreshStub:
    def __init__(self) -> None:
        self.calls = 0

    def sync_open_orders(self, *, limit: int = 200):
        self.calls += 1
        return type(
            "SyncOutcome",
            (),
            {"summary": {"synced_count": 2, "skipped_count": 0, "failed_count": 0}},
        )()


class FailingBrokerRefreshStub:
    def __init__(self) -> None:
        self.calls = 0

    def sync_open_orders(self, *, limit: int = 200):
        self.calls += 1
        raise RuntimeError("broker refresh unavailable")


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _plan(ticker: str = "AAPL", action: str = "long", **overrides) -> RecommendationPlan:
    values = {
        "ticker": ticker,
        "horizon": "1w",
        "action": action,
        "confidence_percent": 70.0,
        "entry_price_low": 100.0,
        "entry_price_high": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "holding_period_days": 5,
    }
    values.update(overrides)
    return RecommendationPlan(**values)


def _set_steering_defaults(settings: SettingsRepository, *, enabled: bool, dry_run: bool) -> None:
    settings.set_steering_config(
        enabled=enabled,
        dry_run=dry_run,
        cancel_expired_pending_orders_enabled=True,
        cancel_invalidated_pending_orders_enabled=True,
        move_to_profit_enabled=True,
        close_on_severe_invalidation_enabled=True,
        tighten_on_deterioration_enabled=True,
        lower_tp_on_weakness_enabled=True,
        pending_expiration_grace_minutes=5,
        pending_min_confidence_percent=55.0,
        pending_invalidation_required_signals=2,
        pending_price_chase_limit_percent=1.0,
        breakeven_trigger_percent=0.75,
        min_profit_lock_percent=0.10,
        position_close_confidence_percent=40.0,
        position_close_required_signals=3,
        position_min_hold_confidence_percent=50.0,
        position_deterioration_required_signals=2,
        deterioration_stop_cushion_percent=0.35,
        weakened_thesis_tp_cushion_percent=0.50,
        min_tp_distance_percent=0.10,
        min_reviewed_dry_run_decisions_before_enable=30,
        min_reviewed_dry_run_amendments_before_enable=10,
        min_reviewed_dry_run_close_now_before_enable=10,
    )


def _seed_reviewed_steering_history(session: Session) -> None:
    plans = RecommendationPlanRepository(session)
    decisions = BrokerSteeringDecisionRepository(session)
    plan = plans.create_plan(_plan(ticker="SEED"))

    def record(decision_name: str) -> None:
        decision = type(
            "Decision",
            (),
            {
                "decision": decision_name,
                "execute_allowed": False,
                "reason_codes": ["seed"],
                "diagnostics": {},
            },
        )()
        decisions.create(
            recommendation_plan_id=plan.id or 0,
            ticker=plan.ticker,
            decision=decision,
            execution_status="dry_run",
        )

    for _ in range(10):
        record("tighten_stop_loss")
    for _ in range(10):
        record("close_position_now")
    for _ in range(10):
        record("keep_position_exits")


def _seed_healthy_reconciliation_snapshot(session: Session, ticker: str) -> None:
    BrokerReconciliationSnapshotRepository(session).create(
        BrokerReconciliationSnapshot(
            broker="alpaca",
            account_mode="paper",
            snapshot_type="post_sync",
            ticker=ticker,
            drift_severity="ok",
            warnings=[],
        )
    )


def test_steering_decision_repository_round_trip() -> None:
    session = create_session()
    repo = BrokerSteeringDecisionRepository(session)

    decision = type(
        "Decision",
        (),
        {
            "decision": "keep_position_exits",
            "execute_allowed": False,
            "reason_codes": ["position_exits_stable"],
            "proposed_stop_loss": 95.0,
            "proposed_take_profit": 110.0,
            "current_price": 101.0,
            "current_stop_loss": 95.0,
            "current_take_profit": 110.0,
            "diagnostics": {"foo": "bar"},
        },
    )()

    saved = repo.create(
        recommendation_plan_id=7, ticker="AAPL", decision=decision, execution_status="dry_run"
    )

    assert saved["decision"] == "keep_position_exits"
    assert saved["reason_codes"] == ["position_exits_stable"]
    assert saved["diagnostics"] == {"foo": "bar"}
    assert session.query(BrokerSteeringDecisionRecord).count() == 1


def test_state_builder_prefers_open_position_over_pending_order() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    positions = BrokerPositionRepository(session)

    plan = plans.create_plan(_plan())
    orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="submitted",
            client_order_id="order-1",
        )
    )
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            current_stop_loss=95.0,
            exit_order_id=None,
        )
    )

    states = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )

    assert len(states) == 1
    assert states[0].has_open_position is True
    assert states[0].has_pending_order is False
    assert states[0].current_price == 101.0


def test_state_builder_does_not_treat_missing_filled_exit_as_missing_protection() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    positions = BrokerPositionRepository(session)

    plan = plans.create_plan(_plan())
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="filled",
            broker_order_id="parent-order-1",
            client_order_id="order-1",
        )
    )
    positions.create(
        BrokerPosition(
            broker_order_execution_id=order.id or 0,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="parent-order-1",
            entry_avg_price=100.0,
            exit_order_id=None,
            stop_loss_order_id="stop-child-1",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-child-1",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
        )
    )

    states = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )

    assert len(states) == 1
    assert states[0].linked_exit_orders_missing is False


def test_state_builder_excludes_submitted_zero_quantity_positions_from_open_steering() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)

    plan = plans.create_plan(_plan())
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            quantity=1,
            current_quantity=0,
            status="submitted",
            entry_order_id="order-1",
        )
    )

    states = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )

    assert states == []


def test_expired_open_position_blocks_profit_lock_amendment() -> None:
    from trade_proposer_app.services.broker_position_steering import BrokerSteeringState

    decision = BrokerSteeringEngine().evaluate(
        BrokerSteeringState(
            recommendation_plan_id=1,
            ticker="AAPL",
            direction="long",
            current_price=102.0,
            entry_price=100.0,
            original_stop_loss=95.0,
            current_stop_loss=95.0,
            current_take_profit=110.0,
            confidence_percent=70.0,
            has_open_position=True,
            broker_ownership_known=True,
            broker_reconciliation_healthy=True,
            broker_reconciliation_age_minutes=1.0,
            linked_exit_orders_missing=False,
            position_holding_period_expired=True,
            expiration_at=NOW - timedelta(minutes=1),
            now=NOW,
        ),
        BrokerSteeringConfig(enabled=True, dry_run=False),
    )

    assert decision.decision == "manual_review_required"
    assert decision.execute_allowed is False
    assert "position_holding_period_expired" in decision.reason_codes


def test_fresh_non_expired_protected_position_can_amend() -> None:
    from trade_proposer_app.services.broker_position_steering import BrokerSteeringState

    decision = BrokerSteeringEngine().evaluate(
        BrokerSteeringState(
            recommendation_plan_id=1,
            ticker="AAPL",
            direction="long",
            current_price=102.0,
            entry_price=100.0,
            original_stop_loss=95.0,
            current_stop_loss=95.0,
            current_take_profit=110.0,
            confidence_percent=70.0,
            has_open_position=True,
            broker_ownership_known=True,
            broker_reconciliation_healthy=True,
            broker_reconciliation_age_minutes=1.0,
            linked_exit_orders_missing=False,
            position_holding_period_expired=False,
            expiration_at=NOW + timedelta(days=1),
            now=NOW,
        ),
        BrokerSteeringConfig(enabled=True, dry_run=False),
    )

    assert decision.decision == "move_stop_to_breakeven_or_profit"
    assert "profit_lock_triggered" in decision.reason_codes


def test_stale_reconciliation_blocks_profit_lock_amendment() -> None:
    from trade_proposer_app.services.broker_position_steering import BrokerSteeringState

    decision = BrokerSteeringEngine().evaluate(
        BrokerSteeringState(
            recommendation_plan_id=1,
            ticker="AAPL",
            direction="long",
            current_price=102.0,
            entry_price=100.0,
            original_stop_loss=95.0,
            current_stop_loss=95.0,
            current_take_profit=110.0,
            confidence_percent=70.0,
            has_open_position=True,
            broker_ownership_known=True,
            broker_reconciliation_healthy=True,
            broker_reconciliation_age_minutes=45.0,
            linked_exit_orders_missing=False,
            position_holding_period_expired=False,
            expiration_at=NOW + timedelta(days=1),
            now=NOW,
        ),
        BrokerSteeringConfig(enabled=True, dry_run=False, max_reconciliation_age_minutes=30),
    )

    assert decision.decision == "manual_review_required"
    assert "broker_reconciliation_stale" in decision.reason_codes


def test_missing_active_protective_orders_block_amendment() -> None:
    from trade_proposer_app.services.broker_position_steering import BrokerSteeringState

    decision = BrokerSteeringEngine().evaluate(
        BrokerSteeringState(
            recommendation_plan_id=1,
            ticker="AAPL",
            direction="long",
            current_price=102.0,
            entry_price=100.0,
            original_stop_loss=95.0,
            current_stop_loss=95.0,
            current_take_profit=110.0,
            confidence_percent=70.0,
            has_open_position=True,
            broker_ownership_known=True,
            broker_reconciliation_healthy=True,
            broker_reconciliation_age_minutes=1.0,
            linked_exit_orders_missing=True,
            position_holding_period_expired=False,
            expiration_at=NOW + timedelta(days=1),
            now=NOW,
        ),
        BrokerSteeringConfig(enabled=True, dry_run=False),
    )

    assert decision.decision == "manual_review_required"
    assert "position_linked_exit_orders_missing" in decision.reason_codes


def test_state_builder_computes_reconciliation_age_and_expiration_flag() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    snapshots = BrokerReconciliationSnapshotRepository(session)

    plan = plans.create_plan(_plan(computed_at=NOW - timedelta(days=6), holding_period_days=5))
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            current_stop_loss=95.0,
            stop_loss_order_id="sl-1",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-1",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
            protective_orders_verified_at=NOW - timedelta(minutes=10),
        )
    )
    snapshots.create(
        BrokerReconciliationSnapshot(
            broker="alpaca",
            account_mode="paper",
            snapshot_type="post_sync",
            ticker=plan.ticker,
            drift_severity="ok",
            warnings=[],
            created_at=NOW - timedelta(minutes=10),
        )
    )

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 102.0).list_states(
        now=NOW
    )[0]

    assert state.broker_reconciliation_age_minutes == 10.0
    assert state.broker_reconciliation_healthy is True
    assert state.position_holding_period_expired is True


def test_state_builder_keeps_active_orders_even_when_history_exceeds_paging_limit() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)

    plan = plans.create_plan(_plan())
    active_order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="submitted",
            client_order_id="order-active",
        )
    )
    for idx in range(205):
        orders.create(
            BrokerOrderExecution(
                recommendation_plan_id=plan.id or 1,
                recommendation_plan_ticker="AAPL",
                ticker="AAPL",
                action="long",
                side="buy",
                order_type="limit",
                quantity=1,
                notional_amount=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                status="canceled",
                client_order_id=f"order-closed-{idx}",
            )
        )

    states = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )

    assert len(states) == 1
    assert states[0].broker_order_id == active_order.id
    assert states[0].has_pending_order is True


def test_state_builder_uses_fresh_steering_evidence_for_severe_invalidation() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    plan = plans.create_plan(
        _plan(
            signal_breakdown={
                "steering_evidence": {
                    "computed_at": NOW.isoformat(),
                    "warnings": ["severe_negative_news"],
                    "market_intelligence_conflict_flags": [],
                    "freshness_status": "fresh",
                }
            }
        )
    )
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            exit_order_id=None,
        )
    )

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 94.0).list_states(
        now=NOW
    )[0]

    assert state.severe_negative_news is True


def test_state_builder_ignores_stale_steering_evidence_for_severe_invalidation() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    plan = plans.create_plan(
        _plan(
            signal_breakdown={
                "steering_evidence": {
                    "computed_at": (NOW - timedelta(days=3)).isoformat(),
                    "warnings": ["severe_negative_news"],
                    "freshness_status": "fresh",
                }
            }
        )
    )
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker="AAPL",
            ticker="AAPL",
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            exit_order_id=None,
        )
    )

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 94.0).list_states(
        now=NOW
    )[0]

    assert state.severe_negative_news is False


def test_state_builder_marks_unknown_direction_plans_for_manual_review() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)

    plan = plans.create_plan(_plan(action="no_action"))
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="no_action",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            current_stop_loss=95.0,
            exit_order_id=None,
        )
    )

    decision = BrokerSteeringEngine().evaluate(
        BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
            now=NOW
        )[0],
        BrokerSteeringConfig(enabled=True, dry_run=False),
    )

    assert decision.decision == "manual_review_required"
    assert decision.requires_manual_review is True


def test_state_builder_uses_latest_reconciliation_snapshot_to_keep_broker_uncertainty_visible() -> (
    None
):
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    snapshots = BrokerReconciliationSnapshotRepository(session)

    plan = plans.create_plan(_plan())
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            current_stop_loss=95.0,
            exit_order_id=None,
        )
    )
    snapshots.create(
        BrokerReconciliationSnapshot(
            broker="alpaca",
            account_mode="paper",
            snapshot_type="post_sync",
            ticker=plan.ticker,
            drift_severity="material",
            warnings=["broker snapshot warnings"],
        )
    )

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )[0]
    decision = BrokerSteeringEngine().evaluate(
        state, BrokerSteeringConfig(enabled=True, dry_run=False)
    )

    assert state.broker_reconciliation_healthy is False
    assert decision.decision == "manual_review_required"
    assert "broker_uncertainty" in decision.reason_codes


def test_state_builder_uses_fresh_order_row_when_snapshot_is_absent() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    plan = plans.create_plan(_plan())
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="submitted",
            client_order_id="fresh-local-order",
        )
    )
    session.query(BrokerOrderExecutionRecord).filter(
        BrokerOrderExecutionRecord.id == order.id
    ).update({"updated_at": NOW - timedelta(minutes=5)})
    session.commit()

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )[0]

    assert state.broker_reconciliation_healthy is True
    assert state.broker_reconciliation_age_minutes == 5.0


def test_state_builder_snapshot_warning_overrides_fresh_order_row() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    snapshots = BrokerReconciliationSnapshotRepository(session)
    plan = plans.create_plan(_plan())
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="submitted",
            client_order_id="fresh-local-order-with-drift",
        )
    )
    session.query(BrokerOrderExecutionRecord).filter(
        BrokerOrderExecutionRecord.id == order.id
    ).update({"updated_at": NOW - timedelta(minutes=5)})
    session.commit()
    snapshots.create(
        BrokerReconciliationSnapshot(
            broker="alpaca",
            account_mode="paper",
            snapshot_type="post_sync",
            ticker=plan.ticker,
            drift_severity="ok",
            warnings=["broker drift still unresolved"],
            created_at=NOW - timedelta(minutes=2),
        )
    )

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )[0]

    assert state.broker_reconciliation_healthy is False
    assert state.broker_reconciliation_age_minutes == 2.0


def test_state_builder_blocks_position_when_protective_verification_is_stale() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    plan = plans.create_plan(_plan())
    position = positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            stop_loss_order_id="sl-1",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-1",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
            protective_orders_verified_at=NOW - timedelta(minutes=45),
        )
    )
    session.query(BrokerPositionRecord).filter(BrokerPositionRecord.id == position.id).update(
        {"updated_at": NOW - timedelta(minutes=5)}
    )
    session.commit()

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(
        now=NOW
    )[0]

    assert state.broker_reconciliation_healthy is False
    assert state.broker_reconciliation_age_minutes == 45.0


def test_state_builder_uses_latest_daily_market_bar_as_price_proxy() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    market_data = HistoricalMarketDataRepository(session)
    snapshots = BrokerReconciliationSnapshotRepository(session)

    plan = plans.create_plan(_plan())
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            current_stop_loss=95.0,
            exit_order_id=None,
            stop_loss_order_id="sl-1",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-1",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
            protective_orders_verified_at=NOW - timedelta(minutes=1),
        )
    )
    snapshots.create(
        BrokerReconciliationSnapshot(
            broker="alpaca",
            account_mode="paper",
            snapshot_type="post_sync",
            ticker=plan.ticker,
            drift_severity="ok",
            warnings=[],
        )
    )
    market_data.upsert_bar(
        HistoricalMarketBar(
            ticker=plan.ticker,
            timeframe="1d",
            bar_time=NOW,
            available_at=NOW,
            open_price=99.0,
            high_price=102.0,
            low_price=98.5,
            close_price=101.0,
            volume=1000.0,
            source="test",
            source_tier="tier_a",
        )
    )

    state = BrokerSteeringStateBuilder(session).list_states(now=NOW)[0]
    decision = BrokerSteeringEngine().evaluate(
        state, BrokerSteeringConfig(enabled=True, dry_run=False)
    )

    assert state.current_price == 101.0
    assert state.broker_reconciliation_healthy is True
    assert decision.decision == "move_stop_to_breakeven_or_profit"
    assert decision.proposed_stop_loss == 100.1


def test_steering_service_persists_decisions_and_events() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    positions = BrokerPositionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=True)
    plan = plans.create_plan(_plan())
    positions.create(
        BrokerPosition(
            broker_order_execution_id=1,
            recommendation_plan_id=plan.id or 1,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=1,
            current_quantity=1,
            status="open",
            entry_order_id="order-1",
            entry_avg_price=100.0,
            current_stop_loss=95.0,
            exit_order_id=None,
        )
    )

    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0),
        broker_reconciliation_service=SuccessfulBrokerRefreshStub(),
    )
    summary = service.run_once(now=NOW)

    assert summary.total_candidates == 1
    assert summary.execution_status == "dry_run"
    assert session.query(BrokerSteeringDecisionRecord).count() == 1
    assert session.query(ObservabilityEventRecord).count() == 3


def test_steering_service_refreshes_broker_state_before_decisions() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=True)
    plan = plans.create_plan(_plan(computed_at=datetime(2026, 4, 30, tzinfo=UTC)))
    orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            status="submitted",
            client_order_id="refresh-preflight-order",
        )
    )
    _seed_healthy_reconciliation_snapshot(session, plan.ticker)
    refresh = SuccessfulBrokerRefreshStub()

    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0),
        broker_reconciliation_service=refresh,
    )

    summary = service.run_once(now=NOW)

    assert refresh.calls == 1
    assert summary.broker_refresh_attempted is True
    assert summary.broker_refresh_status == "succeeded"
    assert summary.broker_refresh_synced_count == 2


def test_steering_service_blocks_live_mutation_when_broker_refresh_fails() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=False)
    plan = plans.create_plan(
        _plan(holding_period_days=1, computed_at=datetime(2026, 4, 28, tzinfo=UTC))
    )
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            quantity=1,
            notional_amount=100.0,
            status="submitted",
            broker_order_id="broker-order-1",
            client_order_id="blocked-refresh-failure-order",
        )
    )
    _seed_healthy_reconciliation_snapshot(session, plan.ticker)

    class LiveOrderExecutionStub:
        def __init__(self) -> None:
            self.canceled: list[int] = []

        def cancel_execution(self, execution_id: int):
            self.canceled.append(execution_id)

    order_execution = LiveOrderExecutionStub()
    refresh = FailingBrokerRefreshStub()
    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0),
        order_execution=order_execution,
        broker_reconciliation_service=refresh,
    )

    summary = service.run_once(now=NOW)

    assert refresh.calls == 1
    assert summary.broker_refresh_status == "failed"
    assert summary.execution_status == "blocked"
    assert order_execution.canceled == []
    stored = session.query(BrokerSteeringDecisionRecord).one()
    assert stored.broker_order_id == (order.id or 0)
    assert stored.execution_status == "blocked"


def test_steering_service_blocks_live_pending_invalidation_without_reviewed_history() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=False)
    plan = plans.create_plan(
        RecommendationPlan(
            ticker="MSFT",
            horizon="1w",
            action="long",
            confidence_percent=70.0,
            entry_price_low=100.0,
            entry_price_high=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            holding_period_days=5,
            computed_at=datetime(2026, 4, 30, tzinfo=UTC),
            warnings=["severe_negative_news"],
        )
    )
    orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            time_in_force="gtc",
            quantity=10,
            notional_amount=1000.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="submitted",
            broker_order_id="alpaca-order-live-invalidation",
            client_order_id="steering-live-order-0",
            submitted_at=datetime(2026, 4, 30, tzinfo=UTC),
            request_payload={"symbol": "MSFT"},
            response_payload={"id": "alpaca-order-live-invalidation", "status": "submitted"},
        )
    )

    class LiveOrderExecutionStub:
        def __init__(self) -> None:
            self.canceled: list[int] = []

        def cancel_execution(self, execution_id: int):
            self.canceled.append(execution_id)
            return None

        def close_position(self, ticker: str):
            raise AssertionError("unexpected close_position")

        def amend_execution(self, execution_id: int, *, stop_loss=None, take_profit=None):
            raise AssertionError("unexpected amend_execution")

    _seed_healthy_reconciliation_snapshot(session, plan.ticker)
    order_execution = LiveOrderExecutionStub()
    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0),
        order_execution=order_execution,
        broker_reconciliation_service=SuccessfulBrokerRefreshStub(),
    )

    summary = service.run_once(now=NOW)

    assert summary.broker_refresh_status == "succeeded"
    assert summary.execution_status == "blocked"
    assert order_execution.canceled == []
    stored = session.query(BrokerSteeringDecisionRecord).one()
    assert stored.decision == "cancel_pending_order"
    assert stored.execution_status == "blocked"
    assert stored.error_message == "live_pending_invalidation_sample_threshold_unmet"


def test_steering_service_can_execute_supported_live_pending_cancellation() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=False)
    plan = plans.create_plan(
        RecommendationPlan(
            ticker="MSFT",
            horizon="1w",
            action="long",
            confidence_percent=70.0,
            entry_price_low=100.0,
            entry_price_high=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            holding_period_days=1,
            computed_at=datetime(2026, 4, 28, tzinfo=UTC),
        )
    )
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            time_in_force="gtc",
            quantity=10,
            notional_amount=1000.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="submitted",
            broker_order_id="alpaca-order-live-cancel",
            client_order_id="steering-live-order-1",
            submitted_at=datetime(2026, 4, 28, tzinfo=UTC),
            request_payload={"symbol": "MSFT"},
            response_payload={"id": "alpaca-order-live-cancel", "status": "submitted"},
        )
    )

    class LiveOrderExecutionStub:
        def __init__(self) -> None:
            self.canceled: list[int] = []

        def cancel_execution(self, execution_id: int):
            self.canceled.append(execution_id)
            return None

        def close_position(self, ticker: str):
            raise AssertionError("unexpected close_position")

        def amend_execution(self, execution_id: int, *, stop_loss=None, take_profit=None):
            raise AssertionError("unexpected amend_execution")

    _seed_healthy_reconciliation_snapshot(session, plan.ticker)
    order_execution = LiveOrderExecutionStub()
    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0),
        order_execution=order_execution,
        broker_reconciliation_service=SuccessfulBrokerRefreshStub(),
    )

    summary = service.run_once(now=NOW)

    assert summary.broker_refresh_status == "succeeded"
    assert summary.execution_status == "succeeded"
    assert order_execution.canceled == [order.id or 0]
    stored = session.query(BrokerSteeringDecisionRecord).one()
    assert stored.execution_status == "succeeded"
    assert (
        session.query(ObservabilityEventRecord)
        .filter(ObservabilityEventRecord.event_type == "steering_broker_mutation_succeeded")
        .count()
        == 1
    )


def test_steering_service_can_execute_supported_live_stop_amendment() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    positions = BrokerPositionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=False)
    settings.set_steering_config(
        enabled=True,
        dry_run=False,
        cancel_expired_pending_orders_enabled=True,
        cancel_invalidated_pending_orders_enabled=True,
        move_to_profit_enabled=False,
        close_on_severe_invalidation_enabled=False,
        tighten_on_deterioration_enabled=True,
        lower_tp_on_weakness_enabled=False,
        pending_expiration_grace_minutes=5,
        pending_min_confidence_percent=55.0,
        pending_invalidation_required_signals=2,
        pending_price_chase_limit_percent=1.0,
        breakeven_trigger_percent=0.75,
        min_profit_lock_percent=0.10,
        position_close_confidence_percent=40.0,
        position_close_required_signals=3,
        position_min_hold_confidence_percent=50.0,
        position_deterioration_required_signals=2,
        deterioration_stop_cushion_percent=2.5,
        weakened_thesis_tp_cushion_percent=0.50,
        min_tp_distance_percent=0.10,
        min_reviewed_dry_run_decisions_before_enable=30,
        min_reviewed_dry_run_amendments_before_enable=10,
        min_reviewed_dry_run_close_now_before_enable=10,
    )
    plan = plans.create_plan(
        RecommendationPlan(
            ticker="AAPL",
            horizon="1w",
            action="long",
            confidence_percent=30.0,
            entry_price_low=100.0,
            entry_price_high=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            holding_period_days=5,
            computed_at=datetime(2026, 4, 28, tzinfo=UTC),
            warnings=["severe_negative_news"],
        )
    )
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            time_in_force="gtc",
            quantity=10,
            notional_amount=1000.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="open",
            broker_order_id="alpaca-order-live-amend",
            client_order_id="steering-live-amend-1",
            submitted_at=datetime(2026, 4, 28, tzinfo=UTC),
            filled_at=datetime(2026, 4, 28, tzinfo=UTC),
            request_payload={"symbol": "AAPL"},
            response_payload={"id": "alpaca-order-live-amend", "status": "open"},
        )
    )
    positions.create(
        BrokerPosition(
            broker_order_execution_id=order.id or 0,
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=10,
            current_quantity=10,
            status="open",
            entry_order_id="steering-live-amend-1",
            entry_avg_price=100.0,
            exit_order_id=None,
            stop_loss_order_id="sl-live-amend",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-live-amend",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
            protective_orders_verified_at=NOW - timedelta(minutes=1),
        )
    )

    class LiveOrderExecutionStub:
        def __init__(self) -> None:
            self.amended: list[tuple[int, float | None, float | None]] = []

        def cancel_execution(self, execution_id: int):
            raise AssertionError("unexpected cancel_execution")

        def close_position(self, ticker: str):
            raise AssertionError("unexpected close_position")

        def amend_execution(self, execution_id: int, *, stop_loss=None, take_profit=None):
            self.amended.append((execution_id, stop_loss, take_profit))
            return None

    _seed_reviewed_steering_history(session)
    _seed_healthy_reconciliation_snapshot(session, plan.ticker)
    order_execution = LiveOrderExecutionStub()
    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 100.0),
        order_execution=order_execution,
        broker_reconciliation_service=SuccessfulBrokerRefreshStub(),
    )

    summary = service.run_once(now=NOW)

    assert summary.broker_refresh_status == "succeeded"
    assert summary.execution_status == "succeeded"
    assert order_execution.amended == [(order.id or 0, 97.5, None)]
    stored = (
        session.query(BrokerSteeringDecisionRecord)
        .filter(BrokerSteeringDecisionRecord.broker_position_id == order.id)
        .one()
    )
    assert stored.decision == "tighten_stop_loss"
    assert stored.execution_status == "succeeded"


def test_steering_service_can_execute_supported_live_take_profit_lowering() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    positions = BrokerPositionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=False)
    settings.set_steering_config(
        enabled=True,
        dry_run=False,
        cancel_expired_pending_orders_enabled=True,
        cancel_invalidated_pending_orders_enabled=True,
        move_to_profit_enabled=False,
        close_on_severe_invalidation_enabled=False,
        tighten_on_deterioration_enabled=False,
        lower_tp_on_weakness_enabled=True,
        pending_expiration_grace_minutes=5,
        pending_min_confidence_percent=55.0,
        pending_invalidation_required_signals=2,
        pending_price_chase_limit_percent=1.0,
        breakeven_trigger_percent=0.75,
        min_profit_lock_percent=0.10,
        position_close_confidence_percent=40.0,
        position_close_required_signals=3,
        position_min_hold_confidence_percent=50.0,
        position_deterioration_required_signals=2,
        deterioration_stop_cushion_percent=2.5,
        weakened_thesis_tp_cushion_percent=0.5,
        min_tp_distance_percent=0.1,
        min_reviewed_dry_run_decisions_before_enable=30,
        min_reviewed_dry_run_amendments_before_enable=10,
        min_reviewed_dry_run_close_now_before_enable=10,
    )
    plan = plans.create_plan(
        RecommendationPlan(
            ticker="AAPL",
            horizon="1w",
            action="long",
            confidence_percent=30.0,
            entry_price_low=100.0,
            entry_price_high=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            holding_period_days=5,
            computed_at=datetime(2026, 4, 28, tzinfo=UTC),
            warnings=["severe_negative_news"],
        )
    )
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            time_in_force="gtc",
            quantity=10,
            notional_amount=1000.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="open",
            broker_order_id="alpaca-order-live-lower-tp",
            client_order_id="steering-live-lower-tp-1",
            submitted_at=datetime(2026, 4, 28, tzinfo=UTC),
            filled_at=datetime(2026, 4, 28, tzinfo=UTC),
            request_payload={"symbol": "AAPL"},
            response_payload={"id": "alpaca-order-live-lower-tp", "status": "open"},
        )
    )
    positions.create(
        BrokerPosition(
            broker_order_execution_id=order.id or 0,
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=10,
            current_quantity=10,
            status="open",
            entry_order_id="steering-live-lower-tp-1",
            entry_avg_price=100.0,
            exit_order_id=None,
            stop_loss_order_id="sl-live-lower-tp",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-live-lower-tp",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
            protective_orders_verified_at=NOW - timedelta(minutes=1),
        )
    )

    class LiveOrderExecutionStub:
        def __init__(self) -> None:
            self.amended: list[tuple[int, float | None, float | None]] = []

        def cancel_execution(self, execution_id: int):
            raise AssertionError("unexpected cancel_execution")

        def close_position(self, ticker: str):
            raise AssertionError("unexpected close_position")

        def amend_execution(self, execution_id: int, *, stop_loss=None, take_profit=None):
            self.amended.append((execution_id, stop_loss, take_profit))
            return None

    _seed_reviewed_steering_history(session)
    _seed_healthy_reconciliation_snapshot(session, plan.ticker)
    order_execution = LiveOrderExecutionStub()
    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 100.5),
        order_execution=order_execution,
        broker_reconciliation_service=SuccessfulBrokerRefreshStub(),
    )

    summary = service.run_once(now=NOW)

    assert summary.broker_refresh_status == "succeeded"
    assert summary.execution_status == "succeeded"
    assert order_execution.amended[0][0] == (order.id or 0)
    assert order_execution.amended[0][1] is None
    assert round(order_execution.amended[0][2] or 0.0, 4) == 101.0025
    stored = (
        session.query(BrokerSteeringDecisionRecord)
        .filter(BrokerSteeringDecisionRecord.broker_position_id == order.id)
        .one()
    )
    assert stored.decision == "lower_take_profit"
    assert stored.execution_status == "succeeded"


def test_steering_service_can_execute_supported_live_close_position() -> None:
    session = create_session()
    plans = RecommendationPlanRepository(session)
    orders = BrokerOrderExecutionRepository(session)
    positions = BrokerPositionRepository(session)
    settings = SettingsRepository(session)
    _set_steering_defaults(settings, enabled=True, dry_run=False)
    plan = plans.create_plan(
        RecommendationPlan(
            ticker="AAPL",
            horizon="1w",
            action="long",
            confidence_percent=30.0,
            entry_price_low=100.0,
            entry_price_high=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            holding_period_days=5,
            computed_at=datetime(2026, 4, 28, tzinfo=UTC),
            warnings=["severe_negative_news"],
        )
    )
    order = orders.create(
        BrokerOrderExecution(
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            order_type="limit",
            time_in_force="gtc",
            quantity=10,
            notional_amount=1000.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            status="filled",
            broker_order_id="alpaca-order-live-close",
            client_order_id="steering-live-close-1",
            submitted_at=datetime(2026, 4, 28, tzinfo=UTC),
            filled_at=datetime(2026, 4, 28, tzinfo=UTC),
            request_payload={"symbol": "AAPL"},
            response_payload={"id": "alpaca-order-live-close", "status": "filled"},
        )
    )
    position = positions.create(
        BrokerPosition(
            broker_order_execution_id=order.id or 0,
            recommendation_plan_id=plan.id or 0,
            recommendation_plan_ticker=plan.ticker,
            ticker=plan.ticker,
            action="long",
            side="buy",
            quantity=10,
            current_quantity=10,
            status="open",
            entry_order_id="steering-live-close-1",
            entry_avg_price=100.0,
            exit_order_id=None,
            stop_loss_order_id="sl-live-close",
            stop_loss_order_status="new",
            stop_loss_order_price=95.0,
            take_profit_order_id="tp-live-close",
            take_profit_order_status="new",
            take_profit_order_price=110.0,
            protective_orders_verified_at=NOW - timedelta(minutes=1),
        )
    )

    class LiveOrderExecutionStub:
        def __init__(self) -> None:
            self.closed: list[str] = []

        def cancel_execution(self, execution_id: int):
            raise AssertionError("unexpected cancel_execution")

        def close_position(self, ticker: str):
            self.closed.append(ticker)
            return None

        def amend_execution(self, execution_id: int, *, stop_loss=None, take_profit=None):
            raise AssertionError("unexpected amend_execution")

    _seed_reviewed_steering_history(session)
    _seed_healthy_reconciliation_snapshot(session, plan.ticker)
    order_execution = LiveOrderExecutionStub()
    service = BrokerSteeringService(
        session,
        builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 94.0),
        order_execution=order_execution,
        broker_reconciliation_service=SuccessfulBrokerRefreshStub(),
    )

    summary = service.run_once(now=NOW)

    assert summary.broker_refresh_status == "succeeded"
    assert summary.execution_status == "succeeded"
    assert order_execution.closed == ["AAPL"]
    stored = (
        session.query(BrokerSteeringDecisionRecord)
        .filter(BrokerSteeringDecisionRecord.broker_position_id == position.id)
        .one()
    )
    assert stored.decision == "close_position_now"
    assert stored.execution_status == "succeeded"
