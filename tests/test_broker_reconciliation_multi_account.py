import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution, BrokerPosition
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.services.broker_reconciliation import BrokerReconciliationService
from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerOrderResult,
    BrokerPortfolioResult,
    BrokerTradeHistoryResult,
)
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
                entry_filled_at=datetime.now(UTC),
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

    def test_etoro_demo_order_lookup_updates_order_and_position_rows(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="submitted",
                broker_order_id="368528997",
                client_order_id="client-pypl",
            )
        )
        adapter = _EtoroLookupAdapter(
            {
                "orderId": 368528997,
                "status": {"name": "Filled"},
                "positionExecutions": [
                    {
                        "positionId": 3567506772,
                        "state": "open",
                        "remainingUnits": 0.444919,
                        "stopLossRate": 55.4,
                        "takeProfitRate": 59.69,
                        "openingData": {
                            "executionTime": "2026-07-24T12:19:19.740Z",
                            "avgPrice": 56.18,
                        },
                    }
                ],
            }
        )

        updated = BrokerReconciliationService(self.session)._sync_etoro_demo_order(
            order, adapter
        )
        position = self.positions.get_by_order_execution_id(order.id or 0)

        self.assertEqual(updated.status, "filled")
        self.assertIsNotNone(updated.filled_at)
        self.assertIsNotNone(position)
        self.assertEqual(position.status, "open")
        self.assertEqual(position.entry_order_id, "3567506772")
        self.assertEqual(position.entry_avg_price, 56.18)
        self.assertEqual(position.quantity, 1)
        self.assertEqual(position.current_quantity, 1)
        self.assertEqual(position.unit_quantity, 0.444919)
        self.assertEqual(position.current_unit_quantity, 0.444919)
        self.assertEqual(position.stop_loss_order_price, 55.4)
        self.assertEqual(position.take_profit_order_price, 59.69)

    def test_etoro_closed_position_execution_is_not_counted_as_active(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="filled",
                broker_order_id="368528997",
                client_order_id="client-pypl",
            )
        )
        adapter = _EtoroLookupAdapter(
            {
                "orderId": 368528997,
                "status": {"name": "Filled"},
                "positionExecutions": [
                    {
                        "positionId": 3567506772,
                        "state": "closed",
                        "remainingUnits": 0.444919,
                        "openingData": {
                            "executionTime": "2026-07-24T12:19:19.740Z",
                            "units": 0.444919,
                            "avgPrice": 56.18,
                        },
                    }
                ],
            }
        )

        BrokerReconciliationService(self.session)._sync_etoro_demo_order(order, adapter)
        position = self.positions.get_by_order_execution_id(order.id or 0)

        self.assertIsNotNone(position)
        self.assertEqual(position.status, "needs_review")
        self.assertEqual(position.unit_quantity, 0.444919)
        self.assertEqual(position.current_unit_quantity, 0.0)
        self.assertEqual(position.current_quantity, 0)

    def test_etoro_close_order_lookup_updates_exit_fields_when_exit_id_exists(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="AAPL",
                run_id=20,
                job_id=30,
                ticker="AAPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="filled",
                broker_order_id="368568527",
                client_order_id="client-aapl",
            )
        )
        position = self.positions.create(
            BrokerPosition(
                broker_order_execution_id=order.id or 0,
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="AAPL",
                run_id=20,
                job_id=30,
                ticker="AAPL",
                action="long",
                side="buy",
                quantity=1,
                current_quantity=1,
                unit_quantity=0.077521,
                current_unit_quantity=0.077521,
                status="closing",
                entry_order_id="3567504740",
                entry_avg_price=322.56,
                exit_order_id="368563966",
            )
        )
        adapter = _EtoroLookupAdapter(
            {},
            close_order_payload={
                "orderID": 368563966,
                "statusID": 3,
                "positions": [
                    {
                        "positionID": 3567504740,
                        "occurred": "2026-07-24T11:49:02.023Z",
                        "rate": 322.35,
                        "units": 0.077521,
                        "amount": 25.0,
                    }
                ],
            },
        )

        updated = BrokerReconciliationService(self.session)._sync_etoro_demo_close_order(
            position, adapter
        )

        self.assertEqual(updated.status, "needs_review")
        self.assertEqual(updated.exit_avg_price, 322.35)
        self.assertEqual(
            updated.exit_filled_at,
            datetime(2026, 7, 24, 11, 49, 2, 23000, tzinfo=UTC),
        )
        self.assertEqual(updated.current_quantity, 0)
        self.assertEqual(updated.current_unit_quantity, 0.0)
        self.assertIsNone(updated.realized_pnl)

    def test_etoro_portfolio_absence_marks_position_needs_review_without_history(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="filled",
                broker_order_id="368528997",
                client_order_id="client-pypl",
            )
        )
        position = self.positions.create(
            BrokerPosition(
                broker_order_execution_id=order.id or 0,
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                quantity=1,
                current_quantity=1,
                unit_quantity=0.444919,
                current_unit_quantity=0.444919,
                status="open",
                entry_order_id="3567506772",
                entry_avg_price=56.18,
            )
        )
        adapter = _EtoroLookupAdapter(
            {},
            open_positions=[
                {"positionID": 111, "instrumentID": 1, "remainingUnits": 0.5},
            ],
            trade_history_status=BrokerAdapterResultStatus.NOT_FOUND,
        )

        summary = (
            BrokerReconciliationService(self.session)._sync_etoro_demo_positions_from_portfolio(
                "etoro-demo-main", adapter
            )
        )
        updated = self.positions.get(position.id or 0)

        self.assertEqual(summary["closed_without_confirmed_pnl"], 1)
        self.assertEqual(updated.status, "needs_review")
        self.assertEqual(updated.current_quantity, 0)
        self.assertEqual(updated.current_unit_quantity, 0.0)
        self.assertIn("portfolio_absent", updated.error_message or "")
        self.assertIsNone(updated.realized_pnl)

    def test_etoro_portfolio_absence_uses_trade_history_pnl_when_matched(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="filled",
                broker_order_id="368528997",
                client_order_id="client-pypl",
            )
        )
        position = self.positions.create(
            BrokerPosition(
                broker_order_execution_id=order.id or 0,
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                quantity=1,
                current_quantity=1,
                unit_quantity=0.444919,
                current_unit_quantity=0.444919,
                status="open",
                entry_order_id="3567506772",
                entry_avg_price=56.18,
                stop_loss_order_price=55.4,
                raw_broker_payload={
                    "position_execution": {"initialExposureAccountCurrency": 24.99554942}
                },
            )
        )
        adapter = _EtoroLookupAdapter(
            {},
            open_positions=[],
            trade_history=[
                {
                    "positionID": 3567506772,
                    "closeDateTime": "2026-08-13T19:29:59.000Z",
                    "closeRate": 58.4,
                    "closedUnits": 0.444919,
                    "netProfit": 0.98,
                }
            ],
        )

        summary = (
            BrokerReconciliationService(self.session)._sync_etoro_demo_positions_from_portfolio(
                "etoro-demo-main", adapter
            )
        )
        updated = self.positions.get(position.id or 0)

        self.assertEqual(summary["closed_with_history_pnl"], 1)
        self.assertEqual(summary["closed_without_confirmed_pnl"], 0)
        self.assertEqual(updated.status, "win")
        self.assertEqual(updated.current_quantity, 0)
        self.assertEqual(updated.current_unit_quantity, 0.0)
        self.assertEqual(updated.realized_pnl, 0.98)
        self.assertEqual(updated.exit_avg_price, 58.4)
        self.assertEqual(
            updated.exit_filled_at,
            datetime(2026, 8, 13, 19, 29, 59, tzinfo=UTC),
        )
        self.assertIsNotNone(updated.realized_return_pct)
        self.assertIn("trade_history_position", updated.raw_broker_payload)

    def test_etoro_trade_history_is_not_matched_by_ticker_only(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="filled",
                broker_order_id="368528997",
                client_order_id="client-pypl",
            )
        )
        position = self.positions.create(
            BrokerPosition(
                broker_order_execution_id=order.id or 0,
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                quantity=1,
                current_quantity=1,
                unit_quantity=0.444919,
                current_unit_quantity=0.444919,
                status="open",
                entry_order_id="3567506772",
                entry_avg_price=56.18,
            )
        )
        adapter = _EtoroLookupAdapter(
            {},
            open_positions=[],
            trade_history=[{"symbol": "PYPL", "netProfit": 9.99}],
        )

        BrokerReconciliationService(self.session)._sync_etoro_demo_positions_from_portfolio(
            "etoro-demo-main", adapter
        )
        updated = self.positions.get(position.id or 0)

        self.assertEqual(updated.status, "needs_review")
        self.assertIsNone(updated.realized_pnl)

    def test_etoro_sparse_portfolio_row_does_not_clear_known_units(self) -> None:
        order = self.orders.create(
            BrokerOrderExecution(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="MRK",
                run_id=20,
                job_id=30,
                ticker="MRK",
                action="long",
                side="buy",
                order_type="market",
                quantity=0,
                notional_amount=25.0,
                status="filled",
                broker_order_id="368568636",
                client_order_id="client-mrk",
            )
        )
        position = self.positions.create(
            BrokerPosition(
                broker_order_execution_id=order.id or 0,
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=10,
                recommendation_plan_ticker="MRK",
                run_id=20,
                job_id=30,
                ticker="MRK",
                action="long",
                side="buy",
                quantity=1,
                current_quantity=1,
                unit_quantity=0.190432,
                current_unit_quantity=0.190432,
                status="open",
                entry_order_id="3567507810",
                entry_avg_price=131.24,
            )
        )
        adapter = _EtoroLookupAdapter(
            {},
            open_positions=[
                {"positionID": 3567507810, "instrumentID": 1027},
            ],
        )

        BrokerReconciliationService(self.session)._sync_etoro_demo_positions_from_portfolio(
            "etoro-demo-main", adapter
        )
        updated = self.positions.get(position.id or 0)

        self.assertEqual(updated.status, "open")
        self.assertEqual(updated.current_quantity, 1)
        self.assertEqual(updated.current_unit_quantity, 0.190432)

    def test_sync_open_orders_skips_disabled_broker_account_orders(self) -> None:
        accounts = BrokerAccountRepository(self.session)
        accounts.create(
            BrokerAccount(
                broker_account_id="alpaca-paper-default",
                broker="alpaca",
                account_mode="paper",
                account_label="Alpaca Paper",
                enabled=False,
            )
        )
        self.orders.create(
            BrokerOrderExecution(
                broker_account_id="alpaca-paper-default",
                broker="alpaca",
                account_mode="paper",
                recommendation_plan_id=10,
                recommendation_plan_ticker="PYPL",
                run_id=20,
                job_id=30,
                ticker="PYPL",
                action="long",
                side="buy",
                order_type="market",
                quantity=1,
                notional_amount=25.0,
                status="open",
                broker_order_id="old-alpaca-order",
                client_order_id="old-alpaca-client-order",
            )
        )

        with patch(
            "trade_proposer_app.services.broker_reconciliation.create_order_execution_service"
        ) as legacy_factory:
            outcome = BrokerReconciliationService(self.session).sync_open_orders()

        legacy_factory.assert_called_once()
        self.assertEqual(outcome.summary["synced_count"], 0)
        self.assertEqual(outcome.summary["skipped_count"], 1)
        self.assertEqual(outcome.summary["failed_count"], 0)


class _EtoroLookupAdapter:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        close_order_payload: dict[str, object] | None = None,
        open_positions: list[dict[str, object]] | None = None,
        trade_history: list[dict[str, object]] | None = None,
        trade_history_status: BrokerAdapterResultStatus = BrokerAdapterResultStatus.SUCCESS,
    ) -> None:
        self.payload = payload
        self.close_order_payload = close_order_payload or {}
        self.open_positions = open_positions or []
        self.trade_history = trade_history or []
        self.trade_history_status = trade_history_status

    def lookup_order(self, order_id=None, client_order_id=None):
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="lookup_order",
            client_request_id=str(order_id or client_order_id),
            payload=self.payload,
        )

    def lookup_close_order(self, order_id):
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="lookup_close_order",
            client_request_id=str(order_id),
            payload=self.close_order_payload,
        )

    def get_open_positions(self):
        return BrokerPortfolioResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="get_open_positions",
            client_request_id="portfolio",
            items=self.open_positions,
        )

    def get_trade_history(self):
        return BrokerTradeHistoryResult(
            status=self.trade_history_status,
            operation="get_trade_history",
            client_request_id="history",
            trades=self.trade_history,
            message="history unavailable" if self.trade_history_status else "",
        )


if __name__ == "__main__":
    unittest.main()
