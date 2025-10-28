"""Flask extension singletons used across the NOAA alerts application."""

from flask_sqlalchemy import SQLAlchemy

# SQLAlchemy is initialised via the application factory in ``app.py``.
db = SQLAlchemy()

__all__ = ["db"]
