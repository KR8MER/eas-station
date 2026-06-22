"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

Database and extension singletons for the EAS Station application.
This module provides SQLAlchemy database session management and shared
application extension helpers.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.ext.declarative import declarative_base
from typing import Generator, Optional
import os

# Global variables for lazy initialization
_engine = None
_SessionLocal = None
_db_session = None

def init_db(database_url: str):
    """
    Initialize the database engine and session factory.
    Must be called before using database operations.
    """
    global _engine, _SessionLocal, _db_session

    if not database_url:
        raise ValueError("DATABASE_URL cannot be empty")

    # Create SQLAlchemy engine with connection pooling
    _engine = create_engine(
        database_url,
        connect_args={'connect_timeout': 10},
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        echo_pool=False,
    )

    # Create session factory
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # Create scoped session for thread-safe access
    _db_session = scoped_session(_SessionLocal)

    return _engine

def get_engine():
    """Get the database engine. Raises error if not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine

def get_session_local():
    """Get the SessionLocal factory. Raises error if not initialized."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal

def get_db_session():
    """Get the scoped db_session. Raises error if not initialized."""
    if _db_session is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db_session

# Expose properties for backward compatibility
@property
def engine():
    return get_engine()

@property
def SessionLocal():
    return get_session_local()

@property
def db_session():
    return get_db_session()

# Base class for models
Base = declarative_base()

# Dependency to get database session
def get_db() -> Generator[Session, None, None]:
    """
    Dependency function that yields a database session.
    Use this with FastAPI's Depends() to get a database session in your routes.

    Example:
        @app.get("/items")
        async def get_items(db: Session = Depends(get_db)):
            items = db.query(Item).all()
            return items
    """
    session_local = get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()

# Global RadioManager instance for SDR receivers
radio_manager = None

def get_radio_manager():
    """Get the global RadioManager instance."""
    global radio_manager
    if radio_manager is None:
        from app_core.radio import RadioManager
        radio_manager = RadioManager()
        radio_manager.register_builtin_drivers()
    return radio_manager

# Import get_redis_client for backward compatibility
from app_core.redis_client import get_redis_client

__all__ = [
    "init_db",
    "get_engine",
    "get_session_local",
    "get_db_session",
    "Base",
    "get_db",
    "get_radio_manager",
    "get_redis_client",
]
