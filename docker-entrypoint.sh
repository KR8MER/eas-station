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

# Initialize persistent .env file if using CONFIG_PATH (persistent volume)
if [ -n "$CONFIG_PATH" ]; then
    CONFIG_DIR=$(dirname "$CONFIG_PATH")

    echo "Using persistent config location: $CONFIG_PATH"

    # Create directory if it doesn't exist
    if [ ! -d "$CONFIG_DIR" ]; then
        echo "Creating config directory: $CONFIG_DIR"
        mkdir -p "$CONFIG_DIR"
    fi

    # Create .env file if it doesn't exist or initialize from environment if empty
    if [ ! -f "$CONFIG_PATH" ]; then
        echo "Initializing persistent .env file at: $CONFIG_PATH"
        # Create with header
        cat > "$CONFIG_PATH" <<'EOF'
# EAS Station Environment Configuration
#
# This file is managed by the Setup Wizard and persists across deployments.
# Navigate to http://localhost/setup to configure.
#

EOF
        chmod 666 "$CONFIG_PATH"
        echo "✅ Created .env file at $CONFIG_PATH"
    else
        echo "✅ Using existing .env file at: $CONFIG_PATH ($(stat -f%z "$CONFIG_PATH" 2>/dev/null || stat -c%s "$CONFIG_PATH" 2>/dev/null || echo "unknown") bytes)"
        # Ensure it's writable
        chmod 666 "$CONFIG_PATH" 2>/dev/null || echo "⚠️  Warning: Could not set permissions on $CONFIG_PATH"
    fi

    # Check if the file is essentially empty (< 100 bytes and no non-comment lines) and populate from environment
    FILE_SIZE=$(stat -c%s "$CONFIG_PATH" 2>/dev/null || stat -f%z "$CONFIG_PATH" 2>/dev/null || echo "0")
    HAS_CONFIG=$(grep -v "^#" "$CONFIG_PATH" 2>/dev/null | grep -v "^[[:space:]]*$" | wc -l)

    if [ "$FILE_SIZE" -lt 100 ] && [ "$HAS_CONFIG" -eq 0 ]; then
        echo "⚙️  Persistent .env file is empty (no configuration)"
        echo "   Initializing from environment variables (stack.env)..."

        # Append environment variables to the config file
        # This transfers configuration from stack.env (loaded as env vars) to the persistent file
        cat >> "$CONFIG_PATH" <<EOF

# =============================================================================
# CORE SETTINGS (REQUIRED) - Auto-populated from environment
# =============================================================================
SECRET_KEY=${SECRET_KEY:-}

# Flask configuration
FLASK_DEBUG=${FLASK_DEBUG:-false}
FLASK_APP=${FLASK_APP:-app.py}
FLASK_RUN_HOST=${FLASK_RUN_HOST:-0.0.0.0}
FLASK_RUN_PORT=${FLASK_RUN_PORT:-5000}
FLASK_ENV=${FLASK_ENV:-production}

# Git commit hash (captured at build time)
# Only set if explicitly provided, otherwise runtime auto-detects from .git
$([ -n "${GIT_COMMIT:-}" ] && echo "GIT_COMMIT=${GIT_COMMIT}" || echo "# GIT_COMMIT not set - will auto-detect from .git metadata at runtime")

# =============================================================================
# DATABASE (PostgreSQL + PostGIS)
# =============================================================================
POSTGRES_HOST=${POSTGRES_HOST:-alerts-db}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
POSTGRES_DB=${POSTGRES_DB:-alerts}
POSTGRES_USER=${POSTGRES_USER:-postgres}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres}

# =============================================================================
# ALERT POLLING
# =============================================================================
POLL_INTERVAL_SEC=${POLL_INTERVAL_SEC:-180}
CAP_TIMEOUT=${CAP_TIMEOUT:-30}
NOAA_USER_AGENT=${NOAA_USER_AGENT:-}
CAP_ENDPOINTS=${CAP_ENDPOINTS:-}
IPAWS_CAP_FEED_URLS=${IPAWS_CAP_FEED_URLS:-}
IPAWS_DEFAULT_LOOKBACK_HOURS=${IPAWS_DEFAULT_LOOKBACK_HOURS:-12}

# =============================================================================
# LOCATION SETTINGS
# =============================================================================
DEFAULT_TIMEZONE=${DEFAULT_TIMEZONE:-America/New_York}
DEFAULT_COUNTY_NAME=${DEFAULT_COUNTY_NAME:-}
DEFAULT_STATE_CODE=${DEFAULT_STATE_CODE:-}
DEFAULT_ZONE_CODES=${DEFAULT_ZONE_CODES:-}
DEFAULT_MAP_CENTER_LAT=${DEFAULT_MAP_CENTER_LAT:-}
DEFAULT_MAP_CENTER_LNG=${DEFAULT_MAP_CENTER_LNG:-}
DEFAULT_MAP_ZOOM=${DEFAULT_MAP_ZOOM:-9}

# =============================================================================
# EAS BROADCAST (SAME/EAS ENCODER)
# =============================================================================
EAS_BROADCAST_ENABLED=${EAS_BROADCAST_ENABLED:-true}
EAS_ORIGINATOR=${EAS_ORIGINATOR:-EAS}
EAS_STATION_ID=${EAS_STATION_ID:-}
EAS_OUTPUT_DIR=${EAS_OUTPUT_DIR:-static/eas_messages}
EAS_ATTENTION_TONE_SECONDS=${EAS_ATTENTION_TONE_SECONDS:-8}
EAS_SAMPLE_RATE=${EAS_SAMPLE_RATE:-44100}
EAS_AUDIO_PLAYER=${EAS_AUDIO_PLAYER:-aplay}
EAS_MANUAL_FIPS_CODES=${EAS_MANUAL_FIPS_CODES:-}
EAS_MANUAL_EVENT_CODES=${EAS_MANUAL_EVENT_CODES:-}
EAS_GPIO_PIN=${EAS_GPIO_PIN:-}
EAS_GPIO_ACTIVE_STATE=${EAS_GPIO_ACTIVE_STATE:-HIGH}
EAS_GPIO_HOLD_SECONDS=${EAS_GPIO_HOLD_SECONDS:-5}

# =============================================================================
# TEXT-TO-SPEECH (OPTIONAL)
# =============================================================================
EAS_TTS_PROVIDER=${EAS_TTS_PROVIDER:-}
AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT:-}
AZURE_OPENAI_KEY=${AZURE_OPENAI_KEY:-}
AZURE_OPENAI_VOICE=${AZURE_OPENAI_VOICE:-alloy}
AZURE_OPENAI_MODEL=${AZURE_OPENAI_MODEL:-tts-1-hd}
AZURE_OPENAI_SPEED=${AZURE_OPENAI_SPEED:-1.0}
AZURE_SPEECH_KEY=${AZURE_SPEECH_KEY:-}
AZURE_SPEECH_REGION=${AZURE_SPEECH_REGION:-}

# =============================================================================
# LED DISPLAY (OPTIONAL)
# =============================================================================
LED_SIGN_IP=${LED_SIGN_IP:-}
LED_SIGN_PORT=${LED_SIGN_PORT:-10001}
DEFAULT_LED_LINES=${DEFAULT_LED_LINES:-}

# =============================================================================
# VFD DISPLAY (OPTIONAL)
# =============================================================================
VFD_PORT=${VFD_PORT:-}
VFD_BAUDRATE=${VFD_BAUDRATE:-38400}

# =============================================================================
# NOTIFICATIONS (OPTIONAL)
# =============================================================================
ENABLE_EMAIL_NOTIFICATIONS=${ENABLE_EMAIL_NOTIFICATIONS:-false}
ENABLE_SMS_NOTIFICATIONS=${ENABLE_SMS_NOTIFICATIONS:-false}
MAIL_SERVER=${MAIL_SERVER:-}
MAIL_PORT=${MAIL_PORT:-587}
MAIL_USE_TLS=${MAIL_USE_TLS:-true}
MAIL_USERNAME=${MAIL_USERNAME:-}
MAIL_PASSWORD=${MAIL_PASSWORD:-}

# =============================================================================
# LOGGING & PERFORMANCE
# =============================================================================
LOG_LEVEL=${LOG_LEVEL:-INFO}
LOG_FILE=${LOG_FILE:-logs/eas_station.log}
WEB_ACCESS_LOG=${WEB_ACCESS_LOG:-false}
CACHE_TIMEOUT=${CACHE_TIMEOUT:-300}
MAX_WORKERS=${MAX_WORKERS:-2}
UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/uploads}

# =============================================================================
# DOCKER/INFRASTRUCTURE
# =============================================================================
TZ=${TZ:-America/New_York}
WATCHTOWER_LABEL_ENABLE=${WATCHTOWER_LABEL_ENABLE:-true}
WATCHTOWER_MONITOR_ONLY=${WATCHTOWER_MONITOR_ONLY:-false}
ALERTS_DB_IMAGE=${ALERTS_DB_IMAGE:-postgis/postgis:17-3.4}
AUDIO_INGEST_ENABLED=${AUDIO_INGEST_ENABLED:-true}
AUDIO_ALSA_ENABLED=${AUDIO_ALSA_ENABLED:-false}
AUDIO_ALSA_DEVICE=${AUDIO_ALSA_DEVICE:-}
AUDIO_SDR_ENABLED=${AUDIO_SDR_ENABLED:-false}
EOF

        echo "   ✅ Initialized persistent config with values from stack.env"
        echo "   📝 File location: $CONFIG_PATH"
        echo "   ℹ️  The application will now start normally without setup wizard"
    fi
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

# Handle Gunicorn access log configuration
# If WEB_ACCESS_LOG is set to "false" or "off", disable access logs (only show errors)
if [ "$1" = "gunicorn" ]; then
    # Check if access logs should be disabled
    if [ "${WEB_ACCESS_LOG:-true}" = "false" ] || [ "${WEB_ACCESS_LOG:-true}" = "off" ]; then
        echo "Web server access logging is DISABLED (only errors will be logged)"
        echo "Set WEB_ACCESS_LOG=true to enable access logs"

        # Reconstruct the command with access-logfile set to /dev/null
        NEW_ARGS=()
        SKIP_NEXT=false
        for arg in "$@"; do
            if [ "$SKIP_NEXT" = true ]; then
                SKIP_NEXT=false
                NEW_ARGS+=("/dev/null")
                continue
            fi

            if [ "$arg" = "--access-logfile" ]; then
                SKIP_NEXT=true
                NEW_ARGS+=("$arg")
            else
                NEW_ARGS+=("$arg")
            fi
        done

        set -- "${NEW_ARGS[@]}"
    else
        echo "Web server access logging is ENABLED"
        echo "Set WEB_ACCESS_LOG=false to disable access logs and reduce log clutter"
    fi
fi

# Execute the main command (gunicorn, poller, etc.)
exec "$@"
