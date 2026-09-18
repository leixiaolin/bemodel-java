"""Contract replay for isolated synthetic CRUD, lifecycle and error scenarios."""
import json
from pathlib import Path
import httpx
from check_flow_parity import differences
from replay_diff import normalize


def contract(value):
    value = normalize(value)
    if isinstance(value, dict):
        if value.get('code') == 500 and str(value.get('msg', '')).startswith('系统异常: '):
            value = dict(value, msg='系统异常: <framework diagnostic>')
        return {k: contract(v) for k, v in value.items() if k not in {'id'}}
    if isinstance(value, list):
        return [contract(v) for v in value]
    return value


clients = [httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=60) for port in (18080, 18081)]
checks = []


def check(method, path, body=None, role='ADMIN'):
    results = []
    for i, client in enumerate(clients):
        endpoint = path[i] if isinstance(path, list) else path
        data = body[i] if isinstance(body, tuple) else body
        headers = {'Authorization': client.headers['Authorization']} if role == 'ADMIN' else {'Authorization': 'invalid'}
        response = client.request(method, '/api'+endpoint, json=data, headers=headers)
        results.append(dict(status=response.status_code, body=response.json()))
    diff = list(differences(contract(results[0]), contract(results[1])))
    checks.append(dict(method=method, path=path, differences=diff))
    if diff:
        print('DIFF', path, json.dumps(diff[:2], ensure_ascii=True)[:1000], flush=True)
    return [r['body'].get('data') for r in results]


try:
    for client in clients:
        token = client.post('/api/auth/login', json=dict(username='admin', password='admin123')).json()['data']['token']
        client.headers['Authorization'] = 'Bearer '+token
    check('GET', '/concept/list', role='NONE')
    check('GET', '/concept/detail/TEST-NOT-FOUND')
    check('POST', '/concept/transition/TEST-NOT-FOUND?target=REVIEW')
    check('GET', '/ontology/relation/closure')
    check('GET', '/flow/loop/TEST-NOT-FOUND')
    check('POST', '/auth/login', dict(username='admin', password='wrong-password'))
    for code in ['TEST-REPLAY-A', 'TEST-REPLAY-B']:
        check('DELETE', '/concept/'+code)
    a = check('POST', '/concept', dict(code='TEST-REPLAY-A', name='回放父概念', domainCode='CLINICAL', definition='初始定义'))
    b = check('POST', '/concept', dict(code='TEST-REPLAY-B', name='回放子概念', domainCode='CLINICAL'))
    check('POST', '/concept', dict(code='TEST-REPLAY-A', name='重复编码', domainCode='CLINICAL'))
    check('PUT', '/concept', tuple(dict(id=r['id'], name='更新名称', definition=None) for r in a))
    check('GET', '/concept/detail/TEST-REPLAY-A')
    check('POST', '/concept/TEST-REPLAY-B/parents', dict(parentCode='TEST-REPLAY-A', isPrimary=1))
    check('GET', '/concept/TEST-REPLAY-B/parents')
    check('POST', '/concept/TEST-REPLAY-A/parents', dict(parentCode='TEST-REPLAY-B'))
    check('PUT', '/concept/TEST-REPLAY-B/parents/TEST-REPLAY-A/primary')
    attr = check('POST', '/concept/attribute', dict(conceptCode='TEST-REPLAY-B', attrCode='id', attrName='标识', dataType='string', isKey=1, sort=1))
    rel = check('POST', '/concept/relation', dict(fromConcept='TEST-REPLAY-A', toConcept='TEST-REPLAY-B', relationName='回放关系'))
    check('PUT', '/concept/relation', tuple(dict(id=r['id'], description='关系描述') for r in rel))
    check('DELETE', ['/concept/relation/'+str(r['id']) for r in rel])
    check('DELETE', ['/concept/attribute/'+str(r['id']) for r in attr])
    check('DELETE', '/concept/TEST-REPLAY-B/parents/TEST-REPLAY-A')
    for kind, field in [('rule', 'ruleCode'), ('action', 'actionCode')]:
        code = 'TEST-REPLAY-'+kind.upper()
        rows = check('POST', '/'+kind, {field: code, 'name': '回放建模元素', 'conceptCode': 'TEST-REPLAY-A', 'ruleType': '校验', 'expression': '合成测试', 'toStatus': '已执行'})
        check('PUT', '/'+kind, tuple(dict(id=r['id'], name='更新建模元素') for r in rows))
        for target in ['PUBLISHED', 'REVIEW', 'PUBLISHED', 'DRAFT', 'DEPRECATED']:
            check('POST', '/'+kind+'/transition/'+code+'?target='+target)
        check('DELETE', ['/'+kind+'/'+str(r['id']) for r in rows])
    check('DELETE', '/concept/TEST-REPLAY-B')
    check('DELETE', '/concept/TEST-REPLAY-A')
finally:
    for client in clients:
        client.close()
destination = Path(__file__).resolve().parents[1] / 'artifacts/write-replay.json'
destination.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
failed = sum(bool(c['differences']) for c in checks)
print(f'{len(checks)} write/error scenarios, {failed} mismatches')
raise SystemExit(bool(failed))
