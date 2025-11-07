#!/bin/bash
set -e

CONFIG_FILE="/etc/icecast2/icecast.xml"

# Function to update XML config values
update_config() {
    local tag=$1
    local value=$2
    if [ -n "$value" ]; then
        sed -i "s|<${tag}>[^<]*</${tag}>|<${tag}>${value}</${tag}>|g" "$CONFIG_FILE"
    fi
}

echo "Configuring Icecast from environment variables..."

# Update passwords
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

echo "Icecast configuration complete. Starting server..."

# Execute the command
exec "$@"
