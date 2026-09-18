"""Compare fresh original Java (13318) and Python (13317) seed databases."""
from collections import Counter
import json
from pathlib import Path
import pymysql
from datetime import date, datetime
from decimal import Decimal


def encoded(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)

configs = [(13318, 'bemodel_flyway_test'), (13317, 'bemodel_py_test')]
connections = [pymysql.connect(host='127.0.0.1', port=port, user='root', password='bemodel-isolated-test-only', database=db, cursorclass=pymysql.cursors.DictCursor) for port, db in configs]
ignored = {'created_at', 'updated_at', 'scanned_at', 'installed_on', 'execution_time'}
reports = []
try:
    with connections[0].cursor() as cursor:
        cursor.execute("SELECT TABLE_SCHEMA,TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s OR TABLE_SCHEMA LIKE 'demo\\_%%' ORDER BY TABLE_SCHEMA,TABLE_NAME", (configs[0][1],))
        tables = cursor.fetchall()
    for row in tables:
        schema, table = row['TABLE_SCHEMA'], row['TABLE_NAME']
        datasets = []
        for i, connection in enumerate(connections):
            target = configs[i][1] if schema == configs[0][1] else schema
            with connection.cursor() as cursor:
                cursor.execute('SELECT * FROM `'+target+'`.`'+table+'`')
                values = []
                for value in cursor.fetchall():
                    value = {k: v for k, v in value.items() if k not in ignored}
                    if table == 'bm_datasource':
                        assert value['port'] == configs[i][0]
                        value['port'] = '<isolated-port>'
                        assert value['password'].startswith('ENC:')
                        value['password'] = '<randomized-ciphertext>'
                    values.append(json.dumps(value, default=encoded, ensure_ascii=False, sort_keys=True))
                datasets.append(Counter(values))
        reports.append(dict(table=table if schema == configs[0][1] else schema+'.'+table, javaCount=sum(datasets[0].values()), pythonCount=sum(datasets[1].values()), equal=datasets[0] == datasets[1], javaOnly=list((datasets[0]-datasets[1]).elements())[:2], pythonOnly=list((datasets[1]-datasets[0]).elements())[:2]))
finally:
    for connection in connections:
        connection.close()
destination = Path(__file__).resolve().parents[1] / 'artifacts/initial-state-parity.json'
destination.write_text(json.dumps(dict(ignoredColumns=sorted(ignored), tables=reports), ensure_ascii=False, indent=2), encoding='utf-8')
failed = [r for r in reports if not r['equal']]
print(f'{len(reports)} platform/demo tables, {len(failed)} mismatches')
for item in failed:
    print(item['table'], item['javaCount'], item['pythonCount'], json.dumps(item['javaOnly'][:1], ensure_ascii=True)[:600], json.dumps(item['pythonOnly'][:1], ensure_ascii=True)[:600])
raise SystemExit(bool(failed))
