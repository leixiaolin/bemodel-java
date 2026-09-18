import time
import jwt


class JwtService:
    DEV_SECRET = "bemodel-dev-jwt-secret-do-not-use-in-prod"

    def __init__(self, secret=""):
        self.secret = secret if secret and secret.strip() else self.DEV_SECRET
        length = len(self.secret.encode())
        if length < 32:
            raise ValueError("JWT secret must contain at least 32 bytes")
        # JJWT signWith(key) selects the strongest suitable HMAC algorithm.
        self.algorithm = "HS512" if length >= 64 else "HS384" if length >= 48 else "HS256"

    def issue(self, user):
        now = int(time.time())
        return jwt.encode({"sub": user.username, "role": user.role,
            "displayName": user.display_name or "", "iat": now, "exp": now + 43200},
            self.secret, algorithm=self.algorithm, headers={"typ": None})

    def parse(self, token):
        try:
            return jwt.decode(token, self.secret, algorithms=["HS256", "HS384", "HS512"],
                              options={"verify_aud": False, "verify_iat": False})
        except jwt.PyJWTError:
            return None
