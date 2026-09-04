"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

from __future__ import annotations

"""Edge Defense analytics: stats for requests nginx rejected before the app
ever saw them.

Three of EAS Station's protections happen entirely inside nginx --
scanner-bait path rejection, the Spamhaus/local bad-actor IP blocklist, and
per-IP rate limiting (see config/nginx-eas-station.conf) -- so none of them
show up in WebRequestLog (web_traffic.py), which only ever sees requests
Flask actually handled. This module gives that layer its own, much smaller
event log, fed by tailing the nginx access log rather than in-process
recording (there is no in-process hook to record from: the app never runs).

scripts/ingest_security_perimeter_log.py (run every 2 minutes via
security-perimeter-ingest.timer) calls ingest_new_events() to do the actual
tailing; this module also holds the query helpers the "Edge Defense" tab on
the Security Center page (webapp/admin/security_blocks.py) uses to render
them.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app_core.extensions import db
from app_utils import utc_now

LOG_PATH = "/var/log/nginx/eas-station-access.log"

# Matches log_format eas_station_combined in config/nginx-eas-station.conf:
#   $remote_addr - $remote_user [$time_local] "$request" $status
#   $body_bytes_sent "$http_referer" "$http_user_agent" "$security_block_reason"
_LOG_LINE_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Za-z]+) (?P<path>\S+)(?: \S+)?" '
    r'(?P<status>\d{3}) \S+ '
    r'"[^"]*" "(?P<ua>[^"]*)" "(?P<reason>[^"]*)"\s*$'
)
_TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"

BLOCK_REASON_LABELS = {
    "scanner_bait": "Scanner Bait",
    "bad_actor_blocklist": "Bad Actor Blocklist",
    "rate_limited": "Rate Limited",
    "other_444": "Other (444)",
}


class SecurityPerimeterEvent(db.Model):
    """A single request nginx rejected before it reached the application.

    block_reason is one of BLOCK_REASON_LABELS' keys, derived by
    _classify() from the response status plus (for a 444) the
    $security_block_reason field nginx tagged the line with.
    """

    __tablename__ = "security_perimeter_events"

    id = db.Column(db.Integer, primary_key=True)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    ip_address = db.Column(db.String(64), nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=False, index=True)
    block_reason = db.Column(db.String(32), nullable=False, index=True)
    method = db.Column(db.String(8), nullable=True)
    path = db.Column(db.String(512), nullable=True, index=True)
    user_agent = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "ip_address": self.ip_address,
            "status_code": self.status_code,
            "block_reason": self.block_reason,
            "block_reason_label": BLOCK_REASON_LABELS.get(self.block_reason, self.block_reason),
            "method": self.method,
            "path": self.path,
            "user_agent": self.user_agent,
        }


class SecurityPerimeterIngestState(db.Model):
    """Single-row (id=1) checkpoint: how far into LOG_PATH we've read.

    Keyed by inode rather than just byte offset so a logrotate rotation
    (rename + fresh file, not copytruncate) is detected and read from the
    top instead of seeking past the new, much-shorter file.
    """

    __tablename__ = "security_perimeter_ingest_state"

    id = db.Column(db.Integer, primary_key=True)
    log_inode = db.Column(db.BigInteger, nullable=False, default=0)
    log_offset = db.Column(db.BigInteger, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


def _classify(status: int, reason: str) -> Optional[str]:
    """Map a log line's (status, $security_block_reason) to a block_reason,
    or None if this line isn't a perimeter-defense event at all (the
    overwhelming majority of lines -- ordinary 200s, 404s, etc.)."""
    if status == 429:
        return "rate_limited"
    if status == 444:
        return reason if reason in BLOCK_REASON_LABELS else "other_444"
    return None


def _parse_line(line: str):
    match = _LOG_LINE_RE.match(line)
    if not match:
        return None
    try:
        status = int(match.group("status"))
    except ValueError:
        return None

    reason = _classify(status, match.group("reason"))
    if reason is None:
        return None

    try:
        occurred_at = datetime.strptime(match.group("time"), _TIME_FMT)
    except ValueError:
        occurred_at = utc_now()

    return SecurityPerimeterEvent(
        occurred_at=occurred_at,
        ip_address=match.group("ip"),
        status_code=status,
        block_reason=reason,
        method=match.group("method")[:8],
        path=match.group("path")[:512],
        user_agent=(match.group("ua") or "")[:512],
    )


def ingest_new_events(log_path: str = LOG_PATH, batch_size: int = 2000) -> int:
    """Tail *log_path* from the last checkpoint, insert any new perimeter-
    defense events, and advance the checkpoint. Returns the number inserted.

    Safe to call repeatedly and concurrently-adjacent (each run picks up
    exactly where the last one's checkpoint left off); a still-being-written
    partial final line is left for the next run rather than guessed at.
    """
    state = SecurityPerimeterIngestState.query.get(1)
    if not state:
        state = SecurityPerimeterIngestState(id=1, log_inode=0, log_offset=0)
        db.session.add(state)
        db.session.commit()

    try:
        file_stat = os.stat(log_path)
    except FileNotFoundError:
        return 0

    offset = state.log_offset
    if file_stat.st_ino != state.log_inode:
        # First run, or the file was rotated (rename + fresh file) since we
        # last checked -- read the new file from the top.
        offset = 0

    inserted = 0
    batch: List[SecurityPerimeterEvent] = []
    checkpoint = offset
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        while True:
            pos = f.tell()
            line = f.readline()
            if not line:
                break
            if not line.endswith("\n"):
                break  # partial line still being written; retry next run
            checkpoint = f.tell()
            event = _parse_line(line)
            if event is not None:
                batch.append(event)
                inserted += 1
            if len(batch) >= batch_size:
                db.session.bulk_save_objects(batch)
                db.session.commit()
                batch = []

    if batch:
        db.session.bulk_save_objects(batch)

    state.log_inode = file_stat.st_ino
    state.log_offset = checkpoint
    db.session.commit()
    return inserted


def summary_counts(hours: int = 24) -> Dict[str, int]:
    since = utc_now() - timedelta(hours=hours)
    rows = (
        db.session.query(SecurityPerimeterEvent.block_reason, db.func.count(SecurityPerimeterEvent.id))
        .filter(SecurityPerimeterEvent.occurred_at >= since)
        .group_by(SecurityPerimeterEvent.block_reason)
        .all()
    )
    counts = {key: 0 for key in BLOCK_REASON_LABELS}
    total = 0
    for reason, count in rows:
        counts[reason] = count
        total += count
    counts["total"] = total
    return counts


def top_ips(hours: int = 24, limit: int = 10) -> List[Dict]:
    since = utc_now() - timedelta(hours=hours)
    rows = (
        db.session.query(SecurityPerimeterEvent.ip_address, db.func.count(SecurityPerimeterEvent.id))
        .filter(SecurityPerimeterEvent.occurred_at >= since)
        .group_by(SecurityPerimeterEvent.ip_address)
        .order_by(db.func.count(SecurityPerimeterEvent.id).desc())
        .limit(limit)
        .all()
    )
    return [{"ip_address": ip, "count": count} for ip, count in rows]


def top_paths(hours: int = 24, limit: int = 10) -> List[Dict]:
    since = utc_now() - timedelta(hours=hours)
    rows = (
        db.session.query(SecurityPerimeterEvent.path, db.func.count(SecurityPerimeterEvent.id))
        .filter(SecurityPerimeterEvent.occurred_at >= since)
        .group_by(SecurityPerimeterEvent.path)
        .order_by(db.func.count(SecurityPerimeterEvent.id).desc())
        .limit(limit)
        .all()
    )
    return [{"path": path, "count": count} for path, count in rows]


def recent_events(limit: int = 50) -> List[Dict]:
    rows = (
        SecurityPerimeterEvent.query.order_by(SecurityPerimeterEvent.occurred_at.desc()).limit(limit).all()
    )
    return [r.to_dict() for r in rows]
