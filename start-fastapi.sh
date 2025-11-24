#!/bin/bash
#
# EAS Station - FastAPI Startup Script
# Starts the FastAPI application with uvicorn
#

set -e

echo "===================================="
echo "EAS Station - FastAPI Application"
echo "===================================="
echo ""

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Warning: No virtual environment found at ./venv"
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/upgrade FastAPI dependencies
echo "Installing FastAPI dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements-fastapi.txt

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found"
    echo "Creating .env file from example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env
        echo "DATABASE_URL=postgresql+asyncpg://eas:eas@localhost:5432/eas" >> .env
        echo "REDIS_URL=redis://localhost:6379/0" >> .env
        echo "FASTAPI_PORT=8001" >> .env
        echo "DEBUG=true" >> .env
    fi
fi

# Export environment variables
export $(grep -v '^#' .env | xargs)

# Default port (8002 - 8001 is used by Icecast)
PORT=${FASTAPI_PORT:-8002}

echo ""
echo "Starting FastAPI application..."
echo "Port: $PORT"
echo "Debug mode: ${DEBUG:-false}"
echo ""
echo "API Documentation available at:"
echo "  - Swagger UI:  http://localhost:$PORT/api/docs"
echo "  - ReDoc:       http://localhost:$PORT/api/redoc"
echo "  - OpenAPI JSON: http://localhost:$PORT/api/openapi.json"
echo ""
echo "WebSocket endpoint:"
echo "  - ws://localhost:$PORT/ws"
echo ""
echo "Press Ctrl+C to stop the server"
echo "===================================="
echo ""

# Start uvicorn with auto-reload in debug mode
if [ "${DEBUG}" = "true" ]; then
    uvicorn app_fastapi:app \
        --host 0.0.0.0 \
        --port $PORT \
        --reload \
        --log-level info
else
    uvicorn app_fastapi:app \
        --host 0.0.0.0 \
        --port $PORT \
        --workers 4 \
        --log-level info
fi
