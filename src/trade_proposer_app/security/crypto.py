import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from trade_proposer_app.config import settings


class CredentialCipher:
    def __init__(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(
                "failed to decrypt stored provider credentials; the SECRET_KEY likely changed after the values were saved"
            ) from exc


credential_cipher = CredentialCipher(settings.secret_key)
