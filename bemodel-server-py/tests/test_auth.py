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
