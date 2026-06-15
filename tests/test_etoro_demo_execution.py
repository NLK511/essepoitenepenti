import unittest
from dataclasses import replace

from tests.test_etoro_client_readonly import FakeResponse
from trade_proposer_app.services.brokers import BrokerAdapterResultStatus, BrokerOrderRequest
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
        self.assertTrue(str(call["url"]).endswith("/api/v2/trading/demo/execution/orders"))
        self.assertEqual(
            call["json"],
            {
                "action": "open",
                "transaction": "buy",
                "symbol": "AAPL",
                "instrumentId": "123",
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


if __name__ == "__main__":
    unittest.main()
