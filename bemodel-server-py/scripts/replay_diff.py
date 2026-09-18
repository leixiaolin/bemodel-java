"""Replay read/probe scenarios against two isolated Java/Python test applications."""
import json
from pathlib import Path
import httpx
from check_flow_parity import differences

VOLATILE = {'createdAt', 'updatedAt', 'scannedAt', 'lastEvalAt', 'generatedAt', 'finishedAt', 'startedAt', 'timestamp', 'latencyMs'}


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def main():
    checks = []
    with httpx.Client(base_url='http://127.0.0.1:18080', timeout=120) as java, httpx.Client(base_url='http://127.0.0.1:18081', timeout=120) as python:
        for client in (java, python):
            response = client.post('/api/auth/login', json=dict(username='admin', password='admin123')).json()
            client.headers['Authorization'] = 'Bearer '+response['data']['token']
            client.post('/api/inspect/run').raise_for_status()
        def check(method, path, body=None):
            responses = []
            for client in (java, python):
                response = client.request(method, '/api'+path, json=body)
                try:
                    data = response.json()
                except ValueError:
                    data = response.text
                responses.append(dict(status=response.status_code, body=data))
            diff = list(differences(normalize(responses[0]), normalize(responses[1])))
            checks.append(dict(method=method, path=path, request=body, differences=diff))
            if diff:
                print('DIFF', method, path, json.dumps(diff[:2], ensure_ascii=False)[:700], flush=True)
            return responses[0]['body']
        for path in ['/auth/me', '/domain/list', '/concept/list', '/term/list', '/metric/list', '/action/list', '/rule/list', '/axiom/list', '/release/current', '/release/list', '/ontology/disjoint', '/ontology/relation/closure?relation=属于&concept=VITAL_SIGN', '/flow/patients', '/flow/opd/patients', '/gov/overview', '/gov/tables', '/gov/issues', '/notice/list', '/notice/unread-count', '/cs/feedback/list', '/qc/records']:
            check('GET', path)
        concepts = java.get('/api/concept/list').json()['data']
        if isinstance(concepts, dict):
            concepts = concepts.get('list', [])
        for concept in concepts:
            code = concept['code']
            check('GET', '/concept/detail/'+code)
            check('GET', '/concept/'+code+'/parents')
        for ds in ['DS_HIS', 'DS_LIS', 'DS_CHARGE', 'DS_PHARMACY', 'DS_EMR', 'DS_OPD', 'DS_PACS', 'DS_NURSE', 'DS_MATERIAL']:
            check('GET', '/datasource/tables/'+ds)
            check('GET', '/mapping/list?dsCode='+ds)
        for code in ['MEDICAL_ORDER', 'INPATIENT', 'DISPENSE', 'FEE_DETAIL', 'STAFF', 'MATERIAL_STOCK']:
            check('GET', '/instance/'+code)
            check('GET', '/link/chain/'+code)
        for q in ['检验取消了怎么还收费？', '没缴费可以发药吗？', '一个医嘱可以分开发药吗？', '发药后可以部分退药吗', '耗材库存', '王芳是谁？', '出院人数怎么算？', '今天天气怎么样']:
            for scene in ['CS', 'ANALYTICS']:
                check('POST', '/cs/ask', dict(question=q, scene=scene))
        check('POST', '/ontology/check')
        records = java.get('/api/qc/records?pageSize=200').json()['data']['list']
        for record in records:
            check('POST', '/qc/check/'+record['record_id'])
        check('GET', '/value/compare')
    destination = Path(__file__).resolve().parents[1] / 'artifacts/replay-diff.json'
    destination.write_text(json.dumps(dict(ignoredFields=sorted(VOLATILE), checks=checks), ensure_ascii=False, indent=2), encoding='utf-8')
    failed = sum(bool(c['differences']) for c in checks)
    print(f'{len(checks)} scenarios, {failed} mismatches; {destination}', flush=True)
    raise SystemExit(bool(failed))


if __name__ == '__main__':
    main()
