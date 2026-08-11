#!/bin/bash
# Invoked via OnFailure= when a critical EAS Station service enters the
# 'failed' state. This exists because Restart=always does not re-trigger
# when a unit dies while systemd already has a stop job in flight for it
# (e.g. a crash during shutdown mid-way through a full-stack restart) -
# that case leaves the unit down with no automatic recovery and no loud
# signal, since the crash itself typically produces no ERROR-level
# application log. This makes the failure visible and attempts one
# recovery restart.
set -euo pipefail

UNIT="${1:?usage: service_failure_recovery.sh <unit-name-without-.service>}.service"

logger -t eas-station-recovery -p daemon.crit \
    "${UNIT} entered failed state (result=$(systemctl show -p Result --value "${UNIT}" 2>/dev/null || echo unknown)); attempting recovery"

sleep 2

if systemctl is-active --quiet "${UNIT}"; then
    logger -t eas-station-recovery -p daemon.info "${UNIT} is already active again, no action needed"
    exit 0
fi

if systemctl start "${UNIT}"; then
    logger -t eas-station-recovery -p daemon.info "${UNIT} recovery restart succeeded"
else
    logger -t eas-station-recovery -p daemon.crit "${UNIT} recovery restart FAILED - manual intervention required"
fi
