#!/bin/bash
# Debug script to check what's in the .env files

echo "=========================================="
echo "ENV FILE DEBUG"
echo "=========================================="

for file in /app-config/.env /app-config/noaa.env /app-config/ipaws.env; do
    if [ -f "$file" ]; then
        echo ""
        echo "File: $file"
        echo "Size: $(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo "unknown") bytes"
        echo "Content (with line numbers and special chars visible):"
        cat -A "$file" | head -20
        echo ""
        echo "Non-comment, non-blank lines:"
        HAS_CONFIG=$(grep -v "^#" "$file" 2>/dev/null | grep -v "^[[:space:]]*$" | wc -l)
        echo "Count: $HAS_CONFIG"
        if [ "$HAS_CONFIG" -gt 0 ]; then
            echo "Lines found:"
            grep -v "^#" "$file" 2>/dev/null | grep -v "^[[:space:]]*$" | head -10
        fi
        echo "----------------------------------------"
    else
        echo "File $file does not exist"
    fi
done

echo ""
echo "Environment variables (database):"
echo "POSTGRES_HOST=${POSTGRES_HOST}"
echo "POSTGRES_PORT=${POSTGRES_PORT}"
echo "POSTGRES_DB=${POSTGRES_DB}"
echo "POSTGRES_USER=${POSTGRES_USER}"
echo "POSTGRES_PASSWORD=${POSTGRES_PASSWORD:+***SET***}"
echo "=========================================="
