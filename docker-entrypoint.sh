#!/bin/bash
set -e

echo "Starting EAS Station..."

# Check if .env is mounted as a directory (Docker does this if file doesn't exist on host)
if [ -d "/app/.env" ]; then
    echo "ERROR: .env was created as a directory by Docker."
    echo "This happens when .env doesn't exist on the host before starting containers."
    echo ""
    echo "To fix this:"
    echo "  1. Stop the containers: docker-compose down"
    echo "  2. Create an empty .env file: touch .env"
    echo "  3. Start the containers: docker-compose up -d"
    echo ""
    echo "After setup, the setup wizard will populate the .env file."
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f "/app/.env" ]; then
    echo "Creating empty .env file..."
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
