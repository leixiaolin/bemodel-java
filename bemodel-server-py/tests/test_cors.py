import pytest


@pytest.mark.parametrize('method', ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'PROPFIND'])
def test_api_preflight_reflects_requested_method_and_headers(client, method):
    response = client.options('/api/concept/list', headers={
        'Origin': 'https://example.invalid', 'Access-Control-Request-Method': method,
        'Access-Control-Request-Headers': 'authorization,content-type'})
    assert response.status_code == 200 and response.content == b''
    assert response.headers['access-control-allow-origin'] == 'https://example.invalid'
    assert response.headers['access-control-allow-methods'] == method
    assert response.headers['access-control-allow-headers'] == 'authorization, content-type'
    assert 'access-control-max-age' not in response.headers
    assert 'access-control-allow-credentials' not in response.headers
    assert set(response.headers['vary'].split(', ')) == {'Origin', 'Access-Control-Request-Method', 'Access-Control-Request-Headers'}


def test_non_api_preflight_rejected(client):
    response = client.options('/outside', headers={'Origin':'https://example.invalid','Access-Control-Request-Method':'GET'})
    assert response.status_code == 403 and response.text == 'Invalid CORS request'
    assert 'access-control-allow-origin' not in response.headers


def test_cross_origin_unauthenticated_preserves_401(client):
    response = client.get('/api/concept/list',headers={'Origin':'https://example.invalid'})
    assert response.status_code == 401
    assert response.headers['access-control-allow-origin'] == 'https://example.invalid'


def test_same_origin_preflight_has_no_cors_permission_headers(client):
    response = client.options('/api/concept/list',headers={'Origin':'http://testserver','Access-Control-Request-Method':'GET'})
    assert response.status_code == 200 and response.content == b''
    assert 'access-control-allow-origin' not in response.headers


def test_null_origin_and_api_root(client):
    response = client.options('/api',headers={'Origin':'null','Access-Control-Request-Method':'POST'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'null'


def test_unhandled_error_keeps_cors_headers(client):
    from types import SimpleNamespace
    from bemodel.auth.jwt_service import JwtService
    @client.app.get('/api/test-cors-error')
    def fail():
        raise RuntimeError('controlled failure')
    token = JwtService().issue(SimpleNamespace(username='test',display_name=None,role='ADMIN'))
    response = client.get('/api/test-cors-error',headers={'Origin':'https://example.invalid','Authorization':'Bearer '+token})
    assert response.status_code == 200
    assert response.json()['msg'] == '系统异常: controlled failure'
    assert response.headers.get('access-control-allow-origin') == 'https://example.invalid'
