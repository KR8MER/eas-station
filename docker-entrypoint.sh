#!/bin/bash
set -e
set -o pipefail

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
# Allow poller-specific overrides (IPAWS/NOAA) so sidecar containers honour
# the mounted /app-config volume even if CONFIG_PATH is not provided directly.
CONFIG_PATH_EFFECTIVE="$CONFIG_PATH"
POLLER_MODE_UPPER="$(echo "${CAP_POLLER_MODE:-}" | tr '[:lower:]' '[:upper:]')"

if [ -z "$CONFIG_PATH_EFFECTIVE" ]; then
    if [ "$POLLER_MODE_UPPER" = "IPAWS" ] && [ -n "$IPAWS_CONFIG_PATH" ]; then
        CONFIG_PATH_EFFECTIVE="$IPAWS_CONFIG_PATH"
    elif [ "$POLLER_MODE_UPPER" = "NOAA" ] && [ -n "$NOAA_CONFIG_PATH" ]; then
        CONFIG_PATH_EFFECTIVE="$NOAA_CONFIG_PATH"
    elif [ -n "$IPAWS_CONFIG_PATH" ]; then
        CONFIG_PATH_EFFECTIVE="$IPAWS_CONFIG_PATH"
    elif [ -n "$NOAA_CONFIG_PATH" ]; then
        CONFIG_PATH_EFFECTIVE="$NOAA_CONFIG_PATH"
    fi
fi

# Ensure downstream processes see CONFIG_PATH even when only the
# poller-specific variables were provided.
if [ -n "$CONFIG_PATH_EFFECTIVE" ] && [ -z "$CONFIG_PATH" ]; then
    export CONFIG_PATH="$CONFIG_PATH_EFFECTIVE"
fi

if [ -n "$CONFIG_PATH_EFFECTIVE" ]; then
    CONFIG_DIR=$(dirname "$CONFIG_PATH_EFFECTIVE")

    echo "Using persistent config location: $CONFIG_PATH_EFFECTIVE"

    # Create directory if it doesn't exist
    if [ ! -d "$CONFIG_DIR" ]; then
        echo "Creating config directory: $CONFIG_DIR"
        mkdir -p "$CONFIG_DIR"
    fi

    # Create .env file if it doesn't exist or initialize from environment if empty
    if [ ! -f "$CONFIG_PATH_EFFECTIVE" ]; then
        echo "Initializing persistent .env file at: $CONFIG_PATH_EFFECTIVE"
        # Create with header
        cat > "$CONFIG_PATH_EFFECTIVE" <<'EOF'
# EAS Station Environment Configuration
#
# This file is managed by the Setup Wizard and persists across deployments.
# Navigate to http://localhost/setup to configure.
#

EOF
        chmod 666 "$CONFIG_PATH_EFFECTIVE"
        echo "✅ Created .env file at $CONFIG_PATH_EFFECTIVE"
    else
        echo "✅ Using existing .env file at: $CONFIG_PATH_EFFECTIVE ($(stat -f%z "$CONFIG_PATH_EFFECTIVE" 2>/dev/null || stat -c%s "$CONFIG_PATH_EFFECTIVE" 2>/dev/null || echo "unknown") bytes)"
        # Ensure it's writable
        chmod 666 "$CONFIG_PATH_EFFECTIVE" 2>/dev/null || echo "⚠️  Warning: Could not set permissions on $CONFIG_PATH_EFFECTIVE"
    fi

    # Check if the file has no configuration (only comments/whitespace) and populate from environment
    # Note: Don't check file size - a file with only the header comment can be > 100 bytes
    # Disable pipefail temporarily because grep returns 1 when no matches found (which is expected)
    set +o pipefail
    HAS_CONFIG=$(grep -v "^#" "$CONFIG_PATH_EFFECTIVE" 2>/dev/null | grep -v "^[[:space:]]*$" | wc -l)
    set -o pipefail

    echo "🔍 DEBUG: HAS_CONFIG check result: $HAS_CONFIG config lines found"

    if [ "$HAS_CONFIG" -eq 0 ]; then
        echo "⚙️  Persistent .env file is empty (no configuration)"
        echo "   Initializing from environment variables (stack.env)..."

        # Append environment variables to the config file
        # This transfers configuration from stack.env (loaded as env vars) to the persistent file
        # NOTE: Database settings (POSTGRES_*) are NOT stored here - they must come from
        # environment variables to ensure all containers use consistent database connection settings.
        # This prevents issues where pollers use different database settings than the app container.
        cat >> "$CONFIG_PATH_EFFECTIVE" <<EOF

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
# Database settings are managed via environment variables in docker-compose.yml
# to ensure consistency across all containers (app, noaa-poller, ipaws-poller).
# Do NOT set POSTGRES_* values here - they will be ignored in favor of
# environment variables to prevent configuration drift between containers.

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
        echo "   📝 File location: $CONFIG_PATH_EFFECTIVE"
        echo "   ℹ️  The application will now start normally without setup wizard"
    fi
fi

# Auto-fix common database schema issues before migrations
echo "Checking for schema issues..."
if [ -n "$POSTGRES_HOST" ] && [ -n "$POSTGRES_USER" ] && [ -n "$POSTGRES_DB" ]; then
    python3 <<'PYEOF'
import os
import psycopg2
import time

max_retries = 10
retry_delay = 2

for attempt in range(max_retries):
    try:
        conn = psycopg2.connect(
            host=os.environ.get('POSTGRES_HOST', 'alerts-db'),
            port=os.environ.get('POSTGRES_PORT', '5432'),
            user=os.environ.get('POSTGRES_USER', 'postgres'),
            password=os.environ.get('POSTGRES_PASSWORD', 'postgres'),
            database=os.environ.get('POSTGRES_DB', 'alerts'),
            connect_timeout=5
        )
        conn.autocommit = False
        cur = conn.cursor()

        fixes_applied = []

        # Fix 1: Drop problematic storage_zone_codes column
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name='location_settings'
            AND column_name='storage_zone_codes'
        """)
        if cur.fetchone()[0] > 0:
            cur.execute("ALTER TABLE location_settings DROP COLUMN storage_zone_codes")
            fixes_applied.append("Dropped storage_zone_codes column")

        # Fix 2: Clean up duplicate alembic_version entries (migration conflicts)
        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'alembic_version'
            """
        )
        if cur.fetchone()[0] == 1:
            cur.execute("SELECT COUNT(*) FROM alembic_version")
            version_count = cur.fetchone()[0]
            if version_count > 1:
                # Keep only the most recent version (ordered deterministically)
                cur.execute("""
                    DELETE FROM alembic_version
                    WHERE version_num NOT IN (
                        SELECT version_num FROM alembic_version
                        ORDER BY version_num DESC
                        LIMIT 1
                    )
                """)
                fixes_applied.append(f"Cleaned {version_count - 1} duplicate migration version(s)")
        else:
            fixes_applied.append("Skipped alembic_version cleanup (table missing)")

        if fixes_applied:
            conn.commit()
            print("🔧 Auto-fixed schema issues:")
            for fix in fixes_applied:
                print(f"   ✅ {fix}")
        else:
            print("✅ Schema OK - no fixes needed")

        cur.close()
        conn.close()
        break

    except psycopg2.OperationalError as e:
        if attempt < max_retries - 1:
            print(f"Database not ready (attempt {attempt + 1}/{max_retries}), waiting {retry_delay}s...")
            time.sleep(retry_delay)
        else:
            print(f"⚠️  Could not connect to database after {max_retries} attempts, continuing anyway...")
    except Exception as e:
        print(f"⚠️  Schema check failed: {e}")
        print("   Continuing with migrations anyway...")
        break
PYEOF
fi

# Run database migrations with retry logic
# This is safe to run concurrently - Alembic handles locking
echo "Running database migrations..."
max_attempts=5
attempt=0

# Set flag to skip database initialization during migrations
export SKIP_DB_INIT=1

while [ $attempt -lt $max_attempts ]; do
    if python -m alembic upgrade head 2>&1 | tee /tmp/migration.log; then
        echo "✅ Migrations complete."
        break
    else
        attempt=$((attempt + 1))
        if [ $attempt -lt $max_attempts ]; then
            echo "⚠️  Migration attempt $attempt failed. Retrying in 2 seconds..."
            sleep 2
        else
            echo "⚠️  WARNING: Migrations failed after $max_attempts attempts."
            echo "   Application will start anyway, but may have schema mismatches."
            echo "   Check logs above for errors. You may need to fix migrations manually."
            # Don't exit - allow app to start
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
