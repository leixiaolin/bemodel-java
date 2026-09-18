"""Compare every demo table between the two isolated MySQL containers."""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import pymysql


def encoded(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


reports = []
baseline_port = int(os.environ.get('BEMODEL_BASELINE_MYSQL_PORT', '13316'))
assert baseline_port in (13316, 13318)
connections = [pymysql.connect(host='127.0.0.1', port=port, user='root', password='bemodel-isolated-test-only', cursorclass=pymysql.cursors.DictCursor) for port in (baseline_port, 13317)]
try:
    with connections[0].cursor() as cursor:
        cursor.execute("SELECT TABLE_SCHEMA,TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA LIKE 'demo\\_%' ORDER BY TABLE_SCHEMA,TABLE_NAME")
        tables = cursor.fetchall()
    for table in tables:
        schema, name = table['TABLE_SCHEMA'], table['TABLE_NAME']
        datasets = []
        for connection in connections:
            with connection.cursor() as cursor:
                cursor.execute('SELECT * FROM `'+schema+'`.`'+name+'`')
                rows = cursor.fetchall()
                if schema == 'demo_emr' and name == 'patient_allergy':
                    rows = [{k: v for k, v in row.items() if k != 'created_at'} for row in rows]
                datasets.append(Counter(json.dumps(row, default=encoded, ensure_ascii=False, sort_keys=True) for row in rows))
        reports.append(dict(table=schema+'.'+name, javaRows=sum(datasets[0].values()), pythonRows=sum(datasets[1].values()), equal=datasets[0] == datasets[1], javaOnly=list((datasets[0]-datasets[1]).elements())[:3], pythonOnly=list((datasets[1]-datasets[0]).elements())[:3]))
finally:
    for connection in connections:
        connection.close()
destination = Path(__file__).resolve().parents[1] / 'artifacts/seed-parity.json'
destination.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
failed = [r for r in reports if not r['equal']]
print(f'{len(reports)} tables, {sum(r["javaRows"] for r in reports)} rows, {len(failed)} mismatches')
for item in failed:
    print(item['table'], item['javaRows'], item['pythonRows'])
raise SystemExit(bool(failed))
