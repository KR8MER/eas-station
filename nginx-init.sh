#!/bin/sh
# nginx initialization script for EAS Station
# Handles SSL certificate generation and nginx configuration
# Compatible with Alpine Linux /bin/sh

set -e

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

echo "========================================="
echo "EAS Station nginx Initialization"
echo "========================================="
echo "Domain: $DOMAIN_NAME"
echo "Email: $EMAIL"
echo "Staging mode: $STAGING"
echo "========================================="

# Create necessary directories
mkdir -p /var/www/certbot
mkdir -p /etc/letsencrypt/live/$DOMAIN_NAME
mkdir -p /var/log/nginx

# Substitute environment variables in nginx config
envsubst '${DOMAIN_NAME}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# Check if we already have certificates
if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
    echo "SSL certificates already exist for $DOMAIN_NAME"
    echo "Skipping certificate generation"
else
    echo "No existing certificates found"

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

        # Generate self-signed certificate
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem \
            -out /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
            -subj "/C=US/ST=State/L=City/O=EAS Station/CN=$DOMAIN_NAME"

        # Create chain.pem (copy of fullchain for self-signed)
        cp /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
           /etc/letsencrypt/live/$DOMAIN_NAME/chain.pem

        echo "Self-signed certificate generated"
        echo "IMPORTANT: Browsers will show a security warning"
        echo "For production, use a valid domain name"
    else
        echo "Obtaining Let's Encrypt certificate for $DOMAIN_NAME"

        # Build certbot command
        CERTBOT_CMD="certbot certonly --webroot --webroot-path=/var/www/certbot"
        CERTBOT_CMD="$CERTBOT_CMD --email $EMAIL"
        CERTBOT_CMD="$CERTBOT_CMD --agree-tos"
        CERTBOT_CMD="$CERTBOT_CMD --no-eff-email"
        CERTBOT_CMD="$CERTBOT_CMD -d $DOMAIN_NAME"

        # Add staging flag if requested
        if [ "$STAGING" = "1" ]; then
            echo "Using Let's Encrypt staging server (for testing)"
            CERTBOT_CMD="$CERTBOT_CMD --staging"
        fi

        # Request certificate
        if $CERTBOT_CMD; then
            echo "Successfully obtained SSL certificate"
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
            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                -keyout /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem \
                -out /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
                -subj "/C=US/ST=State/L=City/O=EAS Station/CN=$DOMAIN_NAME"

            cp /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
               /etc/letsencrypt/live/$DOMAIN_NAME/chain.pem
        fi
    fi
fi

echo "========================================="
echo "nginx initialization complete"
echo "Starting nginx..."
echo "========================================="

# Start nginx in foreground
exec nginx -g 'daemon off;'
