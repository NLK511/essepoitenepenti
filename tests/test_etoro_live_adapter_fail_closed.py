import unittest

from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerOrderRequest,
    BrokerProtectionAmendRequest,
)
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroLiveBrokerAdapter


class ExplodingHttpClient:
    def request(self, *args, **kwargs):
        raise AssertionError("live mutation adapter must not call HTTP while disabled")


class EtoroLiveAdapterFailClosedTests(unittest.TestCase):
    def _adapter(self) -> EtoroLiveBrokerAdapter:
        return EtoroLiveBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="user", http_client=ExplodingHttpClient())
        )

    def _request(self) -> BrokerOrderRequest:
        return BrokerOrderRequest(
            client_order_id="live-request-1",
            symbol="AAPL",
            instrument_id="123",
            side="buy",
            order_type="market",
            notional_amount=25.0,
            leverage=1,
            stop_loss=95.0,
            take_profit=110.0,
        )

    def test_live_submit_cancel_close_and_amend_fail_closed_without_http(self) -> None:
        adapter = self._adapter()

        submit = adapter.submit_order(self._request())
        cancel = adapter.cancel_order("order-1")
        close = adapter.close_position("position-1")
        amend = adapter.amend_position_protection(
            BrokerProtectionAmendRequest(broker_order_id="position-1", stop_loss=96.0)
        )

        self.assertEqual(submit.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(cancel.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(close.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(amend.status, BrokerAdapterResultStatus.REJECTED)
        self.assertEqual(submit.message, "etoro_live_mutation_disabled")
        self.assertEqual(cancel.message, "etoro_live_mutation_disabled")
        self.assertEqual(close.message, "etoro_live_mutation_disabled")
        self.assertEqual(amend.message, "etoro_live_mutation_disabled")

    def test_live_capabilities_are_explicitly_live_but_mutations_disabled(self) -> None:
        capabilities = self._adapter().get_capabilities()

        self.assertEqual(capabilities.broker, "etoro")
        self.assertEqual(capabilities.account_mode, "live")
        self.assertFalse(capabilities.raw_payload["live_mutations_enabled"])


if __name__ == "__main__":
    unittest.main()
