"""Exercise every original API on dedicated Java 18083 / Python 18084 instances.

Run only after bootstrap_acceptance.py and application startup on fresh databases.
Successful business responses, not route presence or matching errors, count as coverage.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from check_flow_parity import differences

ROOT = Path(__file__).resolve().parents[1]
VOLATILE = {'createdAt', 'updatedAt', 'scannedAt', 'lastEvalAt', 'generatedAt', 'finishedAt',
    'startedAt', 'timestamp', 'latencyMs', 'avgLatencyMs', 'firstSeen', 'lastSeen', 'evaluatedAt', 'durationMs', 'token'}


def normalize(value, key=''):
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        items = [normalize(v, key) for v in value]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)) if key == 'violations' else items
    if key == 'port' and value in (13319, 13320):
        return '<isolated mysql port>'
    if key == 'engine' and value in ('pySHACL', 'Apache Jena SHACL 5.2.0'):
        return '<documented SHACL engine>'
    if isinstance(value, str):
        value = re.sub(r'RCA-\d{14}', 'RCA-<generated-timestamp>', value)
        if key.endswith('Json') or key in ('payload', 'context', 'result'):
            try:
                return normalize(json.loads(value))
            except ValueError:
                pass
        if value.startswith('系统异常: '):
            return '系统异常: <framework diagnostic>'
        if key == 'caseNo':
            return '<generated case number>'
        if value.startswith('@prefix') or '# BeModel' in value:
            return re.sub(r'(?m)^#.*(?:导出时间|Exported|Generated|生成时间).*$', '# <export time>', value)
    return value


def compare_responses(paths, responses):
    compared = [normalize(r) for r in responses]
    # Newly generated ticket timestamps are volatile, and sorting by them can
    # cross a MySQL second boundary between the two sequential applications.
    # Only this complete (untruncated) ticket page is compared by business key.
    if paths[0] == '/link/list?nodeType=TICKET&pageSize=200':
        for response in compared:
            page = response['body']['data']
            assert page['total'] == len(page['list'])
            for row in page['list']:
                if row['refNo'].startswith(('T-AUTO-', 'T-GOV-', 'ALERT-')):
                    row.pop('occurredAt', None)
            page['list'].sort(key=lambda row: row['refNo'])
    diff = list(differences(compared[0], compared[1]))
    return diff


class Acceptance:
    def __init__(self):
        self.clients = [httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=180) for port in (18083, 18084)]
        self.checks = []
        self.routes = json.loads((ROOT/'artifacts/routes.json').read_text())['javaRoutes']

    def call(self, method, path, body=None, *, files=None, successful=True):
        responses = []
        paths = path if isinstance(path, list) else [path, path]
        for i, (client, endpoint) in enumerate(zip(self.clients, paths)):
            kwargs = {'files': files} if files else {'json': body[i] if isinstance(body, tuple) else body}
            response = client.request(method, '/api'+endpoint, **kwargs)
            try:
                data = response.json()
            except ValueError:
                data = response.text
            responses.append({'status': response.status_code, 'body': data})
        diff = compare_responses(paths, responses)
        business_ok = all(r['status'] == 200 and (not isinstance(r['body'], dict) or r['body'].get('code') == 0) for r in responses)
        matches = [route for verb, route in self.routes if verb == method and
            re.fullmatch(re.sub(r'\{[^}]+\}', '[^/]+', route), '/api'+urlsplit(paths[0]).path)]
        if matches:
            matches = [min(matches, key=lambda route: route.count('{'))]
        check = dict(method=method, paths=paths, routes=matches, expectedSuccess=successful,
            businessSuccess=business_ok, differences=diff, responses=responses)
        self.checks.append(check)
        if diff or successful and not business_ok:
            print('FAIL', method, paths[0], json.dumps(diff[:2] or responses, ensure_ascii=False)[:900], flush=True)
        return [r['body'].get('data') if isinstance(r['body'], dict) else r['body'] for r in responses]

    def paths(self, pattern, rows, key='id'):
        return [pattern.format(row[key]) for row in rows]

    def finish(self):
        covered = {(c['method'], r) for c in self.checks if c['businessSuccess'] and not c['differences'] for r in c['routes']}
        missing = [r for r in self.routes if tuple(r) not in covered]
        failed = [i for i,c in enumerate(self.checks) if c['differences'] or c['expectedSuccess'] and not c['businessSuccess']]
        report = dict(ignoredFields=sorted(VOLATILE), engineMetadataException=True,
            routeCount=len(self.routes), passedRoutes=len(covered), percentage=round(100*len(covered)/len(self.routes),2),
            uncovered=missing, failedChecks=failed, checks=self.checks)
        (ROOT/'artifacts/full-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False), flush=True)
        for client in self.clients:
            client.close()
        return not missing and not failed

    def run(self):
        logins = self.call('POST', '/auth/login', dict(username='admin', password='admin123'))
        # JWT interoperability is checked separately; only token bytes are volatile here.
        for client, row in zip(self.clients, logins):
            client.headers['Authorization'] = 'Bearer '+row['token']
        for path in ['/auth/me','/domain/list','/concept/list','/term/list','/metric/list','/action/list','/rule/list',
            '/axiom/list','/release/current','/release/list','/ontology/disjoint','/ontology/misses',
            '/datasource/list','/datasource/tables/DS_HIS','/datasource/columns/DS_HIS?tableName=medical_order',
            '/mapping/list?dsCode=DS_HIS','/mapping/ai-suggest?dsCode=DS_HIS&tableName=medical_order',
            '/instance/MEDICAL_ORDER','/flow/patients','/flow/opd/patients','/flow/loop/ZY20260815001',
            '/flow/opd/loop/KC2026900020','/flow/staff?name=王芳','/gov/overview','/gov/tables','/gov/issues',
            '/link/list','/link/chain/MEDICAL_ORDER','/link/chain/MEDICAL_ORDER/rels','/link/trace/T-20260905-002',
            '/notice/list','/notice/unread-count','/cs/feedback/list','/qc/records','/rca/list',
            '/search?q=医嘱','/architecture/overview','/drift/scan','/value/compare',
            '/ontology/relation/closure?relation=属于&concept=VITAL_SIGN']:
            self.call('GET',path)
        self.call('POST','/ontology/check')
        self.call('POST','/impact/analyze',dict(conceptCode='MEDICAL_ORDER',changeDesc='核验字段变更',depth=3))
        self.call('POST','/metric/evaluate-all')
        self.call('POST','/metric/evaluate/DISCHARGE_COUNT')
        self.call('POST','/inspect/run')
        notices=self.call('GET','/notice/list')
        if notices[0]['list']:
            self.call('POST',self.paths('/notice/{}/read',[r['list'][0] for r in notices]))
        self.call('POST','/notice/read-all')
        self.call('POST','/qc/check-all')
        records=self.call('GET','/qc/records')
        rid=[r['list'][0]['record_id'] for r in records]
        self.call('POST',['/qc/check/'+i for i in rid])
        self.call('GET',['/qc/result/'+i for i in rid])
        self.call('POST','/alert/detect')
        self.call('GET','/rdf/patient/ZY20260815001')
        self.call('POST','/rdf/validate/ZY20260815001')
        for question in ['检验取消了怎么还收费？','没缴费可以发药吗？','一个医嘱可以分开发药吗？','发药后可以部分退药吗？','耗材库存','王芳是谁？','出院人数怎么算？']:
            self.call('POST','/cs/ask',dict(question=question,scene='CS'))
        self.call('POST','/cs/feedback',dict(question='没缴费可以发药吗？',intent='PAY_BEFORE_DISPENSE',router='RULE',correct=True,comment='验收'))
        self.call('GET','/cs/feedback/list')
        self.call('GET','/llm/log/list')
        self.call('GET','/llm/stats')
        self.call('POST','/gov/scan')
        issues=self.call('GET','/gov/issues?pageSize=200')
        if issues[0]['list']:
            rows=[r['list'][0] for r in issues]
            self.call('POST',self.paths('/gov/issues/{}/ticket',rows))
            self.call('POST',self.paths('/gov/issues/{}/resolve',rows))
        self.call('POST','/link/auto-ticket')
        tickets=self.call('GET','/link/list?nodeType=TICKET&pageSize=200')
        rows=[next(t for t in r['list'] if t['refNo']=='T-20260905-002') for r in tickets]
        self.call('POST','/rca/start?ticketRef=T-20260905-002')
        cases=self.call('GET','/rca/list')
        self.call('GET',self.paths('/rca/{}',[r[0] for r in cases]))
        self.call('GET',self.paths('/cs/ticket/{}/diagnosis',rows))
        self.call('POST',self.paths('/cs/ticket/{}/refund',rows))
        self.crud()

    def crud(self):
        self.call('POST','/domain',dict(code='ACCEPTANCE',name='验收域',sort=99))
        a=self.call('POST','/concept',dict(code='ACCEPT_A',name='验收父概念',domainCode='ACCEPTANCE',definition='核验'))
        b=self.call('POST','/concept',dict(code='ACCEPT_B',name='验收子概念',domainCode='ACCEPTANCE'))
        self.call('PUT','/concept',tuple(dict(id=r['id'],name='验收父概念更新') for r in a))
        self.call('GET','/concept/detail/ACCEPT_A')
        self.call('POST','/concept/ACCEPT_B/parents',dict(parentCode='ACCEPT_A',isPrimary=1))
        self.call('GET','/concept/ACCEPT_B/parents')
        self.call('PUT','/concept/ACCEPT_B/parents/ACCEPT_A/primary')
        attr=self.call('POST','/concept/attribute',dict(conceptCode='ACCEPT_A',attrCode='id',attrName='编号',dataType='string',isKey=1,sort=1))
        rel=self.call('POST','/concept/relation',dict(fromConcept='ACCEPT_A',toConcept='ACCEPT_B',relationName='验收关联'))
        self.call('PUT','/concept/relation',tuple(dict(id=r['id'],description='已修改') for r in rel))
        term=self.call('POST','/term',dict(term='验收别名',conceptCode='ACCEPT_A',sourceProduct='ACCEPTANCE',termType='ALIAS'))
        self.call('GET','/term/list?conceptCode=ACCEPT_A')
        axiom=self.call('POST','/axiom',dict(axiomCode='ACCEPT_AXIOM',subject='ACCEPT_A',predicate='测试',object='ACCEPT_B',axiomType='BUSINESS',description='验收'))
        disjoint=self.call('POST','/ontology/disjoint',dict(conceptACode='ACCEPT_A',conceptBCode='STAFF',definition='验收'))
        for kind,field in [('rule','ruleCode'),('action','actionCode')]:
            code='ACCEPT_'+kind.upper()
            rows=self.call('POST','/'+kind,{field:code,'name':'验收元素','conceptCode':'ACCEPT_A','ruleType':'校验','expression':'合成规则','toStatus':'已执行'})
            self.call('PUT','/'+kind,tuple(dict(id=r['id'],name='修改元素') for r in rows))
            for target in ['REVIEW','PUBLISHED','DEPRECATED','DRAFT']:
                self.call('POST',f'/{kind}/transition/{code}?target={target}')
            self.call('DELETE',self.paths('/'+kind+'/{}',rows))
        for target in ['REVIEW','PUBLISHED','DEPRECATED','DRAFT']:
            self.call('POST','/concept/transition/ACCEPT_A?target='+target)
        metric=self.call('POST','/metric',dict(metricCode='ACCEPT_COUNT',name='验收医嘱数',conceptCode='MEDICAL_ORDER',dsCode='DS_HIS',probeSql='SELECT COUNT(*) FROM medical_order',warnThreshold=0))
        self.call('PUT','/metric',tuple(dict(id=r['id'],name='医嘱数更新') for r in metric))
        self.call('POST','/metric/evaluate/ACCEPT_COUNT')
        dsbody=tuple(dict(dsCode='DS_ACCEPT',dsName='验收数据源',dbType='MySQL',host='127.0.0.1',port=p,dbName='demo_his',username='root',password='bemodel-isolated-test-only') for p in (13319,13320))
        self.call('POST','/datasource/test',dsbody)
        self.call('POST','/datasource',dsbody)
        self.call('POST','/datasource/scan/DS_ACCEPT')
        self.call('POST','/mapping/batch',[dict(dsCode='DS_ACCEPT',tableName='medical_order',columnName='order_id',conceptCode='ACCEPT_A',attrCode='id')])
        maps=self.call('GET','/mapping/list?dsCode=DS_ACCEPT')
        self.call('DELETE',self.paths('/mapping/{}',[r[0] for r in maps]))
        node=self.call('POST','/link',dict(nodeType='EVENT',refNo='ACCEPT_EVENT',title='验收事件',conceptCode='ACCEPT_A',status='OPEN',occurredAt='2026-09-18T10:00:00'))
        self.call('PUT','/link',tuple(dict(id=r['id'],title='事件更新') for r in node))
        link=self.call('POST','/link/rel',dict(fromRefNo='ACCEPT_EVENT',toRefNo='T-20260905-002',relType='CAUSES',remark='验收'))
        self.call('GET','/link/trace/ACCEPT_EVENT')
        self.call('DELETE',self.paths('/link/rel/{}',link))
        misses=self.call('GET','/ontology/misses')
        rows=[next(t for t in r['items'] if t['adoptedConceptCode'] is None) for r in misses]
        self.call('POST',self.paths('/ontology/misses/{}/dismiss',rows),dict(reason='验收'))
        self.call('POST',self.paths('/ontology/misses/{}/undismiss',rows))
        self.call('POST',self.paths('/ontology/misses/{}/classify',rows))
        self.call('POST',self.paths('/ontology/misses/{}/adopt-as-term',rows),dict(conceptCode='ACCEPT_A'))
        self.call('POST',self.paths('/ontology/misses/{}/revoke',rows))
        self.call('POST',self.paths('/ontology/misses/{}/adopt',rows),dict(code='ACCEPT_MISS',name='验收采纳概念',domainCode='ACCEPTANCE',definition='验收'))
        self.call('POST',self.paths('/ontology/misses/{}/revoke',rows))
        ttl=b'@prefix owl: <http://www.w3.org/2002/07/owl#> . <http://acceptance.example/ImportThing> a owl:Class .'
        self.call('POST','/ontology/import/preview',files={'file':('acceptance.ttl',ttl,'text/turtle')})
        self.call('POST','/ontology/import/execute',files={'file':('acceptance.ttl',ttl,'text/turtle')})
        release=self.call('POST','/release/publish',dict(changeSummary='验收发布',releasedBy='acceptance',force=True))
        self.call('GET',self.paths('/release/{}',release))
        self.call('GET','/release/current')
        for pattern,rows in [('/ontology/disjoint/{}',disjoint),('/axiom/{}',axiom),('/term/{}',term),('/concept/relation/{}',rel),('/concept/attribute/{}',attr)]:
            self.call('DELETE',self.paths(pattern,rows))
        self.call('DELETE','/concept/ACCEPT_B/parents/ACCEPT_A')
        self.call('DELETE','/concept/ACCEPT_B')
        self.call('DELETE','/concept/ACCEPT_A')


if __name__ == '__main__':
    suite=Acceptance()
    try:
        if '--recompare' in sys.argv:
            suite.checks = json.loads((ROOT/'artifacts/full-acceptance.json').read_text(encoding='utf-8'))['checks']
            for check in suite.checks:
                check['differences'] = compare_responses(check['paths'],check['responses'])
                if check['routes']:
                    check['routes'] = [min(check['routes'],key=lambda route: route.count('{'))]
        else:
            suite.run()
    finally:
        passed=suite.finish()
    raise SystemExit(not passed)
