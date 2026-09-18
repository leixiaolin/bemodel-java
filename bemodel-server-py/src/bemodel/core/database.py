from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session
from bemodel.config import settings


class Base(DeclarativeBase):
    pass


def mysql_engine(database=None, **kwargs):
    engine = create_engine(URL.create("mysql+pymysql", username=settings.mysql_username,
        password=settings.mysql_password, host=settings.mysql_host, port=settings.mysql_port,
        database=database, query={"charset": "utf8mb4"}), pool_pre_ping=True, **kwargs)
    return engine


engine = mysql_engine(settings.mysql_database)


def get_session():
    with Session(engine, expire_on_commit=False) as session:
        yield session


@contextmanager
def transactional(session):
    """DAO writes flush within these explicit Java transaction boundaries."""
    depth = session.info.get("transaction_depth", 0)
    session.info["transaction_depth"] = depth + 1
    try:
        yield session
        if depth == 0:
            session.commit()
    except Exception:
        if depth == 0:
            session.rollback()
        raise
    finally:
        session.info["transaction_depth"] = depth
