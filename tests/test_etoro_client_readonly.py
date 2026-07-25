import unittest

from trade_proposer_app.services.brokers import BrokerAdapterResultStatus
from trade_proposer_app.services.brokers.etoro import (
    EtoroClient,
    EtoroClientError,
    EtoroReadOnlyBrokerAdapter,
)


class FakeResponse:
    def __init__(
        self, status_code: int, payload: object, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self) -> object:
        return self._payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, *, headers=None, json=None, params=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json": json,
                "params": params,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


class EtoroClientReadOnlyTests(unittest.TestCase):
    def test_sends_required_headers_and_unique_request_id(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"positions": [], "orders": []}),
                FakeResponse(200, {"positions": [], "orders": []}),
            ]
        )
        client = EtoroClient(api_key="api-key", user_key="user-key", http_client=http)

        client.get_portfolio()
        client.get_portfolio()

        first_headers = http.calls[0]["headers"]
        second_headers = http.calls[1]["headers"]
        self.assertEqual(first_headers["x-api-key"], "api-key")
        self.assertEqual(first_headers["x-user-key"], "user-key")
        self.assertTrue(first_headers["x-request-id"])
        self.assertNotEqual(first_headers["x-request-id"], second_headers["x-request-id"])

    def test_maps_auth_and_rate_limit_errors(self) -> None:
        auth_client = EtoroClient(
            api_key="api-key",
            user_key="user-key",
            http_client=FakeHttpClient([FakeResponse(403, {"message": "forbidden"})]),
        )
        with self.assertRaises(EtoroClientError) as auth_error:
            auth_client.get_portfolio()
        self.assertEqual(auth_error.exception.status_code, 403)
        self.assertEqual(auth_error.exception.error_type, "permission_denied")

        rate_client = EtoroClient(
            api_key="api-key",
            user_key="user-key",
            http_client=FakeHttpClient(
                [FakeResponse(429, {"message": "slow"}, {"retry-after": "7"})]
            ),
        )
        with self.assertRaises(EtoroClientError) as rate_error:
            rate_client.get_portfolio()
        self.assertEqual(rate_error.exception.error_type, "rate_limited")
        self.assertEqual(rate_error.exception.retry_after_seconds, 7.0)

    def test_get_instrument_candles_uses_documented_market_data_path(self) -> None:
        http = FakeHttpClient([FakeResponse(200, {"candles": []})])
        client = EtoroClient(api_key="api-key", user_key="user-key", http_client=http)

        client.get_instrument_candles(
            instrument_id=1001,
            direction="asc",
            interval="OneMinute",
            candles_count=100,
        )

        self.assertEqual(
            "https://public-api.etoro.com/api/v1/market-data/instruments/1001/history/candles/asc/OneMinute/100",
            http.calls[0]["url"],
        )

    def test_adapter_parses_portfolio_pnl_and_history_fixtures(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(
                    200,
                    {"equity": 1000, "cash": 900, "positions": [{"symbol": "AAPL"}], "orders": []},
                ),
                FakeResponse(200, {"positions": [{"symbol": "AAPL"}], "orders": [{"id": "o1"}]}),
                FakeResponse(200, {"trades": [{"symbol": "AAPL", "netProfit": 12.0}]}),
            ]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api-key", user_key="user-key", http_client=http)
        )

        snapshot = adapter.get_account_snapshot()
        positions = adapter.get_open_positions()
        history = adapter.get_trade_history()

        self.assertEqual(snapshot.status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(snapshot.account.equity, 1000.0)
        self.assertEqual(positions.items[0]["symbol"], "AAPL")
        self.assertEqual(history.trades[0]["netProfit"], 12.0)


if __name__ == "__main__":
    unittest.main()
