import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerOrderExecution, BrokerPosition
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.services.multi_broker_reconciliation import MultiBrokerReconciliationService


class BrokerReconciliationMultiAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.orders = BrokerOrderExecutionRepository(self.session)
        self.positions = BrokerPositionRepository(self.session)
        self.safety = BrokerAccountSafetyRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _order(
        self, broker_account_id: str, plan_id: int, ticker: str = "AAPL"
    ) -> BrokerOrderExecution:
        return self.orders.create(
            BrokerOrderExecution(
                broker_account_id=broker_account_id,
                broker="etoro",
                account_mode="live",
                recommendation_plan_id=plan_id,
                recommendation_plan_ticker=ticker,
                run_id=1,
                job_id=2,
                ticker=ticker,
                action="long",
                side="buy",
                order_type="market",
                quantity=10,
                notional_amount=1000.0,
                status="accepted",
                broker_order_id=f"order-{broker_account_id}-{plan_id}",
                client_order_id=f"client-{broker_account_id}-{plan_id}",
            )
        )

    def _position(self, order: BrokerOrderExecution) -> BrokerPosition:
        return self.positions.create(
            BrokerPosition(
                broker_order_execution_id=order.id or 0,
                broker_account_id=order.broker_account_id,
                broker=order.broker,
                account_mode=order.account_mode,
                recommendation_plan_id=order.recommendation_plan_id,
                recommendation_plan_ticker=order.recommendation_plan_ticker,
                run_id=order.run_id,
                job_id=order.job_id,
                ticker=order.ticker,
                action=order.action,
                side=order.side,
                quantity=10,
                current_quantity=10,
                status="open",
                entry_order_id=order.broker_order_id,
                entry_avg_price=100.0,
                entry_filled_at=datetime.now(timezone.utc),
            )
        )

    def test_reconciles_by_broker_account_id_not_ticker_only(self) -> None:
        a = self._position(self._order("etoro-live-a", 1))
        b = self._position(self._order("etoro-live-b", 2))
        service = MultiBrokerReconciliationService(positions=self.positions)

        updated = service.apply_portfolio_snapshot(
            broker_account_id="etoro-live-a",
            open_positions=[{"positionId": "broker-a", "symbol": "AAPL", "quantity": 10}],
            closed_trades=[],
        )

        self.assertEqual(updated[0].id, a.id)
        self.assertEqual(self.positions.get(b.id or 0).status, "open")

    def test_contradictory_missing_open_position_marks_needs_review_for_that_account(self) -> None:
        a = self._position(self._order("etoro-live-a", 1))
        b = self._position(self._order("etoro-live-b", 2))
        service = MultiBrokerReconciliationService(positions=self.positions)

        service.apply_portfolio_snapshot(
            broker_account_id="etoro-live-a",
            open_positions=[],
            closed_trades=[],
        )

        self.assertEqual(self.positions.get(a.id or 0).status, "needs_review")
        self.assertEqual(self.positions.get(b.id or 0).status, "open")

    def test_reconciliation_uncertainty_activates_account_circuit_breaker(self) -> None:
        self._position(self._order("etoro-live-a", 1))
        service = MultiBrokerReconciliationService(positions=self.positions, safety=self.safety)

        service.apply_portfolio_snapshot(
            broker_account_id="etoro-live-a",
            open_positions=[],
            closed_trades=[],
        )

        breaker = self.safety.get_circuit_breaker("etoro-live-a")
        self.assertTrue(breaker.active)
        self.assertEqual(breaker.reason, "broker_reconciliation_uncertainty")

    def test_stale_snapshot_activates_account_circuit_breaker(self) -> None:
        self._position(self._order("etoro-live-a", 1))
        service = MultiBrokerReconciliationService(positions=self.positions, safety=self.safety)

        service.apply_portfolio_snapshot(
            broker_account_id="etoro-live-a",
            open_positions=[{"positionId": "broker-a", "symbol": "AAPL", "quantity": 10}],
            closed_trades=[],
            snapshot_fresh=False,
        )

        breaker = self.safety.get_circuit_breaker("etoro-live-a")
        self.assertTrue(breaker.active)
        self.assertEqual(breaker.reason, "broker_snapshot_stale")

    def test_partial_close_keeps_remaining_exposure_open(self) -> None:
        position = self._position(self._order("etoro-live-a", 1))
        service = MultiBrokerReconciliationService(positions=self.positions)

        service.apply_portfolio_snapshot(
            broker_account_id="etoro-live-a",
            open_positions=[{"positionId": "broker-a", "symbol": "AAPL", "quantity": 4}],
            closed_trades=[
                {"positionId": "broker-a", "symbol": "AAPL", "closedQuantity": 6, "netProfit": 12.5}
            ],
        )

        updated = self.positions.get(position.id or 0)
        self.assertEqual(updated.status, "open")
        self.assertEqual(updated.current_quantity, 4)
        self.assertEqual(updated.realized_pnl, 12.5)

    def test_full_close_maps_profit_to_win(self) -> None:
        position = self._position(self._order("etoro-live-a", 1))
        service = MultiBrokerReconciliationService(positions=self.positions)

        service.apply_portfolio_snapshot(
            broker_account_id="etoro-live-a",
            open_positions=[],
            closed_trades=[
                {
                    "positionId": "broker-a",
                    "symbol": "AAPL",
                    "closedQuantity": 10,
                    "netProfit": 20.0,
                }
            ],
        )

        updated = self.positions.get(position.id or 0)
        self.assertEqual(updated.status, "win")
        self.assertEqual(updated.current_quantity, 0)
        self.assertEqual(updated.realized_pnl, 20.0)


if __name__ == "__main__":
    unittest.main()
