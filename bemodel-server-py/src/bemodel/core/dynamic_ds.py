from threading import Lock
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

_engines, _lock = {}, Lock()


def make_engine(ds, crypto, timeout=None):
    engine = create_engine(URL.create("mysql+pymysql", username=ds.username, password=crypto.decrypt(ds.password),
        host=ds.host, port=ds.port, database=ds.db_name, query={"charset": "utf8mb4"}), poolclass=NullPool,
        connect_args={"connect_timeout": timeout or 10, **({"read_timeout": timeout} if timeout else {})})
    return engine


def get_engine(code, supplier, crypto):
    if code not in _engines:
        with _lock:
            if code not in _engines:
                _engines[code] = make_engine(supplier(), crypto)
    return _engines[code]


def dispose_all():
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()


def dispose_engine(code):
    with _lock:
        engine = _engines.pop(code, None)
    if engine:
        engine.dispose()
