import unittest

from tests.test_etoro_client_readonly import FakeHttpClient, FakeResponse
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroReadOnlyBrokerAdapter


class EtoroPermissionsTests(unittest.TestCase):
    def test_real_trading_permission_validation(self) -> None:
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(
                api_key="api",
                user_key="user",
                http_client=FakeHttpClient(
                    [FakeResponse(200, {"permissions": ["read", "demo_trading"], "mode": "demo"})]
                ),
            )
        )

        validation = adapter.validate_credentials()

        self.assertTrue(validation.valid)
        self.assertNotIn("real_trading", validation.permissions)
        self.assertEqual(validation.permission_scope, "demo")

    def test_expired_or_revoked_key_is_invalid(self) -> None:
        adapter = EtoroReadOnlyBrokerAdapter(
            client=EtoroClient(
                api_key="api",
                user_key="user",
                http_client=FakeHttpClient([FakeResponse(401, {"message": "revoked"})]),
            )
        )

        validation = adapter.validate_credentials()

        self.assertFalse(validation.valid)
        self.assertEqual(validation.permission_scope, "invalid")


if __name__ == "__main__":
    unittest.main()
