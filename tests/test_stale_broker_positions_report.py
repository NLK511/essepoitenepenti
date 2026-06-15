from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scripts.mark_stale_broker_positions_needs_review import expired_position_ids
from scripts.report_stale_broker_positions import build_report
from trade_proposer_app.persistence.models import (
    Base,
    BrokerPositionRecord,
    RecommendationPlanRecord,
)

NOW = datetime(2026, 6, 8, 12, tzinfo=UTC)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_position(
    session: Session,
    *,
    computed_at: datetime,
    holding_days: int,
    status: str = "open",
    quantity: int = 1,
) -> BrokerPositionRecord:
    plan = RecommendationPlanRecord(
        ticker="AAPL",
        horizon="1w",
        action="long",
        confidence_percent=70.0,
        computed_at=computed_at,
        holding_period_days=holding_days,
    )
    session.add(plan)
    session.flush()
    position = BrokerPositionRecord(
        broker_order_execution_id=plan.id or 1,
        broker_account_id="alpaca-paper-default",
        broker="alpaca",
        account_mode="paper",
        recommendation_plan_id=plan.id,
        recommendation_plan_ticker="AAPL",
        ticker="AAPL",
        action="long",
        side="buy",
        quantity=max(1, quantity),
        current_quantity=quantity,
        status=status,
        stop_loss_order_id="sl-1",
        stop_loss_order_status="new",
        stop_loss_order_price=95.0,
        take_profit_order_id="tp-1",
        take_profit_order_status="new",
        take_profit_order_price=110.0,
        protective_orders_verified_at=NOW,
        protective_orders_source="test",
    )
    session.add(position)
    session.commit()
    return position


def test_stale_position_report_counts_expired_and_quantity_zero_rows() -> None:
    session = _session()
    _seed_position(session, computed_at=NOW - timedelta(days=10), holding_days=5)
    _seed_position(
        session,
        computed_at=NOW - timedelta(days=1),
        holding_days=5,
        status="submitted",
        quantity=0,
    )

    report = build_report(session, now=NOW)

    assert report["summary"]["active_app_position_rows"] == 2
    assert report["summary"]["expired_plan_rows"] == 1
    assert report["summary"]["quantity_zero_submitted_rows"] == 1
    assert report["summary"]["missing_active_protective_orders"] == 0


def test_mark_stale_candidates_only_expired_rows() -> None:
    session = _session()
    expired = _seed_position(session, computed_at=NOW - timedelta(days=10), holding_days=5)
    _seed_position(session, computed_at=NOW - timedelta(days=1), holding_days=5)

    assert expired_position_ids(session, now=NOW) == [expired.id]
