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

    ALT_NAMES_CONFIG=$(build_subject_alt_name)

    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem \
        -out /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
        -subj "/C=US/ST=State/L=City/O=EAS Station/CN=$DOMAIN_NAME" \
        -addext "subjectAltName=${ALT_NAMES_CONFIG}"

    cp /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem \
       /etc/letsencrypt/live/$DOMAIN_NAME/chain.pem

    touch "$SELF_SIGNED_MARKER"
}

build_subject_alt_name() {
    ALT_NAMES="DNS:${DOMAIN_NAME}"

    for NAME in $ADDITIONAL_SERVER_NAMES; do
        ALT_NAMES="${ALT_NAMES},DNS:${NAME}"
    done

    echo "$ALT_NAMES"
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

certificate_is_trusted_and_valid() {
    CERT_PATH="${1:-/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem}"

    if [ ! -s "$CERT_PATH" ]; then
        return 1
    fi

    # Check if certificate is expired or not yet valid
    if ! openssl x509 -in "$CERT_PATH" -checkend 0 -noout >/dev/null 2>&1; then
        return 1
    fi

    # Check if certificate is self-signed (self-signed certs should be replaced)
    if is_self_signed_certificate "$CERT_PATH"; then
        return 1
    fi

    # If certificate exists, is not expired, and is not self-signed, consider it valid
    # Don't fail on openssl verify issues as they may be false positives
    return 0
}

is_staging_certificate() {
    CERT_PATH="${1:-/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem}"
    CERT_DOMAIN="${2:-}"

    if [ -z "$CERT_DOMAIN" ] && [ -n "$CERT_PATH" ]; then
        CERT_DOMAIN=$(basename "$(dirname "$CERT_PATH")")
    fi

    if [ -n "$CERT_DOMAIN" ]; then
        RENEWAL_CONFIG="/etc/letsencrypt/renewal/$CERT_DOMAIN.conf"

        if [ -f "$RENEWAL_CONFIG" ] && grep -qi "acme-staging" "$RENEWAL_CONFIG"; then
            return 0
        fi
    fi

    if [ -s "$CERT_PATH" ]; then
        ISSUER=$(openssl x509 -in "$CERT_PATH" -noout -issuer 2>/dev/null || true)

        case "$ISSUER" in
            *"Fake LE"*|*"Fake Let's Encrypt"*|*"staging"*|*"Staging"*)
                return 0
                ;;
        esac
    fi

    return 1
}

describe_certificate_issue() {
    CERT_PATH="${1:-/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem}"
    CERT_DOMAIN="${2:-$DOMAIN_NAME}"

    if [ ! -s "$CERT_PATH" ]; then
        echo "Certificate for $CERT_DOMAIN is missing or empty"
        return
    fi

    if ! openssl x509 -in "$CERT_PATH" -checkend 0 -noout >/dev/null 2>&1; then
        echo "Certificate for $CERT_DOMAIN is expired or not yet valid"
    fi

    if is_self_signed_certificate "$CERT_PATH"; then
        echo "Certificate for $CERT_DOMAIN is self-signed"
    fi

    if ! openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt "$CERT_PATH" >/dev/null 2>&1; then
        ISSUER=$(openssl x509 -in "$CERT_PATH" -noout -issuer 2>/dev/null || echo "unknown")
        echo "Certificate for $CERT_DOMAIN failed trust verification (issuer: $ISSUER)"
    fi

    if is_staging_certificate "$CERT_PATH" "$CERT_DOMAIN"; then
        echo "Certificate for $CERT_DOMAIN is issued by Let's Encrypt staging environment"
    fi
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

        # Only purge certificates that are:
        # 1. Marked as self-signed (via marker file)
        # 2. Actually self-signed (detected by certificate check)
        # 3. Expired or not yet valid
        # Don't purge certificates just because they fail trust verification
        if [ -f "$MARKER_FILE" ] || { [ "$DOMAIN_MATCH" -eq 1 ] && is_self_signed_certificate "$CERT_PATH"; } || { [ "$DOMAIN_MATCH" -eq 1 ] && [ -s "$CERT_PATH" ] && ! openssl x509 -in "$CERT_PATH" -checkend 0 -noout >/dev/null 2>&1; }; then
            describe_certificate_issue "$CERT_PATH" "$CERT_DOMAIN"
            echo "Removing stale certificate artifacts for $CERT_DOMAIN"
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
            DOMAIN_NAME|SSL_EMAIL|CERTBOT_STAGING|ADDITIONAL_SERVER_NAMES)
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
ADDITIONAL_SERVER_NAMES="${ADDITIONAL_SERVER_NAMES:-}"
SELF_SIGNED_MARKER="/etc/letsencrypt/live/$DOMAIN_NAME/.self-signed"

echo "========================================="
echo "EAS Station nginx Initialization"
echo "========================================="
echo "Domain: $DOMAIN_NAME"
if [ -n "$ADDITIONAL_SERVER_NAMES" ]; then
    echo "Additional server names: $ADDITIONAL_SERVER_NAMES"
fi
echo "Email: $EMAIL"
echo "Staging mode: $STAGING"
echo "========================================="

# Create necessary directories
mkdir -p /var/www/certbot
mkdir -p /var/log/nginx

# Ensure any stale self-signed material tied to this domain is removed before proceeding
purge_stale_self_signed_material

# Substitute environment variables in nginx config
envsubst '${DOMAIN_NAME} ${ADDITIONAL_SERVER_NAMES}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# Check if we already have certificates
CURRENT_CERT_SELF_SIGNED=1
if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
    if [ -f "$SELF_SIGNED_MARKER" ]; then
        echo "Detected previously generated self-signed certificate"
        echo "Will retry Let's Encrypt issuance for $DOMAIN_NAME"
        describe_certificate_issue "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" "$DOMAIN_NAME"
        CURRENT_CERT_SELF_SIGNED=1
    elif is_self_signed_certificate; then
        echo "Existing certificate appears to be self-signed without marker"
        echo "Cleaning up legacy fallback before reissuing"
        touch "$SELF_SIGNED_MARKER"
        describe_certificate_issue "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" "$DOMAIN_NAME"
        CURRENT_CERT_SELF_SIGNED=1
    elif certificate_is_trusted_and_valid; then
        if is_staging_certificate "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" "$DOMAIN_NAME"; then
            echo "Existing certificate was issued by Let's Encrypt staging environment"
            echo "Will request a trusted production certificate for $DOMAIN_NAME"
            describe_certificate_issue "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" "$DOMAIN_NAME"
            CURRENT_CERT_SELF_SIGNED=1
        else
            echo "SSL certificates already exist for $DOMAIN_NAME"
            echo "Skipping certificate generation"
            CURRENT_CERT_SELF_SIGNED=0
        fi
    else
        describe_certificate_issue "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" "$DOMAIN_NAME"
        echo "Existing certificate for $DOMAIN_NAME is expired or invalid"
        echo "Will request a new trusted certificate"
        CURRENT_CERT_SELF_SIGNED=1
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
            echo "Using certbot standalone mode to respond to HTTP-01 challenges on port 80"

            # Build certbot command
            CERTBOT_CMD="certbot certonly --standalone --preferred-challenges http"
            CERTBOT_CMD="$CERTBOT_CMD --http-01-port 80"
            CERTBOT_CMD="$CERTBOT_CMD --email $EMAIL"
            CERTBOT_CMD="$CERTBOT_CMD --agree-tos"
            CERTBOT_CMD="$CERTBOT_CMD --no-eff-email"
            CERTBOT_CMD="$CERTBOT_CMD -d $DOMAIN_NAME"
            CERTBOT_CMD="$CERTBOT_CMD --cert-name $DOMAIN_NAME"
            CERTBOT_CMD="$CERTBOT_CMD --non-interactive"

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
