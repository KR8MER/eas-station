#!/bin/sh
# nginx initialization script for EAS Station
# Handles SSL certificate generation and nginx configuration
# Compatible with Alpine Linux /bin/sh

set -e

purge_certificate_material() {
    TARGET_DOMAIN="${1:-$DOMAIN_NAME}"

    if command -v certbot >/dev/null 2>&1; then
        certbot delete --cert-name "$TARGET_DOMAIN" --non-interactive --quiet >/dev/null 2>&1 || true
    fi

    rm -rf "/etc/letsencrypt/live/$TARGET_DOMAIN"
    rm -rf "/etc/letsencrypt/archive/$TARGET_DOMAIN"
    rm -f "/etc/letsencrypt/renewal/$TARGET_DOMAIN.conf"

    if [ "$TARGET_DOMAIN" = "$DOMAIN_NAME" ]; then
        mkdir -p "/etc/letsencrypt/live/$TARGET_DOMAIN"
    fi
}

generate_self_signed_certificate() {
    mkdir -p "/etc/letsencrypt/live/$DOMAIN_NAME"

    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem \
        -out /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
        -subj "/C=US/ST=State/L=City/O=EAS Station/CN=$DOMAIN_NAME"

    cp /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
       /etc/letsencrypt/live/$DOMAIN_NAME/chain.pem

    touch "$SELF_SIGNED_MARKER"
}

is_self_signed_certificate() {
    CERT_PATH="${1:-/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem}"

    if [ ! -s "$CERT_PATH" ]; then
        return 1
    fi

    SUBJECT=$(openssl x509 -in "$CERT_PATH" -noout -subject 2>/dev/null || true)
    ISSUER=$(openssl x509 -in "$CERT_PATH" -noout -issuer 2>/dev/null || true)

    if [ -z "$SUBJECT" ] || [ -z "$ISSUER" ]; then
        return 1
    fi

    if [ "$SUBJECT" = "$ISSUER" ]; then
        return 0
    fi

    return 1
}

purge_stale_self_signed_material() {
    BASE_PATH="/etc/letsencrypt/live"

    if [ ! -d "$BASE_PATH" ]; then
        return
    fi

    for CERT_DIR in "$BASE_PATH"/*; do
        [ -d "$CERT_DIR" ] || continue

        CERT_DOMAIN=$(basename "$CERT_DIR")
        MARKER_FILE="$CERT_DIR/.self-signed"
        CERT_PATH="$CERT_DIR/fullchain.pem"

        case "$CERT_DOMAIN" in
            "$DOMAIN_NAME"|"$DOMAIN_NAME"-[0-9]*)
                DOMAIN_MATCH=1
                ;;
            *)
                DOMAIN_MATCH=0
                ;;
        esac

        if [ -f "$MARKER_FILE" ] || { [ "$DOMAIN_MATCH" -eq 1 ] && is_self_signed_certificate "$CERT_PATH"; }; then
            echo "Removing stale self-signed certificate artifacts for $CERT_DOMAIN"
            purge_certificate_material "$CERT_DOMAIN"
        fi
    done
}

# Source persistent configuration from setup wizard if it exists
# This allows HTTPS settings to be configured through the web UI
if [ -f "/app-config/.env" ]; then
    echo "Loading persistent configuration from /app-config/.env"
    # Export variables from .env file (only HTTPS-related ones)
    # Use a safer approach that works with busybox sh
    while IFS='=' read -r key value; do
        case "$key" in
            DOMAIN_NAME|SSL_EMAIL|CERTBOT_STAGING)
                export "$key=$value"
                echo "Loaded $key from persistent config"
                ;;
        esac
    done < /app-config/.env
fi

# Set defaults from environment variables (or use hardcoded defaults as fallback)
DOMAIN_NAME="${DOMAIN_NAME:-localhost}"
EMAIL="${SSL_EMAIL:-admin@example.com}"
STAGING="${CERTBOT_STAGING:-0}"
SELF_SIGNED_MARKER="/etc/letsencrypt/live/$DOMAIN_NAME/.self-signed"

echo "========================================="
echo "EAS Station nginx Initialization"
echo "========================================="
echo "Domain: $DOMAIN_NAME"
echo "Email: $EMAIL"
echo "Staging mode: $STAGING"
echo "========================================="

# Create necessary directories
mkdir -p /var/www/certbot
mkdir -p /var/log/nginx

# Ensure any stale self-signed material tied to this domain is removed before proceeding
purge_stale_self_signed_material

# Substitute environment variables in nginx config
envsubst '${DOMAIN_NAME}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# Check if we already have certificates
CURRENT_CERT_SELF_SIGNED=1
if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
    if [ -f "$SELF_SIGNED_MARKER" ]; then
        echo "Detected previously generated self-signed certificate"
        echo "Will retry Let's Encrypt issuance for $DOMAIN_NAME"
        CURRENT_CERT_SELF_SIGNED=1
    elif is_self_signed_certificate; then
        echo "Existing certificate appears to be self-signed without marker"
        echo "Cleaning up legacy fallback before reissuing"
        touch "$SELF_SIGNED_MARKER"
        CURRENT_CERT_SELF_SIGNED=1
    else
        echo "SSL certificates already exist for $DOMAIN_NAME"
        echo "Skipping certificate generation"
        CURRENT_CERT_SELF_SIGNED=0
    fi
else
    CURRENT_CERT_SELF_SIGNED=1
fi

if [ "$CURRENT_CERT_SELF_SIGNED" -ne 0 ]; then
    echo "Purging existing certificate material for $DOMAIN_NAME"
    purge_certificate_material

    echo "No valid certificates found for $DOMAIN_NAME"

    # Check if domain is localhost or an IP address
    if [ "$DOMAIN_NAME" = "localhost" ]; then
        LOCAL_CERT_ONLY=1
    elif echo "$DOMAIN_NAME" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        LOCAL_CERT_ONLY=1
    else
        LOCAL_CERT_ONLY=0
    fi

    if [ "$LOCAL_CERT_ONLY" -eq 1 ]; then
        echo "========================================="
        echo "WARNING: Cannot obtain Let's Encrypt certificates for localhost or IP addresses"
        echo "Generating self-signed certificate for development/testing"
        echo "========================================="

        generate_self_signed_certificate

        echo "Self-signed certificate generated"
        echo "IMPORTANT: Browsers will show a security warning"
        echo "For production, use a valid domain name"
    else
        if ! command -v certbot >/dev/null 2>&1; then
            echo "========================================="
            echo "ERROR: certbot command is not available"
            echo "========================================="
            echo "Falling back to self-signed certificate"
            echo "========================================="

            generate_self_signed_certificate
        else
            echo "Obtaining Let's Encrypt certificate for $DOMAIN_NAME"

            # Build certbot command
            CERTBOT_CMD="certbot certonly --webroot --webroot-path=/var/www/certbot"
            CERTBOT_CMD="$CERTBOT_CMD --email $EMAIL"
            CERTBOT_CMD="$CERTBOT_CMD --agree-tos"
            CERTBOT_CMD="$CERTBOT_CMD --no-eff-email"
            CERTBOT_CMD="$CERTBOT_CMD -d $DOMAIN_NAME"
            CERTBOT_CMD="$CERTBOT_CMD --cert-name $DOMAIN_NAME"
            CERTBOT_CMD="$CERTBOT_CMD --non-interactive"
            CERTBOT_CMD="$CERTBOT_CMD --force-renewal"

            # Add staging flag if requested
            if [ "$STAGING" = "1" ]; then
                echo "Using Let's Encrypt staging server (for testing)"
                CERTBOT_CMD="$CERTBOT_CMD --staging"
            fi

            # Request certificate
            if $CERTBOT_CMD; then
                echo "Successfully obtained SSL certificate"
                rm -f "$SELF_SIGNED_MARKER"
            else
                echo "========================================="
                echo "ERROR: Failed to obtain SSL certificate"
                echo "========================================="
                echo "Possible reasons:"
                echo "1. Domain $DOMAIN_NAME is not pointing to this server"
                echo "2. Port 80 is not accessible from the internet"
                echo "3. Firewall is blocking Let's Encrypt validation"
                echo ""
                echo "Falling back to self-signed certificate"
                echo "========================================="

                # Generate self-signed certificate as fallback
                generate_self_signed_certificate
            fi
        fi
    fi
fi

echo "========================================="
echo "nginx initialization complete"
echo "Starting nginx..."
echo "========================================="

# Start nginx in foreground
exec nginx -g 'daemon off;'
