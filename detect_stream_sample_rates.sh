#!/bin/bash
# Auto-detect native sample rates for HTTP audio streams
# Uses ffprobe to query each stream's actual audio format

set -e

echo "================================================================================"
echo "Auto-Detecting Stream Sample Rates"
echo "================================================================================"
echo ""

# Get database connection info
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-alerts}"

# Get list of stream sources from database
echo "Fetching HTTP/stream sources from database..."
STREAM_SOURCES=$(docker-compose exec -T alerts-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -F'|' -c "
SELECT
    name,
    config->'device_params'->>'stream_url' as stream_url,
    (config->>'sample_rate')::int as current_rate
FROM audio_source_configs
WHERE source_type = 'stream' AND enabled = true AND config->'device_params'->>'stream_url' IS NOT NULL
ORDER BY name;
")

if [ -z "$STREAM_SOURCES" ]; then
    echo "No HTTP streams found in database."
    exit 0
fi

echo ""
echo "Found streams to probe:"
echo "--------------------------------------------------------------------------------"
echo "$STREAM_SOURCES" | awk -F'|' '{printf "  - %s (currently: %s Hz)\n", $1, $3}'
echo ""

# Create SQL update script
SQL_FILE="/tmp/update_stream_rates_$$.sql"
cat > "$SQL_FILE" << 'EOF'
-- Auto-generated sample rate updates based on stream detection
BEGIN;

\echo 'Updating stream sample rates based on auto-detection...'

EOF

# Probe each stream
UPDATES_MADE=0
while IFS='|' read -r name stream_url current_rate; do
    if [ -z "$stream_url" ]; then
        continue
    fi

    echo "Probing: $name"
    echo "  URL: $stream_url"

    # Use ffprobe to detect actual stream sample rate
    # Timeout after 10 seconds if stream doesn't respond
    DETECTED_RATE=$(timeout 10 ffprobe -v error -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$stream_url" 2>/dev/null | head -1 || echo "")

    if [ -z "$DETECTED_RATE" ] || [ "$DETECTED_RATE" = "N/A" ]; then
        echo "  ⚠️  Could not detect sample rate (stream may be offline)"
        # Try to resolve playlist first if it's an M3U
        if [[ "$stream_url" =~ \.m3u8?$ ]]; then
            echo "  Attempting to resolve M3U playlist..."
            RESOLVED_URL=$(timeout 10 curl -s "$stream_url" | grep -v '^#' | grep -E '^https?://' | head -1 || echo "")
            if [ -n "$RESOLVED_URL" ]; then
                echo "  Resolved to: $RESOLVED_URL"
                DETECTED_RATE=$(timeout 10 ffprobe -v error -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$RESOLVED_URL" 2>/dev/null | head -1 || echo "")
            fi
        fi
    fi

    if [ -z "$DETECTED_RATE" ] || [ "$DETECTED_RATE" = "N/A" ]; then
        # Fallback to 44100 if detection fails
        DETECTED_RATE=44100
        echo "  ℹ️  Using fallback rate: ${DETECTED_RATE} Hz (stream unreachable)"
    else
        echo "  ✅ Detected native rate: ${DETECTED_RATE} Hz"
    fi

    # Only update if different from current
    if [ "$DETECTED_RATE" != "$current_rate" ]; then
        echo "  🔧 Will update: $current_rate Hz → $DETECTED_RATE Hz"

        # Add SQL update statement
        cat >> "$SQL_FILE" << EOSQL
UPDATE audio_source_configs
SET config = jsonb_set(config, '{sample_rate}', '${DETECTED_RATE}'::jsonb)
WHERE name = '${name}' AND source_type = 'stream';

EOSQL
        UPDATES_MADE=$((UPDATES_MADE + 1))
    else
        echo "  ℹ️  Already correct, no update needed"
    fi

    echo ""
done <<< "$STREAM_SOURCES"

# Finalize SQL file
cat >> "$SQL_FILE" << 'EOF'

\echo 'Sample rate updates complete.'

SELECT
    name,
    source_type,
    (config->>'sample_rate')::int as new_sample_rate,
    (config->>'channels')::int as channels
FROM audio_source_configs
WHERE source_type = 'stream' AND enabled = true
ORDER BY name;

COMMIT;
EOF

echo "================================================================================"
echo "Detection Summary"
echo "================================================================================"
echo ""
echo "Streams needing updates: $UPDATES_MADE"
echo ""

if [ $UPDATES_MADE -gt 0 ]; then
    echo "Generated SQL update script: $SQL_FILE"
    echo ""
    read -p "Apply these updates to the database? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Applying updates..."
        docker-compose exec -T alerts-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SQL_FILE"

        if [ $? -eq 0 ]; then
            echo ""
            echo "✅ Updates applied successfully!"
            echo ""
            echo "Next step: Restart the audio service"
            echo "  docker-compose restart sdr-service"
        else
            echo ""
            echo "❌ Failed to apply updates"
            exit 1
        fi
    else
        echo "Updates cancelled. SQL script saved to: $SQL_FILE"
    fi
else
    echo "All streams already have correct sample rates!"
    rm -f "$SQL_FILE"
fi

echo ""
echo "================================================================================"
