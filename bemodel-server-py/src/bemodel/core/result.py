from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import inspect
from .java_compat import camel_case


def to_camel_dict(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds" if not value.microsecond else "microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        # Java Map keys are literal data (including SQL column names), not bean properties.
        return {str(k): to_camel_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_camel_dict(v) for v in value]
    if is_dataclass(value):
        return {camel_case(k): to_camel_dict(v) for k, v in asdict(value).items()}
    return {camel_case(a.key): to_camel_dict(getattr(value, a.key))
            for a in inspect(type(value)).column_attrs}


def ok(data=None):
    return {"code": 0, "msg": "ok", "data": to_camel_dict(data)}


def error(msg):
    return {"code": 500, "msg": msg, "data": None}
