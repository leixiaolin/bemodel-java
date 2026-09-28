"""Prepare migrations only for the dedicated full-acceptance Docker instances.

The application under test performs its own seeding on startup.
"""
from sqlalchemy import text
from bemodel.config import settings
from bemodel.core.database import engine
from bemodel.core.migration import run_migrations

assert settings.mysql_host == '127.0.0.1'
assert settings.mysql_port in (13319, 13320)
assert settings.mysql_database == 'bemodel_acceptance'
print('migrations:', run_migrations(engine), flush=True)
with engine.begin() as conn:
    conn.execute(text('UPDATE bm_datasource SET port=:port'), {'port': settings.mysql_port})
