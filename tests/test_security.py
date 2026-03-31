import unittest

from cryptography.fernet import InvalidToken

from trade_proposer_app.security.crypto import CredentialCipher


class SecurityTests(unittest.TestCase):
    def test_credential_cipher_raises_clear_error_for_wrong_secret(self) -> None:
        first = CredentialCipher("secret-a")
        second = CredentialCipher("secret-b")
        token = first.encrypt("hello-world")

        with self.assertRaises(RuntimeError) as ctx:
            second.decrypt(token)

        self.assertIn("SECRET_KEY likely changed", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, InvalidToken)


if __name__ == "__main__":
    unittest.main()
