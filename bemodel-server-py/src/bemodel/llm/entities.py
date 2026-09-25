# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class LlmLog(Base):
    __tablename__ = 'bm_llm_log'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    call_type = Column('call_type', Text, nullable=True, server_default=FetchedValue())
    model = Column('model', Text, nullable=True, server_default=FetchedValue())
    ontology_version = Column('ontology_version', Text, nullable=True, server_default=FetchedValue())
    prompt_digest = Column('prompt_digest', Text, nullable=True, server_default=FetchedValue())
    # Python-only column (V30)；Java 端实体未含此列，插入时保持 NULL。
    response_digest = Column('response_digest', Text, nullable=True, server_default=FetchedValue())
    latency_ms = Column('latency_ms', BigInteger().with_variant(Integer, 'sqlite'), nullable=True, server_default=FetchedValue())
    success = Column('success', Integer, nullable=True, server_default=FetchedValue())
    err_msg = Column('err_msg', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
