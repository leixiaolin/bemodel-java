"""Initialize only the isolated Docker candidate database on port 13317."""
from sqlalchemy import text
from sqlalchemy.orm import Session
from bemodel.config import settings
from bemodel.core.database import engine
from bemodel.core.migration import run_migrations
from bemodel.datasource.services import DatasourceService
from bemodel.seed.services import DataSeeder

assert settings.mysql_host in ('127.0.0.1', 'localhost') and settings.mysql_port == 13317
assert settings.mysql_database == 'bemodel_py_test'
print('migrations:', run_migrations(engine), flush=True)
with engine.begin() as conn:
    conn.execute(text('UPDATE bm_datasource SET port=13317'))
with Session(engine, expire_on_commit=False) as session:
    DatasourceService(session).migrate_secrets()
    print('seeded:', DataSeeder(session).run(), flush=True)
    print('second seed:', DataSeeder(session).run(), flush=True)
print('second migrations:', run_migrations(engine), flush=True)
