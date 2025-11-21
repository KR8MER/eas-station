#!/bin/bash
set -e

echo "=== EAS Station Database Fix Script ==="
echo "This will fix the storage_zone_codes column error"
echo ""

# Stop everything
echo "1. Stopping all containers..."
docker compose down

# Clean Python cache
echo "2. Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Start database only
echo "3. Starting database..."
docker compose up -d alerts-db
sleep 5

# Check if storage_zone_codes column exists
echo "4. Checking for problematic column..."
COLUMN_EXISTS=$(docker compose exec -T alerts-db psql -U easstation -d easalerts -tAc \
  "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='location_settings' AND column_name='storage_zone_codes';")

if [ "$COLUMN_EXISTS" -gt "0" ]; then
    echo "   Column exists, dropping it..."
    docker compose exec -T alerts-db psql -U easstation -d easalerts -c \
      "ALTER TABLE location_settings DROP COLUMN storage_zone_codes;"
    echo "   ✓ Column dropped"
else
    echo "   ✓ Column doesn't exist (good)"
fi

# Rebuild app container (clears cache)
echo "5. Rebuilding application container..."
docker compose build --no-cache eas-app

# Run migrations
echo "6. Running database migrations..."
docker compose run --rm eas-app flask db upgrade heads

# Start everything
echo "7. Starting all services..."
docker compose up -d

# Wait for startup
echo "8. Waiting for services to start..."
sleep 10

# Check logs
echo "9. Checking application logs..."
docker compose logs --tail=50 eas-app

echo ""
echo "=== Done! ==="
echo ""
echo "If you see 'Application startup complete', you're good to go!"
echo "Otherwise, check logs with: docker compose logs -f eas-app"
