"""Native Flyway -> Python -> native Flyway on isolated port 13318."""
import json
from pathlib import Path
import subprocess
from bemodel.config import settings
from bemodel.core.database import engine
from bemodel.core.migration import run_migrations

assert settings.mysql_host in ('127.0.0.1', 'localhost') and settings.mysql_port == 13318
assert settings.mysql_database == 'bemodel_flyway_test'
root = Path(__file__).resolve().parents[2]
url = 'jdbc:mysql://127.0.0.1:13318/bemodel_flyway_test?createDatabaseIfNotExist=true&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&useSSL=false'


def java_migrate():
    process = subprocess.run(['D:/jdk/openjdk21.0.2/bin/java.exe', str(Path(__file__).with_name('JavaFlywayInterop.java')), str(root), url], input=settings.mysql_username+'\n'+settings.mysql_password+'\n', capture_output=True, text=True, encoding='utf-8', errors='replace')
    if process.returncode:
        raise RuntimeError(process.stderr[-5000:]+process.stdout[-1000:])
    return int(next(line.split(':')[1] for line in process.stdout.splitlines() if line.startswith('MIGRATIONS:')))


first = java_migrate()
assert first == 28, first
python_count = run_migrations(engine)
assert python_count == 0, python_count
second = java_migrate()
assert second == 0, second
result = dict(javaInitial=first, pythonTakeover=python_count, javaRevalidation=second)
(root / 'bemodel-server-py/artifacts/flyway-interop.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
