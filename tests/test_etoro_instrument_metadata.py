import unittest

from tests.test_etoro_client_readonly import FakeHttpClient, FakeResponse
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroReadOnlyBrokerAdapter


class EtoroInstrumentMetadataTests(unittest.TestCase):
    def test_resolves_symbol_to_instrument_metadata_and_caches(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(
                    200,
                    {
                        "instruments": [
                            {
                                "symbol": "AAPL",
                                "instrumentId": 123,
                                "productType": "stock",
                                "currency": "usd",
                                "tradable": True,
                                "minAmount": 10,
                                "supportsStopLoss": True,
                                "supportsTakeProfit": True,
                            }
                        ]
                    },
                ),
            ]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=http)
        )

        first = adapter.resolve_instrument("AAPL")
        second = adapter.resolve_instrument("AAPL")

        self.assertEqual(first.instrument_id, "123")
        self.assertEqual(first.product_type, "stock")
        self.assertTrue(first.tradable)
        self.assertEqual(second.instrument_id, "123")
        self.assertEqual(len(http.calls), 1)

    def test_ambiguous_cfd_underlying_mapping_blocks(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(
                    200,
                    {
                        "instruments": [
                            {
                                "symbol": "AAPL",
                                "instrumentId": 123,
                                "productType": "stock",
                                "tradable": True,
                            },
                            {
                                "symbol": "AAPL",
                                "instrumentId": 456,
                                "productType": "cfd",
                                "tradable": True,
                            },
                        ]
                    },
                ),
            ]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=http)
        )

        instrument = adapter.resolve_instrument("AAPL")

        self.assertTrue(instrument.ambiguous)
        self.assertFalse(instrument.tradable)

    def test_unsupported_market_currency_or_constraints_block(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(
                    200,
                    {
                        "instruments": [
                            {
                                "symbol": "ABC",
                                "instrumentId": 1,
                                "productType": "crypto",
                                "currency": "eur",
                                "tradable": True,
                                "minAmount": 5000,
                            }
                        ]
                    },
                ),
            ]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=http)
        )

        instrument = adapter.resolve_instrument("ABC")

        self.assertFalse(instrument.tradable)
        self.assertEqual(instrument.currency, "eur")
        self.assertEqual(instrument.product_type, "crypto")


if __name__ == "__main__":
    unittest.main()
