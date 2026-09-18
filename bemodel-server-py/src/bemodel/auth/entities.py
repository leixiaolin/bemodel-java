# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class PlatformUser(Base):
    __tablename__ = 'bm_user'
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    username = Column('username', Text, nullable=True, server_default=FetchedValue())
    password_hash = Column('password_hash', Text, nullable=True, server_default=FetchedValue())
    display_name = Column('display_name', Text, nullable=True, server_default=FetchedValue())
    role = Column('role', Text, nullable=True, server_default=FetchedValue())
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
