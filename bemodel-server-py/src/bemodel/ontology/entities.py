# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class Attribute(Base):
    __tablename__ = 'bm_attribute'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    attr_code = Column('attr_code', Text, nullable=True, server_default=FetchedValue())
    attr_name = Column('attr_name', Text, nullable=True, server_default=FetchedValue())
    data_type = Column('data_type', Text, nullable=True, server_default=FetchedValue())
    is_key = Column('is_key', Integer, nullable=True, server_default=FetchedValue())
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    sort = Column('sort', Integer, nullable=True, server_default=FetchedValue())


class Concept(Base):
    __tablename__ = 'bm_concept'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    code = Column('code', Text, nullable=True, server_default=FetchedValue())
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    domain_code = Column('domain_code', Text, nullable=True, server_default=FetchedValue())
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    owner = Column('owner', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    version = Column('version', Integer, nullable=True, server_default=FetchedValue())
    iri = Column('iri', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class ConceptParent(Base):
    __tablename__ = 'bm_concept_parent'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    child_code = Column('child_code', Text, nullable=True, server_default=FetchedValue())
    parent_code = Column('parent_code', Text, nullable=True, server_default=FetchedValue())
    is_primary = Column('is_primary', Integer, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class Disjoint(Base):
    __tablename__ = 'bm_concept_disjoint'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    concept_a_code = Column('concept_a_code', Text, nullable=True, server_default=FetchedValue())
    concept_b_code = Column('concept_b_code', Text, nullable=True, server_default=FetchedValue())
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class Domain(Base):
    __tablename__ = 'bm_domain'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    code = Column('code', Text, nullable=True, server_default=FetchedValue())
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    description = Column('description', Text, nullable=True, server_default=FetchedValue())
    sort = Column('sort', Integer, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class Metric(Base):
    __tablename__ = 'bm_metric'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    metric_code = Column('metric_code', Text, nullable=True, server_default=FetchedValue())
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    formula = Column('formula', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    owner = Column('owner', Text, nullable=True, server_default=FetchedValue())
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    probe_sql = Column('probe_sql', Text, nullable=True, server_default=FetchedValue())
    warn_threshold = Column('warn_threshold', Integer, nullable=True, server_default=FetchedValue())
    last_val = Column('last_val', Integer, nullable=True, server_default=FetchedValue())
    last_eval_at = Column('last_eval_at', DateTime, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class OntologyMiss(Base):
    __tablename__ = 'bm_ontology_miss'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    term = Column('term', Text, nullable=True, server_default=FetchedValue())
    kind = Column('kind', Text, nullable=True, server_default=FetchedValue())
    source = Column('source', Text, nullable=True, server_default=FetchedValue())
    count = Column('count', Integer, nullable=True, server_default=FetchedValue())
    dismissed = Column('dismissed', Integer, nullable=True, server_default=FetchedValue())
    dismiss_reason = Column('dismiss_reason', Text, nullable=True, server_default=FetchedValue())
    adopted_concept_code = Column('adopted_concept_code', Text, nullable=True, server_default=FetchedValue())
    adopted_as = Column('adopted_as', Text, nullable=True, server_default=FetchedValue())
    revoked = Column('revoked', Integer, nullable=True, server_default=FetchedValue())
    first_seen = Column('first_seen', DateTime, nullable=True, server_default=FetchedValue())
    last_seen = Column('last_seen', DateTime, nullable=True, server_default=FetchedValue())


class Relation(Base):
    __tablename__ = 'bm_relation'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    from_concept = Column('from_concept', Text, nullable=True, server_default=FetchedValue())
    to_concept = Column('to_concept', Text, nullable=True, server_default=FetchedValue())
    relation_name = Column('relation_name', Text, nullable=True, server_default=FetchedValue())
    description = Column('description', Text, nullable=True, server_default=FetchedValue())
    is_symmetric = Column('is_symmetric', Integer, nullable=True, server_default=FetchedValue())
    is_transitive = Column('is_transitive', Integer, nullable=True, server_default=FetchedValue())
    is_functional = Column('is_functional', Integer, nullable=True, server_default=FetchedValue())
    is_inverse_functional = Column('is_inverse_functional', Integer, nullable=True, server_default=FetchedValue())
    is_asymmetric = Column('is_asymmetric', Integer, nullable=True, server_default=FetchedValue())
    inverse_of = Column('inverse_of', Text, nullable=True, server_default=FetchedValue())
    iri = Column('iri', Text, nullable=True, server_default=FetchedValue())


class RelationClosure(Base):
    __tablename__ = 'bm_relation_closure'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    relation_name = Column('relation_name', Text, nullable=True, server_default=FetchedValue())
    from_concept = Column('from_concept', Text, nullable=True, server_default=FetchedValue())
    to_concept = Column('to_concept', Text, nullable=True, server_default=FetchedValue())
    depth = Column('depth', Integer, nullable=True, server_default=FetchedValue())


class Term(Base):
    __tablename__ = 'bm_term'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    term = Column('term', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    source_product = Column('source_product', Text, nullable=True, server_default=FetchedValue())
    term_type = Column('term_type', Text, nullable=True, server_default=FetchedValue())
    code_system = Column('code_system', Text, nullable=True, server_default=FetchedValue())
    standard_code = Column('standard_code', Text, nullable=True, server_default=FetchedValue())
