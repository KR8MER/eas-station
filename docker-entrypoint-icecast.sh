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

# Function to parse .env file safely without using 'source'
# This handles .env files with special characters, quotes, and edge cases
parse_env_file() {
    local env_file="$1"
    local loaded_count=0
    
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        
        # Extract key=value, keeping the full value intact
        if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local value="${BASH_REMATCH[2]}"
            
            # Remove only leading whitespace from value (preserve trailing)
            value="${value#"${value%%[![:space:]]*}"}"
            
            # Remove surrounding quotes if present (simple case only)
            # Handles: "value" or 'value' but not escaped quotes
            if [[ ${#value} -ge 2 ]]; then
                local first="${value:0:1}"
                local last="${value: -1}"
                if [[ "$first" == '"' && "$last" == '"' ]] || [[ "$first" == "'" && "$last" == "'" ]]; then
                    value="${value:1:${#value}-2}"
                fi
            fi
            
            # Only export Icecast-related variables (security: don't override unrelated vars)
            if [[ "$key" == ICECAST_* ]]; then
                export "$key=$value"
                echo "  ✓ Loaded: $key"
                ((loaded_count++))
            fi
        fi
    done < "$env_file"
    
    # Return success if we loaded at least one variable
    [[ $loaded_count -gt 0 ]]
}

# Load configuration from persistent .env file if it exists
# This ensures Icecast uses the same passwords as the app container
if [ -f "$ENV_FILE" ]; then
    echo "INFO: Loading Icecast configuration from persistent .env"
    if parse_env_file "$ENV_FILE"; then
        echo "INFO: ✓ Configuration loaded from persistent storage"
    else
        echo "WARNING: Failed to parse .env file, using docker-compose environment variables"
    fi
else
    echo "INFO: No persistent .env file found, using docker-compose environment variables (initial setup)"
fi

# Function to update XML config values (handles multiline and whitespace)
update_config() {
    local tag=$1
    local value=$2
    if [ -n "$value" ]; then
        # Use perl for better multiline regex support
        # This handles: <tag>value</tag>, <tag> value </tag>, and multiline variants
        perl -i -0777 -pe "s|<${tag}>.*?</${tag}>|<${tag}>${value}</${tag}>|gs" "$CONFIG_FILE" 2>/dev/null || true
    fi
}

echo "Configuring Icecast..."

# Update passwords
update_config "source-password" "${ICECAST_SOURCE_PASSWORD:-hackme}"
update_config "relay-password" "${ICECAST_RELAY_PASSWORD:-hackme}"
update_config "admin-password" "${ICECAST_ADMIN_PASSWORD:-hackme}"

# CRITICAL: Restore file ownership after perl modifications
chown icecast2:icecast "$CONFIG_FILE" 2>/dev/null || true
chmod 644 "$CONFIG_FILE" 2>/dev/null || true

# Update server settings
# Use ICECAST_HOSTNAME if explicitly set, otherwise fallback to ICECAST_PUBLIC_HOSTNAME,
# and finally default to localhost for local-only access
EFFECTIVE_HOSTNAME="${ICECAST_HOSTNAME:-${ICECAST_PUBLIC_HOSTNAME:-localhost}}"
update_config "hostname" "$EFFECTIVE_HOSTNAME"
echo "INFO: Configured hostname: $EFFECTIVE_HOSTNAME"
update_config "location" "${ICECAST_LOCATION:-Earth}"
update_config "admin" "${ICECAST_ADMIN:-icemaster@localhost}"

# Update limits
update_config "clients" "${ICECAST_MAX_CLIENTS:-100}"
update_config "sources" "${ICECAST_MAX_SOURCES:-2}"

# CRITICAL: Disable source timeout to prevent 10-minute disconnects
# Default source-timeout is 10 seconds, but we need infinite for persistent streams
# Setting to -1 (infinite) or very large value prevents automatic disconnection
update_config "source-timeout" "0"  # 0 = infinite timeout

# Enable changeowner for security (allows Icecast to drop root privileges)
update_config "changeowner" "true"

# Set logging level (3 = INFO, 4 = DEBUG)
update_config "loglevel" "3"

# CRITICAL: Restore file ownership one final time after ALL updates
chown icecast2:icecast "$CONFIG_FILE" 2>/dev/null || true
chmod 644 "$CONFIG_FILE" 2>/dev/null || true

echo "✓ Icecast configuration complete. Starting server..."

# Drop privileges and execute icecast as icecast2 user
exec gosu icecast2 "$@"
