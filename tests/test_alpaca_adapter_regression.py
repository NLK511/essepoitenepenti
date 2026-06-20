import unittest

from trade_proposer_app.services.alpaca_paper_client import AlpacaOrderSubmissionResult
from trade_proposer_app.services.brokers import BrokerAdapterResultStatus, BrokerOrderRequest
from trade_proposer_app.services.brokers.alpaca import AlpacaPaperBrokerAdapter


class StubAlpacaClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_account(self) -> AlpacaOrderSubmissionResult:
        self.calls.append(("get_account", None))
        return AlpacaOrderSubmissionResult(200, {"equity": "1000", "cash": "900"})

    def list_open_orders(self) -> AlpacaOrderSubmissionResult:
        self.calls.append(("list_open_orders", None))
        return AlpacaOrderSubmissionResult(200, {"items": [{"id": "order-1"}]})

    def list_open_positions(self) -> AlpacaOrderSubmissionResult:
        self.calls.append(("list_open_positions", None))
        return AlpacaOrderSubmissionResult(200, {"items": [{"symbol": "AAPL"}]})

    def submit_order(self, payload: dict[str, object]) -> AlpacaOrderSubmissionResult:
        self.calls.append(("submit_order", payload))
        return AlpacaOrderSubmissionResult(200, {"id": "order-1", "status": "accepted"})

    def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
        self.calls.append(("get_order", order_id))
        return AlpacaOrderSubmissionResult(200, {"id": order_id, "status": "filled"})

    def cancel_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
        self.calls.append(("cancel_order", order_id))
        return AlpacaOrderSubmissionResult(200, {"id": order_id, "status": "canceled"})

    def close_position(self, symbol: str) -> AlpacaOrderSubmissionResult:
        self.calls.append(("close_position", symbol))
        return AlpacaOrderSubmissionResult(200, {"symbol": symbol, "status": "accepted"})


class AlpacaAdapterRegressionTests(unittest.TestCase):
    def test_alpaca_submit_payload_matches_existing_shape(self) -> None:
        client = StubAlpacaClient()
        adapter = AlpacaPaperBrokerAdapter(client=client)  # type: ignore[arg-type]

        result = adapter.submit_order(
            BrokerOrderRequest(
                client_order_id="client-1",
                symbol="AAPL",
                side="buy",
                order_type="limit",
                quantity=10,
                time_in_force="gtc",
                stop_loss=95.0,
                take_profit=110.0,
                payload={"limit_price": 100.0},
            )
        )

        self.assertEqual(result.status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(result.broker_order_id, "order-1")
        self.assertEqual(
            client.calls[0],
            (
                "submit_order",
                {
                    "symbol": "AAPL",
                    "qty": 10,
                    "side": "buy",
                    "type": "limit",
                    "time_in_force": "gtc",
                    "limit_price": 100.0,
                    "order_class": "bracket",
                    "take_profit": {"limit_price": 110.0},
                    "stop_loss": {"stop_price": 95.0},
                    "client_order_id": "client-1",
                },
            ),
        )

    def test_alpaca_submit_prefers_normalized_payload_protective_levels(self) -> None:
        client = StubAlpacaClient()
        adapter = AlpacaPaperBrokerAdapter(client=client)  # type: ignore[arg-type]

        adapter.submit_order(
            BrokerOrderRequest(
                client_order_id="client-1",
                symbol="AMAT",
                side="buy",
                order_type="limit",
                quantity=1,
                time_in_force="gtc",
                stop_loss=578.1666,
                take_profit=630.1101,
                payload={
                    "limit_price": 597.29,
                    "stop_loss": {"stop_price": 578.17},
                    "take_profit": {"limit_price": 630.11},
                },
            )
        )

        submitted = client.calls[0][1]
        assert isinstance(submitted, dict)
        self.assertEqual(submitted["limit_price"], 597.29)
        self.assertEqual(submitted["stop_loss"], {"stop_price": 578.17})
        self.assertEqual(submitted["take_profit"], {"limit_price": 630.11})

    def test_alpaca_lookup_cancel_close_and_snapshots_normalize(self) -> None:
        client = StubAlpacaClient()
        adapter = AlpacaPaperBrokerAdapter(client=client)  # type: ignore[arg-type]

        self.assertTrue(adapter.validate_credentials().valid)
        self.assertEqual(adapter.get_capabilities().broker, "alpaca")
        self.assertEqual(adapter.resolve_instrument("aapl").instrument_id, "AAPL")
        self.assertEqual(adapter.get_account_snapshot().account.equity, 1000.0)
        self.assertEqual(adapter.get_open_orders().items[0]["id"], "order-1")
        self.assertEqual(adapter.get_open_positions().items[0]["symbol"], "AAPL")
        self.assertEqual(adapter.lookup_order("order-1").broker_status, "filled")
        self.assertEqual(adapter.cancel_order("order-1").broker_status, "canceled")
        self.assertEqual(adapter.close_position("AAPL").broker_status, "accepted")
        self.assertEqual(adapter.get_trade_history().status, BrokerAdapterResultStatus.SUCCESS)


if __name__ == "__main__":
    unittest.main()
