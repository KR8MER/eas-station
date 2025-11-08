#!/bin/bash
set -e

CONFIG_FILE="/etc/icecast2/icecast.xml"
ENV_FILE="/app-config/.env"

# Check if perl is installed (CRITICAL for config updates)
if ! command -v perl &> /dev/null; then
    echo "ERROR: perl is not installed! Cannot update Icecast configuration!"
    echo "ERROR: This means the Docker image is outdated."
    echo "ERROR: Please rebuild the image with: docker-compose build icecast"
    exit 1
fi

echo "DEBUG: perl is available at: $(which perl)"

# Load configuration from persistent .env file if it exists
# This ensures Icecast uses the same passwords as the app container
if [ -f "$ENV_FILE" ]; then
    echo "=========================================="
    echo "INFO: Loading Icecast configuration from persistent .env file: $ENV_FILE"
    echo "INFO: This is the single source of truth for all passwords"
    echo "=========================================="
    # Source the .env file to load variables
    # Use export to make them available to this script
    set -a  # automatically export all variables
    source "$ENV_FILE"
    set +a
    echo "INFO: ✓ Configuration loaded from persistent storage"
else
    echo "=========================================="
    echo "INFO: No persistent .env file found at $ENV_FILE"
    echo "INFO: Using environment variables from docker-compose (initial setup)"
    echo "=========================================="
fi

# Function to update XML config values (handles multiline and whitespace)
update_config() {
    local tag=$1
    local value=$2
    if [ -n "$value" ]; then
        echo "DEBUG: Updating <${tag}> with value: ${value}"
        # Use perl for better multiline regex support
        # This handles: <tag>value</tag>, <tag> value </tag>, and multiline variants
        perl -i -0777 -pe "s|<${tag}>.*?</${tag}>|<${tag}>${value}</${tag}>|gs" "$CONFIG_FILE"

        # Verify the update worked
        local actual_value=$(perl -0777 -ne "print \$1 if /<${tag}>(.*?)<\/${tag}>/s" "$CONFIG_FILE")
        echo "DEBUG: Actual value in XML after update: ${actual_value}"
    fi
}

echo "Configuring Icecast from environment variables..."
echo "DEBUG: ICECAST_SOURCE_PASSWORD environment variable is: ${ICECAST_SOURCE_PASSWORD:-<not set, will use 'hackme'>}"
echo "DEBUG: ICECAST_ADMIN_PASSWORD environment variable is: ${ICECAST_ADMIN_PASSWORD:-<not set, will use 'hackme'>}"

# Show authentication section BEFORE updates
echo "DEBUG: Authentication section BEFORE updates:"
grep -A5 "<authentication>" "$CONFIG_FILE" || echo "Could not extract authentication section"

# Update passwords
update_config "source-password" "${ICECAST_SOURCE_PASSWORD:-hackme}"
update_config "relay-password" "${ICECAST_RELAY_PASSWORD:-hackme}"
update_config "admin-password" "${ICECAST_ADMIN_PASSWORD:-hackme}"

# Show authentication section AFTER updates
echo "DEBUG: Authentication section AFTER updates:"
grep -A5 "<authentication>" "$CONFIG_FILE" || echo "Could not extract authentication section"

# CRITICAL: Restore file ownership after perl modifications
# perl -i creates a new file that might be owned by root
echo "DEBUG: Restoring config file ownership to icecast2:icecast"
chown icecast2:icecast "$CONFIG_FILE"
chmod 644 "$CONFIG_FILE"
ls -la "$CONFIG_FILE"

# Update server settings
update_config "hostname" "${ICECAST_HOSTNAME:-localhost}"
update_config "location" "${ICECAST_LOCATION:-Earth}"
update_config "admin" "${ICECAST_ADMIN:-icemaster@localhost}"

# Update limits
update_config "clients" "${ICECAST_MAX_CLIENTS:-100}"
update_config "sources" "${ICECAST_MAX_SOURCES:-2}"

# Enable changeowner for security (allows Icecast to drop root privileges)
update_config "changeowner" "true"

# Set logging to maximum verbosity for debugging
update_config "loglevel" "4"  # 4 = DEBUG level (most verbose)

# CRITICAL: Restore file ownership one final time after ALL updates
echo "DEBUG: Final ownership restoration"
chown icecast2:icecast "$CONFIG_FILE"
chmod 644 "$CONFIG_FILE"

# Verify password was updated
echo "Verifying Icecast configuration..."
if grep -q "<source-password>${ICECAST_SOURCE_PASSWORD:-hackme}</source-password>" "$CONFIG_FILE"; then
    echo "✓ source-password correctly set to: ${ICECAST_SOURCE_PASSWORD:-hackme}"
else
    echo "✗ WARNING: source-password may not have been updated correctly!"
    echo "  Current value in config:"
    grep "source-password" "$CONFIG_FILE" | head -1
fi

# Final dump of complete authentication block
echo "DEBUG: ========== FINAL AUTHENTICATION BLOCK =========="
grep -A10 "<authentication>" "$CONFIG_FILE" | head -15
echo "DEBUG: ================================================"

# Show final file permissions
echo "DEBUG: Final config file permissions:"
ls -la "$CONFIG_FILE"

echo "Icecast configuration complete. Starting server..."

# Drop privileges and execute icecast as icecast2 user
exec gosu icecast2 "$@"
