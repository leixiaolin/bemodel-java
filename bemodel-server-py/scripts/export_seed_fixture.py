"""Capture the deterministic Java DataSeeder output from an isolated test server.

The generated resource contains fictional demo records only, never platform users,
datasource credentials, tokens or audit records. Run after the unmodified Java
application has completed seeding. This is a development tool, not a runtime dependency.
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from bemodel.config import settings
from bemodel.core.database import engine

ROOT = Path(__file__).resolve().parents[1]
DATABASES = ["his", "lis", "charge", "pharmacy", "opd", "emr", "pacs", "nurse", "material"]


def encode(value):
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    raise TypeError(type(value).__name__)


def main():
    if settings.mysql_host != "127.0.0.1" or settings.mysql_port != 13316 or settings.mysql_database != "bemodel_py_test":
        raise SystemExit("Export is restricted to the isolated Java baseline at 127.0.0.1:13316/bemodel_py_test")
    source = ROOT.parent / "bemodel-server/src/main/java/com/bemodel/seed/DataSeeder.java"
    fixture = {"sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "datasources": {}}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM demo_his.inpatient")).scalar_one() == 41
        assert conn.execute(text("SELECT COUNT(*) FROM demo_his.staff")).scalar_one() >= 17
        assert conn.execute(text("SELECT COUNT(*) FROM demo_his.fee_detail f JOIN demo_his.medical_order o ON f.order_id=o.order_id WHERE o.order_status='2' AND f.fee_status='1'")).scalar_one() == 5
        for suffix in DATABASES:
            schema = "demo_" + suffix
            tables = conn.execute(text("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=:db ORDER BY TABLE_NAME"), {"db": schema}).scalars().all()
            dataset = {}
            for table in tables:
                auto = set(conn.execute(text("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:db AND TABLE_NAME=:table AND EXTRA LIKE '%auto_increment%'"), {"db": schema, "table": table}).scalars())
                # Auto-increment ids are assigned afresh, exactly as the Java DELETE+INSERT seeder does.
                if schema == 'demo_emr' and table == 'patient_allergy':
                    auto.add('created_at')  # Java INSERT lets MySQL generate this runtime timestamp.
                rows = [{k: v for k, v in r.items() if k not in auto} for r in conn.execute(text(f"SELECT * FROM `{schema}`.`{table}`")).mappings()]
                dataset[table] = rows
            fixture["datasources"]["DS_" + suffix.upper()] = dataset
    target = ROOT / "src/bemodel/resources/seed/demo.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fixture, default=encode, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({ds: {t: len(rows) for t, rows in tables.items()} for ds, tables in fixture["datasources"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
