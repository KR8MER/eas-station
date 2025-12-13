#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System (FastAPI Minimal Version)
Copyright (c) 2025 Timothy Kramer (KR8MER)

Minimal working FastAPI application for testing and gradual migration.
This version has no Flask dependencies and can run independently.
"""

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
try:
    load_dotenv(override=True)
except (PermissionError, FileNotFoundError, OSError) as e:
    logger.warning(f"Could not load .env file: {e}. Using environment variables only.")

# Configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '*').split(',')

# =============================================================================
# LIFESPAN CONTEXT
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context for startup and shutdown events."""
    # STARTUP
    logger.info("=" * 80)
    logger.info("EAS Station FastAPI - Minimal Version Starting")
    logger.info("=" * 80)

    try:
        # Get version info
        from app_utils.versioning import get_current_version
        version = get_current_version()
        logger.info(f"Version: {version}")
        app.state.version = version
    except Exception as e:
        logger.warning(f"Could not load version info: {e}")
        app.state.version = "unknown"

    logger.info(f"Secret Key Length: {len(SECRET_KEY)} chars")
    logger.info(f"CORS Origins: {CORS_ALLOWED_ORIGINS}")
    logger.info("FastAPI app ready to accept requests")
    logger.info("=" * 80)

    yield  # Application runs here

    # SHUTDOWN
    logger.info("EAS Station FastAPI - Shutting down")

# =============================================================================
# CREATE FASTAPI APP
# =============================================================================

app = FastAPI(
    title="EAS Station",
    description="Emergency Alert System Platform (Minimal FastAPI)",
    version="3.0.0-minimal",
    lifespan=lifespan,
)

# Store configuration
app.state.secret_key = SECRET_KEY

# =============================================================================
# MIDDLEWARE
# =============================================================================

# Session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=43200,  # 12 hours
    same_site="lax",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in CORS_ALLOWED_ORIGINS else CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# =============================================================================
# BASIC ROUTES
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>EAS Station - FastAPI</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 { color: #2c3e50; }
            .status { color: #27ae60; font-weight: bold; }
            .endpoint {
                background: #ecf0f1;
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
                font-family: monospace;
            }
            a { color: #3498db; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚨 EAS Station - FastAPI</h1>
            <p class="status">✅ FastAPI server is running!</p>

            <h2>Available Endpoints:</h2>
            <div class="endpoint">GET <a href="/health">/health</a> - Health check</div>
            <div class="endpoint">GET <a href="/api/status">/api/status</a> - System status</div>
            <div class="endpoint">GET <a href="/docs">/docs</a> - Interactive API documentation</div>
            <div class="endpoint">GET <a href="/redoc">/redoc</a> - ReDoc API documentation</div>

            <h2>Migration Progress:</h2>
            <ul>
                <li>✅ FastAPI core application</li>
                <li>✅ Basic middleware (CORS, Sessions)</li>
                <li>✅ Health check endpoint</li>
                <li>⏳ Database integration</li>
                <li>⏳ Authentication system</li>
                <li>⏳ WebSocket support</li>
                <li>⏳ Route migration (0/51 modules)</li>
            </ul>

            <p><small>Version: """ + app.state.version + """</small></p>
        </div>
    </body>
    </html>
    """)

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and orchestration"""
    return {
        "status": "healthy",
        "service": "eas-station-fastapi",
        "version": app.state.version,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "framework": "FastAPI",
    }

@app.get("/api/status")
async def system_status():
    """Basic system status endpoint (migrated from Flask)"""
    import psutil

    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            "status": "operational",
            "version": app.state.version,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "system": {
                "cpu_percent": cpu_percent,
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "percent_used": memory.percent,
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "percent_used": disk.percent,
                },
            },
            "framework": "FastAPI",
            "migration_status": "minimal_version",
        }
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "version": app.state.version,
            }
        )

@app.get("/api/version")
async def get_version():
    """Get application version information"""
    return {
        "version": app.state.version,
        "framework": "FastAPI",
        "python_version": os.sys.version,
    }

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler"""
    if request.url.path.startswith('/api/'):
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "path": request.url.path,
                "message": "The requested endpoint does not exist"
            }
        )

    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>404 - Not Found</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 50px;
                    background: #f5f5f5;
                }
                .error-container {
                    background: white;
                    padding: 40px;
                    border-radius: 8px;
                    max-width: 500px;
                    margin: 0 auto;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                h1 { color: #e74c3c; }
                a { color: #3498db; }
            </style>
        </head>
        <body>
            <div class="error-container">
                <h1>404 - Page Not Found</h1>
                <p>The page you're looking for doesn't exist.</p>
                <p><a href="/">← Go Home</a></p>
            </div>
        </body>
        </html>
        """,
        status_code=404
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Custom 500 handler"""
    logger.error(f"Internal server error: {exc}", exc_info=True)

    if request.url.path.startswith('/api/'):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred"
            }
        )

    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>500 - Internal Server Error</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 50px;
                    background: #f5f5f5;
                }
                .error-container {
                    background: white;
                    padding: 40px;
                    border-radius: 8px;
                    max-width: 500px;
                    margin: 0 auto;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                h1 { color: #e74c3c; }
                a { color: #3498db; }
            </style>
        </head>
        <body>
            <div class="error-container">
                <h1>500 - Internal Server Error</h1>
                <p>Something went wrong on our end.</p>
                <p><a href="/">← Go Home</a></p>
            </div>
        </body>
        </html>
        """,
        status_code=500
    )

# =============================================================================
# STATIC FILES (if exists)
# =============================================================================

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# =============================================================================
# DEVELOPMENT SERVER
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting FastAPI development server...")
    logger.info("Documentation available at: http://localhost:8080/docs")

    uvicorn.run(
        "fastapi_app_minimal:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
    )
