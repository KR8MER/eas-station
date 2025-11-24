#!/usr/bin/env python3
"""
EAS Station - FastAPI Application
Copyright (c) 2025 Timothy Kramer (KR8MER)

FastAPI-based async API for Emergency Alert System
Provides 3-5x better performance than Flask with native async support

This file is part of EAS Station.
EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

Repository: https://github.com/KR8MER/eas-station
Version: 3.0.0-alpha - FastAPI Migration
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Import FastAPI routers
from fastapi_app.routers import audio, alerts, system, eas_monitor, websocket
from fastapi_app.database import engine, init_db
from fastapi_app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting EAS Station FastAPI application...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # TODO: Initialize audio services
    # TODO: Initialize WebSocket manager
    # TODO: Start background tasks (health monitoring, etc.)

    yield

    # Shutdown
    logger.info("Shutting down EAS Station FastAPI application...")
    # TODO: Cleanup resources
    await engine.dispose()
    logger.info("Database connections closed")


# Create FastAPI application
app = FastAPI(
    title="EAS Station API",
    description="""
    Emergency Alert System (EAS) Station - Modern async API

    This API provides high-performance endpoints for:
    - Emergency alert management (CAP/SAME)
    - Real-time audio monitoring and streaming
    - System health and diagnostics
    - Geographic boundary intelligence

    **Features:**
    - 🚀 3-5x faster than Flask
    - ⚡ Native async/await support
    - 📡 Native WebSocket support
    - 🔒 Type-safe with Pydantic validation
    - 📖 Auto-generated OpenAPI documentation

    **Author:** KR8MER Amateur Radio Emergency Communications
    **License:** AGPL-3.0 / Commercial
    """,
    version="3.0.0-alpha",
    docs_url="/api/docs",  # Swagger UI at /api/docs
    redoc_url="/api/redoc",  # ReDoc at /api/redoc
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
    debug=settings.debug,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Mount static files (compatible with Flask structure)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates (compatible with Flask templates)
templates = Jinja2Templates(directory="templates")


# Include routers
app.include_router(audio.router, prefix="/api/audio", tags=["Audio"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
app.include_router(eas_monitor.router, prefix="/api/eas-monitor", tags=["EAS Monitor"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(websocket.router, tags=["WebSocket"])  # WebSocket at /ws


@app.get("/")
async def root():
    """Root endpoint - redirect to API docs"""
    return {
        "message": "EAS Station FastAPI",
        "version": "3.0.0-alpha",
        "docs": "/api/docs",
        "redoc": "/api/redoc",
        "status": "operational"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers and monitoring"""
    return {
        "status": "healthy",
        "version": "3.0.0-alpha",
        "environment": settings.environment
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn

    # Run with uvicorn
    uvicorn.run(
        "app_fastapi:app",
        host=settings.host,
        port=settings.fastapi_port,
        reload=settings.debug,
        log_level="info",
        access_log=True,
    )
