import unittest

from tests.test_etoro_client_readonly import FakeHttpClient, FakeResponse
from trade_proposer_app.services.brokers import redacted_payload
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroReadOnlyBrokerAdapter


class EtoroSecretRedactionTests(unittest.TestCase):
    def test_user_key_is_redacted_from_errors_and_adapter_payloads(self) -> None:
        redacted = redacted_payload({"headers": {"x-user-key": "very-secret-user-key"}})
        self.assertNotIn("very-secret-user-key", str(redacted))

        http = FakeHttpClient(
            [FakeResponse(200, {"x-user-key": "very-secret-user-key", "equity": 1})]
        )
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(api_key="api", user_key="very-secret-user-key", http_client=http)
        )

        result = adapter.get_account_snapshot()

        self.assertNotIn("very-secret-user-key", repr(result))
        self.assertEqual(result.payload["x-user-key"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
