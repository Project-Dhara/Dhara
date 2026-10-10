"""SQLAlchemy declarative base and metadata registry."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared ORM base for all models."""
