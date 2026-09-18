# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class AlertNotice(Base):
    __tablename__ = 'bm_alert_notice'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    metric_code = Column('metric_code', Text, nullable=True, server_default=FetchedValue())
    metric_name = Column('metric_name', Text, nullable=True, server_default=FetchedValue())
    actual_value = Column('actual_value', Integer, nullable=True, server_default=FetchedValue())
    threshold = Column('threshold', Integer, nullable=True, server_default=FetchedValue())
    message = Column('message', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class InspectRun(Base):
    __tablename__ = 'bm_inspect_run'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    evaluated = Column('evaluated', Integer, nullable=True, server_default=FetchedValue())
    alarmed = Column('alarmed', Integer, nullable=True, server_default=FetchedValue())
    notices_created = Column('notices_created', Integer, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
