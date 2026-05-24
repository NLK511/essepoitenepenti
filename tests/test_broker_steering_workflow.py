from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerOrderExecution, BrokerPosition, BrokerReconciliationSnapshot, RecommendationPlan
from trade_proposer_app.persistence.models import Base, BrokerSteeringDecisionRecord, ObservabilityEventRecord
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.broker_reconciliation_snapshots import BrokerReconciliationSnapshotRepository
from trade_proposer_app.repositories.broker_steering_decisions import BrokerSteeringDecisionRepository
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.broker_position_steering import BrokerSteeringConfig, BrokerSteeringEngine
from trade_proposer_app.services.broker_position_steering_workflow import BrokerSteeringService, BrokerSteeringStateBuilder


NOW = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _plan(ticker: str = "AAPL", action: str = "long") -> RecommendationPlan:
    return RecommendationPlan(
        ticker=ticker,
        horizon="1w",
        action=action,
        confidence_percent=70.0,
        entry_price_low=100.0,
        entry_price_high=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        holding_period_days=5,
    )


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
            {"decision": decision_name, "execute_allowed": False, "reason_codes": ["seed"], "diagnostics": {}},
        )()
        decisions.create(recommendation_plan_id=plan.id or 0, ticker=plan.ticker, decision=decision, execution_status="dry_run")

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

    saved = repo.create(recommendation_plan_id=7, ticker="AAPL", decision=decision, execution_status="dry_run")

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

    states = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(now=NOW)

    assert len(states) == 1
    assert states[0].has_open_position is True
    assert states[0].has_pending_order is False
    assert states[0].current_price == 101.0


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

    states = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(now=NOW)

    assert len(states) == 1
    assert states[0].broker_order_id == active_order.id
    assert states[0].has_pending_order is True


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
        BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(now=NOW)[0],
        BrokerSteeringConfig(enabled=True, dry_run=False),
    )

    assert decision.decision == "manual_review_required"
    assert decision.requires_manual_review is True


def test_state_builder_uses_latest_reconciliation_snapshot_to_keep_broker_uncertainty_visible() -> None:
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

    state = BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0).list_states(now=NOW)[0]
    decision = BrokerSteeringEngine().evaluate(state, BrokerSteeringConfig(enabled=True, dry_run=False))

    assert state.broker_reconciliation_healthy is False
    assert decision.decision == "manual_review_required"
    assert "broker_uncertainty" in decision.reason_codes


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

    service = BrokerSteeringService(session, builder=BrokerSteeringStateBuilder(session, price_lookup=lambda _ticker: 101.0))
    summary = service.run_once(now=NOW)

    assert summary.total_candidates == 1
    assert summary.execution_status == "dry_run"
    assert session.query(BrokerSteeringDecisionRecord).count() == 1
    assert session.query(ObservabilityEventRecord).count() == 3


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
            computed_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
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
            status="submitted",
            broker_order_id="alpaca-order-live-invalidation",
            client_order_id="steering-live-order-0",
            submitted_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
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
    )

    summary = service.run_once(now=NOW)

    assert summary.execution_status == "submitted"
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
            computed_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
            submitted_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
    )

    summary = service.run_once(now=NOW)

    assert summary.execution_status == "submitted"
    assert order_execution.canceled == [order.id or 0]
    stored = session.query(BrokerSteeringDecisionRecord).one()
    assert stored.execution_status == "succeeded"
    assert session.query(ObservabilityEventRecord).filter(ObservabilityEventRecord.event_type == "steering_broker_mutation_succeeded").count() == 1


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
            computed_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
            submitted_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            filled_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
    )

    summary = service.run_once(now=NOW)

    assert summary.execution_status == "submitted"
    assert order_execution.amended == [(order.id or 0, 97.5, None)]
    stored = session.query(BrokerSteeringDecisionRecord).filter(BrokerSteeringDecisionRecord.broker_position_id == order.id).one()
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
            computed_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
            submitted_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            filled_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
    )

    summary = service.run_once(now=NOW)

    assert summary.execution_status == "submitted"
    assert order_execution.amended[0][0] == (order.id or 0)
    assert order_execution.amended[0][1] is None
    assert round(order_execution.amended[0][2] or 0.0, 4) == 101.0025
    stored = session.query(BrokerSteeringDecisionRecord).filter(BrokerSteeringDecisionRecord.broker_position_id == order.id).one()
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
            computed_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
            submitted_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            filled_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
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
    )

    summary = service.run_once(now=NOW)

    assert summary.execution_status == "submitted"
    assert order_execution.closed == ["AAPL"]
    stored = session.query(BrokerSteeringDecisionRecord).filter(BrokerSteeringDecisionRecord.broker_position_id == position.id).one()
    assert stored.decision == "close_position_now"
    assert stored.execution_status == "succeeded"
