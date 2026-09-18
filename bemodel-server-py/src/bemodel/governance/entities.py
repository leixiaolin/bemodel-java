# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class GovIssue(Base):
    __tablename__ = 'bm_gov_issue'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    scan_id = Column('scan_id', BigInteger().with_variant(Integer, 'sqlite'), nullable=True, server_default=FetchedValue())
    rule_code = Column('rule_code', Text, nullable=True, server_default=FetchedValue())
    rule_name = Column('rule_name', Text, nullable=True, server_default=FetchedValue())
    rule_type = Column('rule_type', Text, nullable=True, server_default=FetchedValue())
    severity = Column('severity', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    table_name = Column('table_name', Text, nullable=True, server_default=FetchedValue())
    hit_count = Column('hit_count', Integer, nullable=True, server_default=FetchedValue())
    sample_json = Column('sample_json', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class GovRule(Base):
    __tablename__ = 'bm_gov_rule'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    rule_code = Column('rule_code', Text, nullable=True, server_default=FetchedValue())
    rule_name = Column('rule_name', Text, nullable=True, server_default=FetchedValue())
    rule_type = Column('rule_type', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    severity = Column('severity', Text, nullable=True, server_default=FetchedValue())
    expr_json = Column('expr_json', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class GovScan(Base):
    __tablename__ = 'bm_gov_scan'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    scan_time = Column('scan_time', DateTime, nullable=True, server_default=FetchedValue())
    duration_ms = Column('duration_ms', BigInteger().with_variant(Integer, 'sqlite'), nullable=True, server_default=FetchedValue())
    rule_count = Column('rule_count', Integer, nullable=True, server_default=FetchedValue())
    issue_count = Column('issue_count', Integer, nullable=True, server_default=FetchedValue())
    quality_score = Column('quality_score', Integer, nullable=True, server_default=FetchedValue())
