from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, FetchedValue
from bemodel.core.database import Base


class OntologyAnalysisTask(Base):
    __tablename__ = "bm_ontology_analysis_task"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ds_code = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="PENDING")
    progress = Column(Integer, nullable=False, default=0)
    scan_fingerprint = Column(Text, nullable=False)
    ontology_version = Column(Text, nullable=False)
    model = Column(Text)
    analysis_mode = Column(Text, nullable=False, default="FULL")
    scan_diff_json = Column(Text)
    dedupe_key = Column(Text, unique=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    locked_at = Column(DateTime)
    worker_id = Column(Text)
    error_message = Column(Text)
    change_set_id = Column(BigInteger().with_variant(Integer, "sqlite"))
    created_by = Column(Text)
    created_at = Column(DateTime, server_default=FetchedValue())
    started_at = Column(DateTime)
    finished_at = Column(DateTime)


class OntologyChangeSet(Base):
    __tablename__ = "bm_ontology_change_set"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False, unique=True)
    ds_code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="DRAFT")
    scan_fingerprint = Column(Text, nullable=False)
    ontology_version = Column(Text, nullable=False)
    suggestion_count = Column(Integer, nullable=False, default=0)
    high_risk_count = Column(Integer, nullable=False, default=0)
    summary_json = Column(Text)
    created_by = Column(Text)
    reviewed_by = Column(Text)
    published_by = Column(Text)
    created_at = Column(DateTime, server_default=FetchedValue())
    updated_at = Column(DateTime, server_default=FetchedValue())
    published_at = Column(DateTime)


class OntologyChangeItem(Base):
    __tablename__ = "bm_ontology_change_item"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    change_set_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False)
    item_type = Column(Text, nullable=False)
    operation = Column(Text, nullable=False)
    review_status = Column(Text, nullable=False, default="PENDING")
    target_key = Column(Text, nullable=False)
    payload_json = Column(Text, nullable=False)
    evidence_json = Column(Text)
    dependency_json = Column(Text)
    confidence = Column(Numeric(5, 4), nullable=False, default=0)
    risk_level = Column(Text, nullable=False, default="MEDIUM")
    reason = Column(Text)
    missing_information = Column(Text)
    source_table = Column(Text)
    source_column = Column(Text)
    review_note = Column(Text)
    result_ref_json = Column(Text)
    created_at = Column(DateTime, server_default=FetchedValue())
    updated_at = Column(DateTime, server_default=FetchedValue())
