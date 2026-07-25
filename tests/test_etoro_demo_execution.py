import unittest
from dataclasses import replace

from tests.test_etoro_client_readonly import FakeResponse
from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerOrderRequest,
    BrokerProtectionAmendRequest,
)
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroDemoBrokerAdapter


class FakeHttpClient:
    def __init__(
        self, responses: list[FakeResponse] | None = None, error: Exception | None = None
    ) -> None:
        self.responses = responses or []
        self.error = error
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, *, headers=None, json=None, params=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "json": json, "params": params}
        )
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class EtoroDemoExecutionTests(unittest.TestCase):
    def _adapter(self, http: FakeHttpClient) -> EtoroDemoBrokerAdapter:
        return EtoroDemoBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=http)
        )

    def _request(self) -> BrokerOrderRequest:
        return BrokerOrderRequest(
            client_order_id="request-1",
            symbol="AAPL",
            instrument_id="123",
            side="buy",
            order_type="market",
            notional_amount=25.0,
            leverage=1,
            stop_loss=95.0,
            take_profit=110.0,
        )

    def test_constructs_demo_open_order_payload_for_valid_long(self) -> None:
        http = FakeHttpClient([FakeResponse(200, {"orderId": "order-1", "status": "accepted"})])
        adapter = self._adapter(http)

        result = adapter.submit_order(self._request())

        self.assertEqual(result.status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(result.broker_order_id, "order-1")
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(str(call["url"]).endswith("/api/v2/trading/execution/demo/orders"))
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(
            call["json"],
            {
                "action": "open",
                "transaction": "buy",
                "instrumentId": "123",
                "settlementType": "real",
                "orderType": "mkt",
                "leverage": 1,
                "amount": 25.0,
                "orderCurrency": "usd",
                "stopLossRate": 95.0,
                "takeProfitRate": 110.0,
                "stopLossType": "fixed",
            },
        )

    def test_rejects_unsupported_demo_order_without_http_call(self) -> None:
        http = FakeHttpClient([])
        adapter = self._adapter(http)

        result = adapter.submit_order(replace(self._request(), side="sell"))
        missing_levels = adapter.submit_order(replace(self._request(), stop_loss=None))
        leveraged = adapter.submit_order(replace(self._request(), leverage=2))

        self.assertEqual(result.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(missing_levels.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(leveraged.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(http.calls, [])

    def test_broker_rejection_and_timeout_are_safe_results(self) -> None:
        rejected = self._adapter(
            FakeHttpClient([FakeResponse(400, {"message": "bad stops"})])
        ).submit_order(self._request())
        ambiguous = self._adapter(FakeHttpClient(error=TimeoutError("timed out"))).submit_order(
            self._request()
        )

        self.assertEqual(rejected.status, BrokerAdapterResultStatus.REJECTED)
        self.assertIn("bad stops", str(rejected.payload))
        self.assertEqual(ambiguous.status, BrokerAdapterResultStatus.AMBIGUOUS)
        self.assertTrue(ambiguous.needs_review)

    def test_lookup_cancel_and_close_demo_order_lifecycle_calls(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"orderId": "order-1", "status": "pending"}),
                FakeResponse(200, {"orderId": "order-1", "status": "canceled"}),
                FakeResponse(200, {"positionId": "position-1", "status": "closing"}),
            ]
        )
        adapter = self._adapter(http)

        lookup = adapter.lookup_order("order-1")
        canceled = adapter.cancel_order("order-1")
        closed = adapter.close_position("position-1")

        self.assertEqual(lookup.broker_status, "pending")
        self.assertEqual(canceled.broker_status, "canceled")
        self.assertEqual(closed.broker_status, "closing")
        self.assertEqual([call["method"] for call in http.calls], ["GET", "DELETE", "POST"])
        self.assertTrue(
            str(http.calls[0]["url"]).endswith("/api/v2/trading/info/demo/orders:lookup")
        )
        self.assertTrue(
            str(http.calls[1]["url"]).endswith("/api/v2/trading/execution/demo/orders/order-1")
        )
        self.assertTrue(
            str(http.calls[2]["url"]).endswith(
                "/api/v1/trading/execution/demo/market-close-orders/positions/position-1"
            )
        )

    def test_demo_client_uses_current_read_precheck_and_close_order_paths(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"items": []}),
                FakeResponse(200, {"eligible": True}),
                FakeResponse(200, {"costs": []}),
                FakeResponse(200, {"positions": []}),
                FakeResponse(200, {"equity": 1000}),
                FakeResponse(200, {"orders": []}),
                FakeResponse(200, {"closed": True}),
                FakeResponse(200, {"history": []}),
            ]
        )
        client = EtoroClient(api_key="api", user_key="user", http_client=http)

        client.get_market_rates([123])
        client.check_demo_eligibility({"instrumentIds": [123]})
        client.get_demo_costs({"instrumentId": 123, "amount": 25})
        client.get_demo_portfolio()
        client.get_demo_pnl()
        client.get_demo_aggregate_portfolio()
        client.lookup_demo_close_order("close-1")
        client.get_demo_trade_history()

        self.assertEqual(
            [str(call["url"]).replace("https://public-api.etoro.com", "") for call in http.calls],
            [
                "/api/v1/market-data/instruments/rates",
                "/api/v2/trading/info/demo/eligibility",
                "/api/v2/trading/info/demo/costs",
                "/api/v1/trading/info/demo/portfolio",
                "/api/v1/trading/info/demo/pnl",
                "/api/v1/trading/info/demo/aggregate-portfolio",
                "/api/v1/trading/info/demo/close-orders/close-1",
                "/api/v1/trading/info/trade/demo/history",
            ],
        )
        self.assertEqual(http.calls[0]["params"], {"instrumentIds": "123"})
        self.assertEqual(http.calls[1]["headers"]["Content-Type"], "application/json")
        self.assertEqual(http.calls[2]["headers"]["Content-Type"], "application/json")

    def test_demo_portfolio_methods_read_nested_client_portfolio(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"clientPortfolio": {"credit": 1000.0}}),
                FakeResponse(200, {"clientPortfolio": {"orders": [{"orderID": 1}]}}),
                FakeResponse(
                    200,
                    {"clientPortfolio": {"positions": [{"positionID": 2, "instrumentID": 1484}]}},
                ),
            ]
        )
        adapter = self._adapter(http)

        snapshot = adapter.get_account_snapshot()
        orders = adapter.get_open_orders()
        positions = adapter.get_open_positions()

        self.assertEqual(snapshot.account.cash, 1000.0)
        self.assertEqual(orders.items, [{"orderID": 1}])
        self.assertEqual(positions.items, [{"positionID": 2, "instrumentID": 1484}])

    def test_demo_client_uses_one_order_lookup_identifier_and_instrument_id_on_close(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"orderId": "order-1", "status": "filled"}),
                FakeResponse(200, {"positionId": "position-1", "status": "closing"}),
            ]
        )
        client = EtoroClient(api_key="api", user_key="user", http_client=http)

        client.lookup_demo_order(order_id="order-1", reference_id="ignored")
        client.close_demo_position("position-1", instrument_id=1001)

        self.assertEqual(http.calls[0]["params"], {"orderId": "order-1"})
        self.assertEqual(
            http.calls[1]["json"], {"UnitsToDeduct": None, "InstrumentID": 1001}
        )

    def test_demo_protection_amend_uses_current_position_patch_path(self) -> None:
        http = FakeHttpClient(
            [FakeResponse(200, {"positionId": "position-1", "status": "updated"})]
        )
        adapter = self._adapter(http)

        result = adapter.amend_position_protection(
            BrokerProtectionAmendRequest(
                broker_order_id="position-1",
                client_order_id="amend-1",
                symbol="AAPL",
                stop_loss=96.0,
                take_profit=111.0,
            )
        )

        self.assertEqual(result.status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(result.broker_position_id, "position-1")
        self.assertEqual(http.calls[0]["method"], "PATCH")
        self.assertTrue(
            str(http.calls[0]["url"]).endswith("/api/v2/trading/demo/positions/position-1")
        )
        self.assertEqual(
            http.calls[0]["json"],
            {"stopLossRate": 96.0, "takeProfitRate": 111.0},
        )


if __name__ == "__main__":
    unittest.main()
