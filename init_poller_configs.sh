#!/bin/bash
# Initialize separate config files for NOAA and IPAWS pollers

NOAA_CONFIG="/app-config/noaa.env"
IPAWS_CONFIG="/app-config/ipaws.env"
MAIN_CONFIG="/app-config/.env"

echo "Initializing poller configuration files..."

# Create noaa.env if it doesn't exist
if [ ! -f "$NOAA_CONFIG" ]; then
    echo "Creating $NOAA_CONFIG"
    cat > "$NOAA_CONFIG" <<'EOF'
# NOAA Weather Alert Poller Configuration
CAP_POLLER_MODE=NOAA

# NOAA automatically builds endpoints from location zone codes
# No need to specify CAP_ENDPOINTS or IPAWS_CAP_FEED_URLS

# Uncomment to enable debug logging:
# CAP_POLLER_DEBUG_RECORDS=1
EOF
    echo "✅ Created $NOAA_CONFIG"
else
    echo "✅ $NOAA_CONFIG already exists"
fi

# Create ipaws.env if it doesn't exist
if [ ! -f "$IPAWS_CONFIG" ]; then
    echo "Creating $IPAWS_CONFIG"

    # Try to read IPAWS_CAP_FEED_URLS from main config if it exists
    IPAWS_URL=""
    if [ -f "$MAIN_CONFIG" ]; then
        IPAWS_URL=$(grep "^IPAWS_CAP_FEED_URLS=" "$MAIN_CONFIG" | cut -d'=' -f2-)
    fi

    # Use default if not found
    if [ -z "$IPAWS_URL" ]; then
        # Calculate timestamp for 12 hours ago
        TIMESTAMP=$(date -u -d "12 hours ago" +"%Y-%m-%dT%H:%M:%SZ")
        IPAWS_URL="https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/$TIMESTAMP"
    fi

    cat > "$IPAWS_CONFIG" <<EOF
# IPAWS (FEMA) Alert Poller Configuration
CAP_POLLER_MODE=IPAWS

# IPAWS Production Feed
IPAWS_CAP_FEED_URLS=$IPAWS_URL

# Uncomment to enable debug logging:
# CAP_POLLER_DEBUG_RECORDS=1
EOF
    echo "✅ Created $IPAWS_CONFIG"
else
    echo "✅ $IPAWS_CONFIG already exists"
fi

echo ""
echo "Configuration files initialized!"
echo "- NOAA poller will use: $NOAA_CONFIG"
echo "- IPAWS poller will use: $IPAWS_CONFIG"
echo ""
echo "Edit these files to customize each poller's configuration."
