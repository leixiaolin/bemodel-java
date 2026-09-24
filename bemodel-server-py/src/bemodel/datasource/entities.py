# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class Datasource(Base):
    __tablename__ = 'bm_datasource'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    ds_name = Column('ds_name', Text, nullable=True, server_default=FetchedValue())
    product_name = Column('product_name', Text, nullable=True, server_default=FetchedValue())
    db_type = Column('db_type', Text, nullable=True, server_default=FetchedValue())
    host = Column('host', Text, nullable=True, server_default=FetchedValue())
    port = Column('port', Integer, nullable=True, server_default=FetchedValue())
    db_name = Column('db_name', Text, nullable=True, server_default=FetchedValue())
    username = Column('username', Text, nullable=True, server_default=FetchedValue())
    password = Column('password', Text, nullable=True, server_default=FetchedValue())
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    deleted = Column('deleted', Integer, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class Mapping(Base):
    __tablename__ = 'bm_mapping'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    table_name = Column('table_name', Text, nullable=True, server_default=FetchedValue())
    column_name = Column('column_name', Text, nullable=True, server_default=FetchedValue())
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    attr_code = Column('attr_code', Text, nullable=True, server_default=FetchedValue())
    value_map = Column('value_map', Text, nullable=True, server_default=FetchedValue())
    confirmed = Column('confirmed', Integer, nullable=True, server_default=FetchedValue())
    source = Column('source', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class PhysicalColumn(Base):
    __tablename__ = 'bm_physical_column'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    table_name = Column('table_name', Text, nullable=True, server_default=FetchedValue())
    column_name = Column('column_name', Text, nullable=True, server_default=FetchedValue())
    data_type = Column('data_type', Text, nullable=True, server_default=FetchedValue())
    column_comment = Column('column_comment', Text, nullable=True, server_default=FetchedValue())
    is_pk = Column('is_pk', Integer, nullable=True, server_default=FetchedValue())
    ordinal_position = Column('ordinal_position', Integer, nullable=True, server_default=FetchedValue())


class PhysicalTable(Base):
    __tablename__ = 'bm_physical_table'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    table_name = Column('table_name', Text, nullable=True, server_default=FetchedValue())
    table_comment = Column('table_comment', Text, nullable=True, server_default=FetchedValue())
    scanned_at = Column('scanned_at', DateTime, nullable=True, server_default=FetchedValue())
