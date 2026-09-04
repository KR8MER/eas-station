#!/usr/bin/env bash
# Refreshes /etc/nginx/bad-actors-auto.conf from Spamhaus DROP + EDROP --
# professionally-curated lists of hijacked and cybercrime-controlled
# netblocks, deliberately kept small and high-confidence (unlike Spamhaus's
# spam-scoring lists), so it's safe to hard-block rather than just flag.
#
# Run daily by bad-actors-update.timer (see systemd/). Safe to run by hand.
# Reloads nginx only after the new list passes `nginx -t`, so a bad fetch or
# a syntax problem never takes the site down.
set -euo pipefail

OUT=/etc/nginx/bad-actors-auto.conf
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
    echo "# Auto-generated $(date -u +%FT%TZ) by update_bad_actors.sh from Spamhaus DROP/EDROP."
    echo "# Do not edit by hand -- edit config/bad-actors-local.conf instead, it is not overwritten."
    # `|| true` per URL: a single source returning zero matching lines (e.g.
    # Spamhaus has since folded EDROP into DROP, leaving edrop.txt an empty
    # stub) must not abort the whole run under pipefail. The aggregate count
    # check below is what actually guards against a real fetch failure.
    for url in https://www.spamhaus.org/drop/drop.txt https://www.spamhaus.org/drop/edrop.txt; do
        curl -fsS --max-time 15 "$url" \
            | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+' \
            | awk '{print $1, "1;"}' \
            || true
    done
} > "$TMP"

count=$(grep -cE '^[0-9]' "$TMP" || true)
if [ "$count" -lt 100 ]; then
    echo "update_bad_actors: only $count entries fetched (expected hundreds+) -- refusing to replace the list, likely a fetch failure" >&2
    exit 1
fi

install -m 644 "$TMP" "$OUT"

if nginx -t 2>/tmp/bad-actors-nginx-test.log; then
    systemctl reload nginx
    echo "update_bad_actors: applied $count entries"
else
    echo "update_bad_actors: nginx -t failed after updating the list, see /tmp/bad-actors-nginx-test.log -- leaving nginx running on the previous config" >&2
    exit 1
fi
