"""Compare all persisted state after full_acceptance on isolated ports 13319/13320."""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json
import re
import hashlib
from pathlib import Path
import pymysql
from full_acceptance import normalize

IGNORED = {'created_at','updated_at','scanned_at','installed_on','execution_time','last_eval_at',
    'latency_ms','started_at','finished_at','first_seen','last_seen'}


def numeric_values(value):
    if isinstance(value, dict):
        return {k:numeric_values(v) for k,v in value.items()}
    if isinstance(value, list):
        return [numeric_values(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def clean(value, table=''):
    result = {}
    for key, val in value.items():
        if key in IGNORED:
            continue
        if isinstance(val, (date, datetime)):
            val = val.isoformat()
        if isinstance(val, Decimal):
            val = float(val)
        if isinstance(val, str) and val[:1] in ('{','['):
            try:
                val = normalize(json.loads(val))
            except ValueError:
                pass
        result[key] = val
    if table == 'bm_datasource':
        assert result['port'] in (13319,13320)
        result['port'] = '<isolated-port>'
        assert result['password'].startswith('ENC:')
        result['password'] = '<ciphertext>'
    if table == 'link_node' and str(result['ref_no']).startswith(('T-AUTO-','T-GOV-','ALERT-')):
        result.pop('occurred_at',None)
    if table == 'rca_case':
        result['case_no'] = '<generated-case-number>'
    if table == 'bm_gov_scan':
        result.pop('duration_ms',None)
        result.pop('scan_time',None)
    return numeric_values(normalize(result))


def main():
    connections = [pymysql.connect(host='127.0.0.1',port=p,user='root',password='bemodel-isolated-test-only',
        database='bemodel_acceptance',cursorclass=pymysql.cursors.DictCursor) for p in (13319,13320)]
    reports=[]
    try:
        inventories=[]
        for connection in connections:
            with connection.cursor() as cursor:
                cursor.execute("SELECT TABLE_SCHEMA,TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='bemodel_acceptance' OR TABLE_SCHEMA LIKE 'demo\\_%%' ORDER BY TABLE_SCHEMA,TABLE_NAME")
                inventories.append(cursor.fetchall())
        assert inventories[0] == inventories[1], 'Different table inventories'
        for row in inventories[0]:
            schema, table = row['TABLE_SCHEMA'], row['TABLE_NAME']
            datasets=[]
            schemas=[]
            for connection in connections:
                with connection.cursor() as cursor:
                    cursor.execute(f'SHOW CREATE TABLE `{schema}`.`{table}`')
                    ddl=cursor.fetchone()['Create Table']
                    schemas.append(re.sub(r' AUTO_INCREMENT=\d+', '', ddl))
                    cursor.execute(f'SELECT * FROM `{schema}`.`{table}`')
                    datasets.append(Counter(json.dumps(clean(r,table),sort_keys=True,ensure_ascii=False) for r in cursor.fetchall()))
            reports.append(dict(table=schema+'.'+table,javaCount=sum(datasets[0].values()),pythonCount=sum(datasets[1].values()),
                equal=datasets[0]==datasets[1] and schemas[0]==schemas[1],schemaEqual=schemas[0]==schemas[1],
                ddlSha256=[hashlib.sha256(s.encode()).hexdigest() for s in schemas],
                javaOnly=list((datasets[0]-datasets[1]).elements())[:3],pythonOnly=list((datasets[1]-datasets[0]).elements())[:3]))
    finally:
        for connection in connections:
            connection.close()
    destination=Path(__file__).resolve().parents[1]/'artifacts/acceptance-state.json'
    destination.write_text(json.dumps(dict(ignoredColumns=sorted(IGNORED),tables=reports),ensure_ascii=False,indent=2),encoding='utf-8')
    failures=[r for r in reports if not r['equal']]
    print(f'{len(reports)} tables, {len(failures)} differences')
    for row in failures:
        print(json.dumps(row,ensure_ascii=True)[:2000])
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
