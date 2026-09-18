from starlette.responses import JSONResponse
from bemodel.auth.jwt_service import JwtService
from bemodel.config import settings


def allowed_roles(method, path):
    if path == "/api/auth/login" or method == "OPTIONS" or not path.startswith("/api/"):
        return None
    all_roles = {"ADMIN", "EDITOR", "VIEWER"}
    if method == "POST" and path in {"/api/cs/ask", "/api/search", "/api/cs/feedback"}:
        return all_roles
    if method == "GET" and path == "/api/cs/feedback/list":
        return {"ADMIN", "EDITOR"}
    if method == "GET":
        return all_roles
    return {"ADMIN", "EDITOR"}


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app
        self.jwt = JwtService(settings.jwt_secret)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin1")
        claims = self.jwt.parse(header[7:]) if header.startswith("Bearer ") else None
        scope.setdefault("state", {})["claims"] = claims
        roles = allowed_roles(scope["method"], scope["path"])
        if roles is not None:
            code = 401 if claims is None else 403 if claims.get("role") not in roles else None
            if code:
                response = JSONResponse({"code": code, "msg": "未登录或已过期" if code == 401 else "权限不足"}, status_code=code)
                return await response(scope, receive, send)
        await self.app(scope, receive, send)
