#!/bin/bash
# EAS Station PostgreSQL Tuning Script
# Copyright (c) 2025 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License
#
# Applies cluster-wide PostgreSQL safety settings that are easy to lose track
# of because they live in server config rather than the application schema.
#
# idle_in_transaction_session_timeout: without this, a stuck or misbehaving
# app session that opens a transaction and never commits/closes it can pin
# the vacuum cleanup horizon indefinitely, preventing autovacuum from
# reclaiming dead tuples on any table until the session is killed manually.
# Safe to re-run; only changes the setting when it differs from the target.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}ℹ️  [INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}✓  [SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  [WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}✗  [ERROR]${NC} $1"
}

if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root or with sudo"
    exit 1
fi

IDLE_IN_TRANSACTION_TIMEOUT="${EAS_IDLE_IN_TRANSACTION_TIMEOUT:-5min}"

if ! command -v psql >/dev/null 2>&1 && ! sudo -u postgres psql --version >/dev/null 2>&1; then
    echo_warning "psql not available - skipping PostgreSQL tuning"
    exit 0
fi

echo_info "Checking idle_in_transaction_session_timeout..."
CURRENT_VALUE=$(sudo -u postgres psql -tAc \
    "SELECT setting FROM pg_settings WHERE name = 'idle_in_transaction_session_timeout'" 2>/dev/null || echo "")

if [ -z "$CURRENT_VALUE" ]; then
    echo_warning "Could not read current PostgreSQL settings - skipping"
    exit 0
fi

if [ "$CURRENT_VALUE" = "0" ]; then
    echo_info "idle_in_transaction_session_timeout is currently unlimited (0) - applying safety net of $IDLE_IN_TRANSACTION_TIMEOUT"
    sudo -u postgres psql -c "ALTER SYSTEM SET idle_in_transaction_session_timeout = '${IDLE_IN_TRANSACTION_TIMEOUT}';" >/dev/null
    sudo -u postgres psql -c "SELECT pg_reload_conf();" >/dev/null
    echo_success "idle_in_transaction_session_timeout set to $IDLE_IN_TRANSACTION_TIMEOUT (no restart required)"
else
    echo_info "idle_in_transaction_session_timeout already configured (current setting: ${CURRENT_VALUE}ms) - leaving as-is"
fi
