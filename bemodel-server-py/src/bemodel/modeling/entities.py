# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class Action(Base):
    __tablename__ = 'bm_action'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    action_code = Column('action_code', Text, nullable=True, server_default=FetchedValue())
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    from_status = Column('from_status', Text, nullable=True, server_default=FetchedValue())
    to_status = Column('to_status', Text, nullable=True, server_default=FetchedValue())
    trigger_desc = Column('trigger_desc', Text, nullable=True, server_default=FetchedValue())
    description = Column('description', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    version = Column('version', Integer, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class Axiom(Base):
    __tablename__ = 'bm_axiom'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    axiom_code = Column('axiom_code', Text, nullable=True, server_default=FetchedValue())
    subject = Column('subject', Text, nullable=True, server_default=FetchedValue())
    predicate = Column('predicate', Text, nullable=True, server_default=FetchedValue())
    object = Column('object', Text, nullable=True, server_default=FetchedValue())
    axiom_type = Column('axiom_type', Text, nullable=True, server_default=FetchedValue())
    description = Column('description', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class Release(Base):
    __tablename__ = 'bm_release'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    version_tag = Column('version_tag', Text, nullable=True, server_default=FetchedValue())
    change_summary = Column('change_summary', Text, nullable=True, server_default=FetchedValue())
    element_count = Column('element_count', Integer, nullable=True, server_default=FetchedValue())
    snapshot_json = Column('snapshot_json', Text, nullable=True, server_default=FetchedValue())
    released_by = Column('released_by', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class Rule(Base):
    __tablename__ = 'bm_rule'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    rule_code = Column('rule_code', Text, nullable=True, server_default=FetchedValue())
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    rule_type = Column('rule_type', Text, nullable=True, server_default=FetchedValue())
    expression = Column('expression', Text, nullable=True, server_default=FetchedValue())
    metric_code = Column('metric_code', Text, nullable=True, server_default=FetchedValue())
    severity = Column('severity', Text, nullable=True, server_default=FetchedValue())
    owner = Column('owner', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    version = Column('version', Integer, nullable=True, server_default=FetchedValue())
    engine = Column('engine', Text, nullable=True, server_default=FetchedValue())
    expr_json = Column('expr_json', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())
