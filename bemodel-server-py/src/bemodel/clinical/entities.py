# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class QcResult(Base):
    __tablename__ = 'qc_result'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    record_id = Column('record_id', Text, nullable=True, server_default=FetchedValue())
    inhos_no = Column('inhos_no', Text, nullable=True, server_default=FetchedValue())
    record_type = Column('record_type', Text, nullable=True, server_default=FetchedValue())
    pass_flag = Column('pass_flag', Integer, nullable=True, server_default=FetchedValue())
    findings_json = Column('findings_json', Text, nullable=True, server_default=FetchedValue())
    trace_json = Column('trace_json', Text, nullable=True, server_default=FetchedValue())
    llm_used = Column('llm_used', Integer, nullable=True, server_default=FetchedValue())
    llm_summary = Column('llm_summary', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
