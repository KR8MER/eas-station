#!/usr/bin/env python3
"""Utility script for manually importing NOAA alerts into the database."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import Optional

from app import (
    app,
    db,
    logger,
    CAPAlert,
    SystemLog,
    assign_alert_geometry,
    calculate_alert_intersections,
    local_now,
    parse_noaa_cap_alert,
    retrieve_noaa_alerts,
    utc_now,
    NOAAImportError,
    normalize_manual_import_datetime,
    format_noaa_timestamp,
)


VALID_STATUSES = {'actual', 'test', 'exercise', 'system'}
VALID_MESSAGE_TYPES = {'alert', 'update', 'cancel', 'ack', 'error'}


def parse_cli_datetime(raw_value: str, description: str) -> datetime:
    """Parse a CLI datetime argument into a timezone-aware UTC datetime."""
    dt_value = normalize_manual_import_datetime(raw_value)
    if dt_value is None:
        raise argparse.ArgumentTypeError(
            f"Could not parse {description} '{raw_value}'. Provide an ISO 8601 timestamp."
        )
    return dt_value


def sanitize_status(value: Optional[str]) -> Optional[str]:
    """Normalize CLI status input to the subset accepted by the NOAA API."""
    normalized = (value or '').strip().lower()
    if not normalized or normalized == 'any':
        return None
    if normalized in VALID_STATUSES:
        return normalized
    raise argparse.ArgumentTypeError(
        f"Unsupported status '{value}'. Valid options: actual, test, exercise, system, any."
    )


def sanitize_message_type(value: Optional[str]) -> Optional[str]:
    """Normalize CLI message type to the allowed NOAA values."""
    normalized = (value or '').strip().lower()
    if not normalized or normalized == 'any':
        return None
    if normalized in VALID_MESSAGE_TYPES:
        return normalized
    raise argparse.ArgumentTypeError(
        f"Unsupported message type '{value}'. Valid options: alert, update, cancel, ack, error, any."
    )


def determine_window(args: argparse.Namespace) -> tuple[Optional[datetime], Optional[datetime]]:
    """Determine the start/end window for the NOAA query."""
    identifier = (args.identifier or '').strip()
    if identifier:
        return None, None

    now = utc_now()
    end_dt: datetime
    if args.end:
        end_dt = parse_cli_datetime(args.end, 'end time')
    else:
        end_dt = now

    if end_dt > now:
        logger.info(
            "Clamping CLI manual import end time %s to current UTC %s",
            end_dt.isoformat(),
            now.isoformat(),
        )
        end_dt = now

    if args.start:
        start_dt = parse_cli_datetime(args.start, 'start time')
    else:
        window_days = max(1, int(args.days))
        start_dt = end_dt - timedelta(days=window_days)

    if start_dt > end_dt:
        raise argparse.ArgumentTypeError('The start time must be before the end time.')

    return start_dt, end_dt


def execute_import(args: argparse.Namespace) -> int:
    """Run the manual import workflow using the shared Flask application context."""
    identifier = (args.identifier or '').strip()
    zone = (args.zone or '').strip()
    event_filter = (args.event or '').strip()
    status_filter = sanitize_status(args.status)
    message_type_filter = sanitize_message_type(args.message_type)
    limit_value = max(1, min(int(args.limit or 10), 50))

    start_dt, end_dt = determine_window(args)
    start_iso = format_noaa_timestamp(start_dt)
    end_iso = format_noaa_timestamp(end_dt)

    logger.info(
        "Manual NOAA fetch starting with identifier=%s, zone=%s, start=%s, end=%s",
        identifier or '—',
        zone or '—',
        start_iso or '—',
        end_iso or '—',
    )

    try:
        alerts_payloads, query_url, params = retrieve_noaa_alerts(
            identifier=identifier or None,
            start=start_dt,
            end=end_dt,
            zone=zone or None,
            event=event_filter or None,
            status=status_filter,
            message_type=message_type_filter,
            limit=limit_value,
        )
    except NOAAImportError as exc:
        logger.error("Manual NOAA fetch failed: %s", exc)
        if exc.detail:
            logger.error("NOAA detail: %s", exc.detail)
        if exc.query_url:
            logger.error("NOAA query URL: %s", exc.query_url)
        return 1

    logger.info("NOAA query returned %s alert payload(s)", len(alerts_payloads))

    dry_run = bool(args.dry_run)
    if dry_run:
        logger.info('Dry run enabled — no database changes will be committed.')

    inserted = 0
    updated = 0
    skipped = 0
    identifiers = []

    for feature in alerts_payloads:
        parsed_result = parse_noaa_cap_alert(feature)
        if not parsed_result:
            skipped += 1
            continue

        parsed, geometry = parsed_result
        alert_identifier = parsed['identifier']

        if alert_identifier not in identifiers:
            identifiers.append(alert_identifier)

        existing = CAPAlert.query.filter_by(identifier=alert_identifier).first()

        if existing:
            if dry_run:
                logger.info("DRY RUN: would update alert %s (%s)", alert_identifier, parsed.get('event'))
                updated += 1
                continue

            for key, value in parsed.items():
                setattr(existing, key, value)
            existing.updated_at = utc_now()
            assign_alert_geometry(existing, geometry)
            db.session.flush()
            try:
                if existing.geom:
                    calculate_alert_intersections(existing)
            except Exception as intersection_error:  # pragma: no cover - diagnostic logging
                logger.warning(
                    "Intersection recalculation failed for alert %s: %s",
                    alert_identifier,
                    intersection_error,
                )
            updated += 1
        else:
            if dry_run:
                logger.info("DRY RUN: would insert alert %s (%s)", alert_identifier, parsed.get('event'))
                inserted += 1
                continue

            new_alert = CAPAlert(**parsed)
            new_alert.created_at = utc_now()
            new_alert.updated_at = utc_now()
            assign_alert_geometry(new_alert, geometry)
            db.session.add(new_alert)
            db.session.flush()
            try:
                if new_alert.geom:
                    calculate_alert_intersections(new_alert)
            except Exception as intersection_error:  # pragma: no cover - diagnostic logging
                logger.warning(
                    "Intersection calculation failed for new alert %s: %s",
                    alert_identifier,
                    intersection_error,
                )
            inserted += 1

    if dry_run:
        db.session.rollback()
        logger.info(
            "Dry run complete — %s would be inserted, %s would be updated, %s skipped",
            inserted,
            updated,
            skipped,
        )
        return 0

    try:
        log_entry = SystemLog(
            level='INFO',
            message='Manual NOAA alert import executed via CLI',
            module='admin',
            details={
                'identifiers': identifiers,
                'inserted': inserted,
                'updated': updated,
                'skipped': skipped,
                'query_url': query_url,
                'params': params,
                'requested_filters': {
                    'identifier': identifier or None,
                    'start': start_iso,
                    'end': end_iso,
                    'zone': zone or None,
                    'event': event_filter or None,
                    'status': status_filter or 'any',
                    'message_type': message_type_filter or 'any',
                    'limit': limit_value,
                },
                'requested_at_utc': utc_now().isoformat(),
                'requested_at_local': local_now().isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging
        db.session.rollback()
        logger.error("Failed to persist manual import log: %s", exc)
        return 1

    logger.info(
        "Manual NOAA fetch complete — %s inserted, %s updated, %s skipped",
        inserted,
        updated,
        skipped,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Fetch NOAA alerts (including expired) and store them locally.'
    )
    parser.add_argument('--identifier', help='Specific alert identifier to import.')
    parser.add_argument('--zone', help='NOAA zone identifier (e.g., OHZ016).')
    parser.add_argument('--event', help='Filter by event name (e.g., Tornado Warning).')
    parser.add_argument('--status', default='actual', help='NOAA alert status filter (actual/test/exercise/system/any).')
    parser.add_argument(
        '--message-type',
        default='alert',
        help='NOAA message type (alert/update/cancel/ack/error/any).',
    )
    parser.add_argument('--start', help='Start of the date range (ISO 8601).')
    parser.add_argument('--end', help='End of the date range (ISO 8601).')
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Window length in days when --start is omitted (default: 7).',
    )
    parser.add_argument('--limit', type=int, default=10, help='Maximum number of alerts to fetch (1-50).')
    parser.add_argument('--dry-run', action='store_true', help='Parse alerts without modifying the database.')
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with app.app_context():
        try:
            return execute_import(args)
        except argparse.ArgumentTypeError as exc:
            logger.error(str(exc))
            return 2
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Unexpected error during manual import: %s", exc)
            return 1


if __name__ == '__main__':
    sys.exit(main())
