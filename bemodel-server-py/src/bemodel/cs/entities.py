# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class CsFeedback(Base):
    __tablename__ = 'bm_cs_feedback'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    question = Column('question', Text, nullable=True, server_default=FetchedValue())
    intent = Column('intent', Text, nullable=True, server_default=FetchedValue())
    router = Column('router', Text, nullable=True, server_default=FetchedValue())
    correct = Column('correct', Integer, nullable=True, server_default=FetchedValue())
    comment = Column('comment', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
