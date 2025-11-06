#!/bin/bash
set -e

echo "Starting EAS Station..."

# Verify .env is a file, not a directory
# (Should not happen anymore since we include .env in the repo)
if [ -d "/app/.env" ]; then
    echo "ERROR: .env is a directory instead of a file."
    echo "This should not happen with the latest repository version."
    echo ""
    echo "To fix this in Portainer:"
    echo "  1. Stop and remove the stack"
    echo "  2. Redeploy from the latest Git repository"
    echo "  3. The .env file is now included in the repo"
    echo ""
    exit 1
fi

# Ensure .env exists (should already exist from Git)
if [ ! -f "/app/.env" ]; then
    echo "WARNING: .env file not found, creating empty file..."
    touch /app/.env
fi

# Run database migrations with retry logic
# This is safe to run concurrently - Alembic handles locking
echo "Running database migrations..."
max_attempts=5
attempt=0

# Set flag to skip database initialization during migrations
export SKIP_DB_INIT=1

while [ $attempt -lt $max_attempts ]; do
    if python -m alembic upgrade head; then
        echo "Migrations complete."
        break
    else
        attempt=$((attempt + 1))
        if [ $attempt -lt $max_attempts ]; then
            echo "Migration attempt $attempt failed. Retrying in 2 seconds..."
            sleep 2
        else
            echo "Migration failed after $max_attempts attempts. Continuing anyway..."
        fi
    fi
done

# Unset the flag after migrations are complete
unset SKIP_DB_INIT

echo "Starting application..."

# Execute the main command (gunicorn, poller, etc.)
exec "$@"
