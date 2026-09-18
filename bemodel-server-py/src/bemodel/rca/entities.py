# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class RcaCase(Base):
    __tablename__ = 'rca_case'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    case_no = Column('case_no', Text, nullable=True, server_default=FetchedValue())
    ticket_ref = Column('ticket_ref', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    conclusion = Column('conclusion', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    finished_at = Column('finished_at', DateTime, nullable=True, server_default=FetchedValue())


class RcaReport(Base):
    __tablename__ = 'rca_report'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    case_id = Column('case_id', BigInteger().with_variant(Integer, 'sqlite'), nullable=True, server_default=FetchedValue())
    root_cause = Column('root_cause', Text, nullable=True, server_default=FetchedValue())
    evidence_json = Column('evidence_json', Text, nullable=True, server_default=FetchedValue())
    impact_json = Column('impact_json', Text, nullable=True, server_default=FetchedValue())
    suggestions_json = Column('suggestions_json', Text, nullable=True, server_default=FetchedValue())
    llm_used = Column('llm_used', Integer, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class RcaStep(Base):
    __tablename__ = 'rca_step'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    case_id = Column('case_id', BigInteger().with_variant(Integer, 'sqlite'), nullable=True, server_default=FetchedValue())
    step_no = Column('step_no', Integer, nullable=True, server_default=FetchedValue())
    step_name = Column('step_name', Text, nullable=True, server_default=FetchedValue())
    step_type = Column('step_type', Text, nullable=True, server_default=FetchedValue())
    sql_text = Column('sql_text', Text, nullable=True, server_default=FetchedValue())
    hit_count = Column('hit_count', Integer, nullable=True, server_default=FetchedValue())
    result_json = Column('result_json', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    started_at = Column('started_at', DateTime, nullable=True, server_default=FetchedValue())
    finished_at = Column('finished_at', DateTime, nullable=True, server_default=FetchedValue())
