#!/bin/bash
set -e

echo "Starting EAS Station..."

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
