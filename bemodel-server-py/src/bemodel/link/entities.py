# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class LinkNode(Base):
    __tablename__ = 'link_node'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    node_type = Column('node_type', Text, nullable=True, server_default=FetchedValue())
    ref_no = Column('ref_no', Text, nullable=True, server_default=FetchedValue())
    title = Column('title', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    occurred_at = Column('occurred_at', DateTime, nullable=True, server_default=FetchedValue())
    payload = Column('payload', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class LinkRel(Base):
    __tablename__ = 'link_rel'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    from_ref_no = Column('from_ref_no', Text, nullable=True, server_default=FetchedValue())
    to_ref_no = Column('to_ref_no', Text, nullable=True, server_default=FetchedValue())
    rel_type = Column('rel_type', Text, nullable=True, server_default=FetchedValue())
    remark = Column('remark', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
