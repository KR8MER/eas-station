"""
Async Database Configuration for FastAPI
Uses SQLAlchemy 2.0 with asyncpg driver
"""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from fastapi_app.config import settings

logger = logging.getLogger(__name__)

# Convert DATABASE_URL to async format if needed
database_url = settings.database_url
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql+psycopg2://"):
    database_url = database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

logger.info(f"Using async database URL: {database_url.split('@')[0]}@***")

# Create async engine
engine = create_async_engine(
    database_url,
    echo=settings.debug,  # Log SQL queries in debug mode
    future=True,
    pool_pre_ping=True,  # Verify connections before using them
    pool_size=20,  # Connection pool size
    max_overflow=10,  # Maximum overflow connections
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Import Base from existing models to maintain compatibility
# We'll import from app_core.extensions which defines the Flask-SQLAlchemy db object
# For FastAPI, we need to access the underlying declarative base
try:
    from app_core.extensions import db as flask_db
    # Get the declarative base from Flask-SQLAlchemy
    Base = flask_db.Model.metadata
    logger.info("Using existing Flask-SQLAlchemy models")
except ImportError:
    # Fallback: create new base if needed
    Base = declarative_base()
    logger.warning("Created new declarative base - models may not be compatible with Flask")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function to get async database session.

    Usage in FastAPI routes:
        @router.get("/items")
        async def read_items(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Item))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database connection and verify it works.
    Called during application startup.
    """
    try:
        async with engine.begin() as conn:
            # Test connection
            await conn.run_sync(lambda conn: conn.execute("SELECT 1"))
        logger.info("Database connection established successfully")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


async def close_db() -> None:
    """
    Close database connections.
    Called during application shutdown.
    """
    await engine.dispose()
    logger.info("Database connections closed")
