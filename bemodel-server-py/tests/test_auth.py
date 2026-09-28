from types import SimpleNamespace
import bcrypt
import pytest
from bemodel.auth.jwt_service import JwtService
from bemodel.auth.entities import PlatformUser
from bemodel.core.base_dao import BaseDAO


@pytest.mark.parametrize("role,path,method,status", [
    ("VIEWER", "/api/cs/feedback/list", "GET", 403),
    ("VIEWER", "/api/concept", "POST", 403),
    ("VIEWER", "/api/cs/ask", "POST", 200),
    ("EDITOR", "/api/missing", "POST", 404),
    ("VIEWER", "/api/missing", "GET", 404),
])
def test_security_chain(client, role, path, method, status):
    token = JwtService().issue(SimpleNamespace(username="test", display_name=None, role=role))
    response = client.request(method, path, headers={"Authorization": "Bearer " + token})
    assert response.status_code == status


def test_unauthenticated(client):
    assert client.get("/api/concept/list").json() == {"code": 401, "msg": "未登录或已过期"}
    assert client.get("/api/concept/list", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_login_and_me(client, session):
    BaseDAO(session, PlatformUser).insert(dict(username="admin", passwordHash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(), role="ADMIN", displayName="管理员"))
    response = client.post("/api/auth/login", json={"username": "admin", "password": "pw"}).json()
    assert response["code"] == 0
    claims = JwtService().parse(response["data"]["token"])
    assert claims["exp"] - claims["iat"] == 43200
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + response["data"]["token"]}).json()["data"]["role"] == "ADMIN"
    invalid = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert invalid.status_code == 200 and invalid.json()["msg"] == "用户名或密码错误"


def test_validation_error(client):
    response = client.post("/api/auth/login", content="not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["msg"].startswith("系统异常: ")


def test_plain_options_requires_auth_but_cors_preflight_does_not(client):
    assert client.options("/api/concept/list").status_code == 401
    response = client.options("/api/concept/list", headers={
        "Origin": "https://example.invalid", "Access-Control-Request-Method": "GET"})
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers


def test_api_root_requires_auth(client):
    assert client.get("/api").status_code == 401


@pytest.mark.parametrize("role", [[], {}, None, 42, "UNKNOWN"])
def test_unrecognized_signed_role_is_forbidden(client, role):
    token = JwtService().issue(SimpleNamespace(username="test", display_name=None, role=role))
    response = client.get("/api/concept/list", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403
    assert response.json() == {"code": 403, "msg": "权限不足"}


@pytest.mark.parametrize("length,algorithm,accepted", [
    (32, "HS256", True), (32, "HS384", False), (32, "HS512", False),
    (48, "HS256", True), (48, "HS384", True), (48, "HS512", False),
    (64, "HS256", True), (64, "HS384", True), (64, "HS512", True),
])
def test_jjwt_minimum_key_size(length, algorithm, accepted):
    import jwt
    import warnings
    secret = "k" * length
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        token = jwt.encode({"sub": "test", "role": "VIEWER"}, secret, algorithm=algorithm)
    assert (JwtService(secret).parse(token) is not None) == accepted
