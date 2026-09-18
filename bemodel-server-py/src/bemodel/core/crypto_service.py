import base64
import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoService:
    PREFIX = "ENC:"
    DEV_KEY = "bemodel-dev-app-secret-do-not-use-in-prod"

    def __init__(self, secret=""):
        self.cipher = AESGCM(hashlib.sha256((secret if secret and secret.strip() else self.DEV_KEY).encode()).digest())

    def encrypt(self, plain):
        if plain is None or plain.startswith(self.PREFIX):
            return plain
        iv = os.urandom(12)
        return self.PREFIX + base64.b64encode(iv + self.cipher.encrypt(iv, plain.encode(), None)).decode()

    def decrypt(self, stored):
        if stored is None or not stored.startswith(self.PREFIX):
            return stored
        try:
            raw = base64.b64decode(stored[4:], validate=True)
            return self.cipher.decrypt(raw[:12], raw[12:], None).decode()
        except Exception as exc:
            raise ValueError(f"解密失败（密钥不匹配或数据损坏）: {exc}") from exc
