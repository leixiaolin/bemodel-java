import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from bemodel.core.database import Base, get_session
from bemodel.main import create_app
from fastapi.testclient import TestClient
import os


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(session):
    app = create_app(startup=False)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def mysql_session():
    if os.environ.get('BEMODEL_MYSQL_TESTS') != '1':
        pytest.skip('Set BEMODEL_MYSQL_TESTS=1 for isolated Docker integration tests')
    from bemodel.config import settings
    from bemodel.core.database import engine
    assert settings.mysql_host in ('127.0.0.1', 'localhost')
    assert settings.mysql_port == 13317 and settings.mysql_database == 'bemodel_py_test'
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
