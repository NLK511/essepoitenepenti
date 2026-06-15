import unittest

from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerCapabilities,
    BrokerCredentialValidation,
    BrokerInstrument,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerProtectionAmendRequest,
    FakeBrokerAdapter,
    redacted_payload,
)


class BrokerAdapterContractTests(unittest.TestCase):
    def test_fake_adapter_covers_core_lifecycle_calls(self) -> None:
        adapter = FakeBrokerAdapter(
            capabilities=BrokerCapabilities(
                broker="fake",
                account_mode="paper",
                supported_actions=["long"],
                supported_order_types=["market"],
                supports_cancel=True,
                supports_close_position=True,
            )
        )

        self.assertTrue(adapter.validate_credentials().valid)
        self.assertEqual(adapter.get_capabilities().broker, "fake")
        self.assertEqual(adapter.resolve_instrument("AAPL").instrument_id, "AAPL")
        self.assertEqual(adapter.get_account_snapshot().status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(adapter.get_open_orders().status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(adapter.get_open_positions().status, BrokerAdapterResultStatus.SUCCESS)

        submitted = adapter.submit_order(
            BrokerOrderRequest(
                client_order_id="client-1",
                symbol="AAPL",
                side="buy",
                order_type="market",
                notional_amount=25.0,
            )
        )
        self.assertEqual(submitted.status, BrokerAdapterResultStatus.SUCCESS)
        self.assertEqual(
            adapter.lookup_order(submitted.broker_order_id or "").broker_order_id,
            submitted.broker_order_id,
        )
        self.assertEqual(
            adapter.cancel_order(submitted.broker_order_id or "").status,
            BrokerAdapterResultStatus.SUCCESS,
        )
        self.assertEqual(
            adapter.close_position("position-1").status, BrokerAdapterResultStatus.SUCCESS
        )
        unsupported_amend = adapter.amend_position_protection(
            BrokerProtectionAmendRequest(broker_order_id=submitted.broker_order_id or "")
        )
        self.assertEqual(unsupported_amend.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(unsupported_amend.message, "broker_amend_protection_unsupported")
        self.assertEqual(adapter.get_trade_history().status, BrokerAdapterResultStatus.SUCCESS)

    def test_ambiguous_result_is_explicit_not_success(self) -> None:
        result = BrokerOrderResult.ambiguous(
            operation="submit_order",
            client_request_id="request-1",
            message="timeout after submit",
        )

        self.assertEqual(result.status, BrokerAdapterResultStatus.AMBIGUOUS)
        self.assertFalse(result.is_success)
        self.assertTrue(result.needs_review)

    def test_secret_redaction_handles_nested_payloads_and_repr(self) -> None:
        payload = {
            "x-user-key": "secret-user",
            "nested": {"api_secret": "secret-api", "safe": "ok"},
            "items": [{"token": "secret-token"}],
        }

        redacted = redacted_payload(payload)

        self.assertEqual(redacted["x-user-key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["api_secret"], "[REDACTED]")
        self.assertEqual(redacted["items"][0]["token"], "[REDACTED]")
        rendered = repr(BrokerCredentialValidation(valid=False, raw_payload=redacted))
        self.assertNotIn("secret-user", rendered)
        self.assertNotIn("secret-api", rendered)
        self.assertNotIn("secret-token", rendered)

    def test_capabilities_block_when_ambiguous(self) -> None:
        instrument = BrokerInstrument(
            symbol="AAPL",
            instrument_id="123",
            tradable=False,
            ambiguous=True,
            product_type="cfd",
        )

        self.assertTrue(instrument.ambiguous)
        self.assertFalse(instrument.tradable)


if __name__ == "__main__":
    unittest.main()
