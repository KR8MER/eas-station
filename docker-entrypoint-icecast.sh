#!/bin/bash
set -e

CONFIG_FILE="/etc/icecast2/icecast.xml"

# Function to update XML config values (handles multiline and whitespace)
update_config() {
    local tag=$1
    local value=$2
    if [ -n "$value" ]; then
        # Use perl for better multiline regex support
        # This handles: <tag>value</tag>, <tag> value </tag>, and multiline variants
        perl -i -0777 -pe "s|<${tag}>.*?</${tag}>|<${tag}>${value}</${tag}>|gs" "$CONFIG_FILE"
    fi
}

echo "Configuring Icecast from environment variables..."

# Check if perl is available
if ! command -v perl &> /dev/null; then
    echo "ERROR: perl not found! Cannot update Icecast config. Please rebuild the Icecast image:"
    echo "  docker-compose build icecast"
    echo "Falling back to default passwords (this will cause 403 errors!)"
else
    echo "perl found, updating configuration..."
fi

# Update passwords
echo "Setting source-password to: ${ICECAST_SOURCE_PASSWORD:-hackme}"
update_config "source-password" "${ICECAST_SOURCE_PASSWORD:-hackme}"
update_config "relay-password" "${ICECAST_RELAY_PASSWORD:-hackme}"
update_config "admin-password" "${ICECAST_ADMIN_PASSWORD:-hackme}"

# Update server settings
update_config "hostname" "${ICECAST_HOSTNAME:-localhost}"
update_config "location" "${ICECAST_LOCATION:-Earth}"
update_config "admin" "${ICECAST_ADMIN:-icemaster@localhost}"

# Update limits
update_config "clients" "${ICECAST_MAX_CLIENTS:-100}"
update_config "sources" "${ICECAST_MAX_SOURCES:-2}"

# Enable changeowner for security (allows Icecast to drop root privileges)
update_config "changeowner" "true"

# Verify password was updated
echo "Verifying Icecast configuration..."
if grep -q "<source-password>${ICECAST_SOURCE_PASSWORD:-hackme}</source-password>" "$CONFIG_FILE"; then
    echo "✓ source-password correctly set to: ${ICECAST_SOURCE_PASSWORD:-hackme}"
else
    echo "✗ WARNING: source-password may not have been updated correctly!"
    echo "  Current value in config:"
    grep "source-password" "$CONFIG_FILE" | head -1
fi

echo "Icecast configuration complete. Starting server..."

# Drop privileges and execute icecast as icecast2 user
exec gosu icecast2 "$@"
