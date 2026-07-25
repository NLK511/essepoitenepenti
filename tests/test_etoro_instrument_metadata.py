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

    def test_resolves_current_search_shape_through_display_data(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"items": [{"instrumentId": 1001}, {"instrumentId": 15569}]}),
                FakeResponse(
                    200,
                    {
                        "instrumentDisplayDatas": [
                            {
                                "instrumentID": 1001,
                                "symbolFull": "AAPL",
                                "instrumentDisplayName": "Apple",
                                "priceSource": "NASDAQ",
                            }
                        ]
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "instrumentDisplayDatas": [
                            {
                                "instrumentID": 15569,
                                "symbolFull": "AAPL.24-7",
                                "instrumentDisplayName": "Apple 24/7",
                                "priceSource": "eToro",
                            }
                        ]
                    },
                ),
            ]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=http)
        )

        instrument = adapter.resolve_instrument("AAPL")

        self.assertEqual(instrument.instrument_id, "1001")
        self.assertTrue(instrument.tradable)
        self.assertEqual(instrument.exchange, "NASDAQ")
        self.assertEqual([call["method"] for call in http.calls], ["GET", "GET", "GET"])
        self.assertEqual(
            http.calls[0]["params"],
            {"fields": "instrumentId", "internalSymbolFull": "AAPL", "pageSize": 25},
        )

    def test_resolves_safe_symbol_punctuation_alias(self) -> None:
        http = FakeHttpClient(
            [
                FakeResponse(200, {"items": []}),
                FakeResponse(200, {"items": [{"instrumentId": 321}]}),
                FakeResponse(
                    200,
                    {
                        "instrumentDisplayDatas": [
                            {
                                "instrumentID": 321,
                                "symbolFull": "BRK.B",
                                "instrumentDisplayName": "Berkshire Hathaway",
                                "priceSource": "NYSE",
                            }
                        ]
                    },
                ),
            ]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=http)
        )

        instrument = adapter.resolve_instrument("BRK-B")

        self.assertEqual(instrument.instrument_id, "321")
        self.assertFalse(instrument.ambiguous)
        self.assertEqual(
            [
                call["params"]["internalSymbolFull"]
                for call in http.calls
                if call["params"] and "internalSymbolFull" in call["params"]
            ],
            ["BRK-B", "BRK.B"],
        )

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
