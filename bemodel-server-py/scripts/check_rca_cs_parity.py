"""Stateful RCA/CS acceptance against isolated databases only."""
import json
from pathlib import Path
import httpx
from check_flow_parity import differences
from replay_diff import normalize


def cleaned(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {'id', 'caseId', 'caseNo'}:
                continue
            if key.endswith('Json') and isinstance(item, str):
                item = json.loads(item)
            result[key] = cleaned(item)
        return normalize(result)
    if isinstance(value, list):
        return [cleaned(item) for item in value]
    return value


checks = []
clients = [httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=120) for port in (18080, 18081)]
try:
    reports = []
    for client in clients:
        login = client.post('/api/auth/login', json=dict(username='admin', password='admin123')).json()
        client.headers['Authorization'] = 'Bearer '+login['data']['token']
        case = client.post('/api/rca/start', params=dict(ticketRef='T-20260901-001')).json()['data']
        assert case['status'] == 'DONE', case
        detail = client.get('/api/rca/'+str(case['id'])).json()['data']
        assert len(detail['steps']) == 7
        assert [s['hitCount'] for s in detail['steps'][1:4]] == [1, 1, 1]
        impact = json.loads(detail['steps'][4]['resultJson'])
        assert impact['patient_cnt'] == 5 and impact['fee_cnt'] == 5 and impact['total_amount'] == 205
        reports.append(detail)
    diff = list(differences(cleaned(reports[0]), cleaned(reports[1])))
    checks.append(dict(scenario='RCA seven steps', differences=diff))
    for client in clients:
        login_other = clients[1 if client is clients[0] else 0].headers['Authorization']
        assert client.get('/api/auth/me', headers={'Authorization': login_other}).json()['code'] == 0
    checks.append(dict(scenario='JWT cross-verification both directions', differences=[]))
finally:
    for client in clients:
        client.close()
destination = Path(__file__).resolve().parents[1] / 'artifacts/rca-cs-parity.json'
destination.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
for check in checks:
    print(check['scenario'], len(check['differences']), json.dumps(check['differences'][:4], ensure_ascii=False)[:2000])
raise SystemExit(any(c['differences'] for c in checks))
