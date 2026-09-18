"""Read-only replay of all seeded patient flows against an isolated Java baseline."""
import json
from pathlib import Path
import httpx
from sqlalchemy.orm import Session
from bemodel.config import settings
from bemodel.core.database import engine
from bemodel.core.result import to_camel_dict
from bemodel.flow.services import FlowService


def differences(a, b, path='$'):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a.keys() | b.keys():
            if key not in a or key not in b:
                yield dict(path=path+'.'+key, java=a.get(key), python=b.get(key))
            else:
                yield from differences(a[key], b[key], path+'.'+key)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield dict(path=path+'.length', java=len(a), python=len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            yield from differences(x, y, f'{path}[{i}]')
    elif a != b:
        yield dict(path=path, java=a, python=b)


def main():
    assert settings.mysql_host in ('127.0.0.1', 'localhost') and settings.mysql_port == 13316
    assert settings.mysql_database == 'bemodel_py_test'
    with httpx.Client(base_url='http://127.0.0.1:18080', timeout=60) as client, Session(engine) as session:
        login = client.post('/api/auth/login', json=dict(username='admin', password='admin123')).json()
        client.headers['Authorization'] = 'Bearer '+login['data']['token']
        service = FlowService(session)
        checks = []
        def check(path, actual):
            expected = client.get('/api/flow'+path).json()
            assert expected['code'] == 0, expected
            diff = list(differences(expected['data'], to_camel_dict(actual)))
            checks.append(dict(path=path, differences=diff))
        check('/patients?pageSize=200', service.patients(None, 1, 200))
        check('/opd/patients?pageSize=200', service.opd_patients(None, 1, 200))
        for row in service.query('HIS', 'SELECT inhos_no FROM inpatient ORDER BY inhos_no'):
            check('/loop/'+row['inhos_no'], service.loop(row['inhos_no']))
        for row in service.query('OPD', 'SELECT pat_card_no FROM opd_reg ORDER BY pat_card_no'):
            check('/opd/loop/'+row['pat_card_no'], service.opd_loop(row['pat_card_no']))
        for name in ('护士 王芳', '医生 张建国', '不存在'):
            check('/staff?name='+name, service.staff_detail(name))
    destination = Path(__file__).resolve().parents[1] / 'artifacts' / 'flow-parity.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    failed = [r for r in checks if r['differences']]
    print(f'{len(checks)} checks, {len(failed)} mismatches; report: {destination}')
    if failed:
        print(json.dumps(failed[0], ensure_ascii=False)[:3000])
        raise SystemExit(1)


if __name__ == '__main__':
    main()
