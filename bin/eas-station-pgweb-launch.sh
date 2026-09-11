#!/usr/bin/env bash
#
# EAS Station - Emergency Alert System
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
#
# This file is part of EAS Station.
#
# EAS Station is dual-licensed software:
# - GNU Affero General Public License v3 (AGPL-3.0) for open-source use
# - Commercial License for proprietary use
#
# You should have received a copy of both licenses with this software.
# For more information, see LICENSE and LICENSE-COMMERCIAL files.
#
# IMPORTANT: This software cannot be rebranded or have attribution removed.
# See NOTICE file for complete terms.
#
# Repository: https://github.com/KR8MER/eas-station
#
# Launches pgweb (https://github.com/sosedoff/pgweb), an optional
# third-party PostgreSQL browser an operator can install for ad-hoc query
# access to the EAS Station database. See docs/guides/DATABASE_BROWSER.md.
#
# CRITICAL: --bind=127.0.0.1, never 0.0.0.0. pgweb has no authentication of
# its own -- whoever can reach its port gets full, unauthenticated
# read/write SQL access to the production database. The only supported way
# to reach it is through the authenticated nginx proxy on port 8081 (see
# the `listen 8081` server block in config/nginx-eas-station.conf and the
# /api/internal/pgweb-auth-check Flask route it calls), which requires a
# logged-in session with the system.configure permission -- the same gate
# this app's other highest-sensitivity admin actions use. --listen is
# therefore an *internal* port nginx proxies to, not the port an operator
# actually connects to.
set -euo pipefail

env_file="/opt/eas-station/.env"

get_env_val() {
    local key="$1" line val
    line=$(grep -m1 "^${key}=" "$env_file" 2>/dev/null || true)
    [ -z "$line" ] && return
    val="${line#*=}"
    if [[ "$val" == \"*\" && "$val" == *\" ]]; then
        val="${val#\"}"; val="${val%\"}"
    elif [[ "$val" == \'*\' && "$val" == *\' ]]; then
        val="${val#\'}"; val="${val%\'}"
    fi
    printf '%s' "$val"
}

url=$(get_env_val DATABASE_URL)
if [ -z "$url" ]; then
    pg_user=$(get_env_val POSTGRES_USER); pg_user="${pg_user:-postgres}"
    pg_pass=$(get_env_val POSTGRES_PASSWORD); pg_pass="${pg_pass:-postgres}"
    pg_host=$(get_env_val POSTGRES_HOST); pg_host="${pg_host:-localhost}"
    pg_port=$(get_env_val POSTGRES_PORT); pg_port="${pg_port:-5432}"
    pg_db=$(get_env_val POSTGRES_DB); pg_db="${pg_db:-alerts}"
    url="postgres://${pg_user}:${pg_pass}@${pg_host}:${pg_port}/${pg_db}"
else
    url="postgres://${url#*://}"
fi

exec /usr/local/bin/pgweb --bind=127.0.0.1 --listen=18081 --url="$url"
