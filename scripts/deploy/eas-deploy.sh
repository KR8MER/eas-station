#!/usr/bin/env bash
# EAS Station - Emergency Alert System
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
# Dual-licensed: AGPL-3.0 / Commercial. See LICENSE, LICENSE-COMMERCIAL, NOTICE.
# Repository: https://github.com/KR8MER/eas-station
#
# Deploy the current tip of origin/main to /opt/eas-station.
#
# Installed root-owned at /usr/local/sbin/eas-deploy and run by the GitHub
# Actions runner (user gh-runner) through the single sudoers rule in
# config/sudoers-gh-runner. It is NOT updated automatically from the repo:
# reinstall it by hand after reviewing changes, so a merge can never widen
# what runs as root. See docs/maintenance/PI_AUTODEPLOY.md.
#
# Usage: eas-deploy <40-char commit sha>
#   Refuses unless <sha> is exactly origin/main's tip, so the runner can
#   only ever deploy what is already merged.
set -euo pipefail

APP_DIR=/opt/eas-station
APP_USER=eas-station
TARGET=eas-station.target
HEALTH_URL=http://localhost:5000/health
LOCK=/run/eas-deploy.lock
SELF=/usr/local/sbin/eas-deploy

log() { echo "[eas-deploy] $*"; logger -t eas-deploy -- "$*" 2>/dev/null || true; }
fail() { echo "::error::$*"; logger -t eas-deploy -p user.err -- "$*" 2>/dev/null || true; exit 1; }
as_app() { sudo -u "$APP_USER" -H bash -c "cd '$APP_DIR' && $1"; }

[ "$(id -u)" -eq 0 ] || fail "must run as root"
SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "usage: eas-deploy <40-char sha>"

exec 9>"$LOCK"
flock -n 9 || fail "another deploy is running"

as_app "git fetch -q origin main"
TIP=$(as_app "git rev-parse origin/main")
[ "$SHA" = "$TIP" ] || fail "refusing: $SHA is not origin/main's tip ($TIP)"

# Never clobber hand edits in /opt -- the drift that once silently reverted
# deployed fixes.
if [ -n "$(as_app 'git status --porcelain --untracked-files=no')" ]; then
    as_app "git status --short --untracked-files=no"
    fail "/opt/eas-station has local modifications; resolve them before auto-deploy"
fi

PREV=$(as_app "git rev-parse HEAD")
if [ "$PREV" = "$SHA" ]; then
    log "already at $SHA; nothing to deploy"
    exit 0
fi

# Changes outside these paths need a restart; docs/tests/CI-only merges don't.
RUNTIME_CHANGED=$(as_app "git diff --name-only $PREV $SHA -- . ':!docs' ':!tests' ':!.github' ':!*.md' ':!VERSION'" | head -1)
REQS_CHANGED=$(as_app "git diff --name-only $PREV $SHA -- requirements.txt requirements-sdr.txt" | head -1)
UNITS_CHANGED=$(as_app "git diff --name-only $PREV $SHA -- systemd" | head -1)

wait_for_air() {
    # Don't restart audio mid-alert: wait up to 10 minutes for the
    # broadcast marker (app_utils/eas/indicators.py) to clear.
    for _ in $(seq 1 60); do
        [ "$(redis-cli EXISTS eas:broadcast_active 2>/dev/null || echo 0)" = "0" ] && return 0
        log "alert on air; waiting before restart"
        sleep 10
    done
    fail "alert still on air after 10 minutes; not restarting"
}

install_reqs() {
    as_app "venv/bin/pip install -q -r requirements.txt"
    if [ -x "$APP_DIR/venv-sdr/bin/pip" ]; then
        as_app "venv-sdr/bin/pip install -q -r requirements-sdr.txt"
    fi
}

UNHEALTHY=""
healthy() {
    local code=""
    for _ in $(seq 1 24); do
        sleep 5
        UNHEALTHY=$(systemctl list-dependencies "$TARGET" --plain --no-pager |
                    grep -oE 'eas-station[^ ]*\.service' |
                    while read -r unit; do systemctl is-active --quiet "$unit" || echo "$unit"; done)
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" || true)
        if [ -z "$UNHEALTHY" ] && [ "$code" = "200" ]; then
            return 0
        fi
    done
    log "unhealthy after 2 minutes: inactive=[${UNHEALTHY//$'\n'/ }] health=$code"
    return 1
}

log "deploying $PREV -> $SHA"
as_app "git reset -q --hard $SHA"
if [ -z "$RUNTIME_CHANGED" ]; then
    log "docs/tests/CI-only change; checkout updated, no restart needed"
    exit 0
fi
if [ -n "$REQS_CHANGED" ]; then
    log "requirements changed; installing"
    install_reqs
fi
if [ -n "$UNITS_CHANGED" ]; then
    echo "::warning::systemd unit files changed; run update.sh to install them"
fi
log "running migrations"
as_app "venv/bin/alembic upgrade head" >/dev/null
wait_for_air
systemctl restart "$TARGET"

if healthy; then
    log "deployed $SHA; all services healthy"
    if ! cmp -s "$APP_DIR/scripts/deploy/eas-deploy.sh" "$SELF"; then
        echo "::warning::scripts/deploy/eas-deploy.sh differs from the installed $SELF; review it and reinstall (docs/maintenance/PI_AUTODEPLOY.md)"
    fi
    exit 0
fi

log "health check failed; rolling back to $PREV (schema migrations are not reverted)"
as_app "git reset -q --hard $PREV"
if [ -n "$REQS_CHANGED" ]; then
    install_reqs
fi
systemctl restart "$TARGET"
if healthy; then
    fail "deploy of $SHA failed health checks; rolled back to $PREV"
fi
fail "deploy of $SHA failed AND rollback to $PREV is unhealthy; needs a person"
