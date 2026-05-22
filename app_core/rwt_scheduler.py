"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""RWT (Required Weekly Test) automatic scheduler.

This module provides scheduled background tasks for automatically sending
RWT broadcasts according to configured schedules.
"""

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from flask import Flask, has_app_context
from app_core.extensions import db
from app_core.models import RWTScheduleConfig, ManualEASActivation, SystemLog
from app_utils import utc_now
from app_utils.eas import (
    EASAudioGenerator,
    build_same_header,
    load_eas_config,
    manual_default_same_codes,
)

logger = logging.getLogger(__name__)


def compute_next_fire(
    config: RWTScheduleConfig,
    now_local: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next datetime (local timezone, aware) at which this
    configuration will fire an automatic RWT broadcast.

    Returns ``None`` when the config is disabled, has no configured days, or
    would otherwise never fire.

    Rules:
      * The fire time on a configured day is the start of the time window
        (start_hour:start_minute, local time).  We deliberately return
        ``window_start`` even when ``now > window_start`` — the scheduler
        thread evaluates the window every minute and will fire on the next
        iteration, so the UI should show the operator-scheduled time rather
        than a moving target that advances by one minute on every refresh
        (which the previous ``max(now, window_start)`` formulation produced
        and operators read as "the broadcast keeps getting pushed back").
      * If today is a configured day, the window has not closed, and an
        RWT hasn't already been sent successfully today, fire is today at
        ``window_start``.
      * If ``skip_until`` is set, dates on or before it are skipped.
      * Otherwise scan the next 14 days for the first configured weekday.
    """
    if not config.enabled:
        return None
    configured_days = [int(d) for d in (config.days_of_week or [])]
    if not configured_days:
        return None

    if now_local is None:
        now_local = datetime.now(timezone.utc).astimezone()

    tz = now_local.tzinfo
    today = now_local.date()
    start_h = int(config.start_hour or 0)
    start_m = int(config.start_minute or 0)
    end_h = int(config.end_hour or 0)
    end_m = int(config.end_minute or 0)

    skip_until = getattr(config, 'skip_until', None)

    last_success_date: Optional[date] = None
    if config.last_run_at and config.last_run_status == 'success':
        last_run_local = config.last_run_at
        if last_run_local.tzinfo is None:
            last_run_local = last_run_local.replace(tzinfo=timezone.utc)
        last_success_date = last_run_local.astimezone(tz).date()

    # Scan today + next 14 days for the first day that qualifies.
    for offset in range(0, 15):
        candidate_date = today + timedelta(days=offset)
        if candidate_date.weekday() not in configured_days:
            continue
        if skip_until and candidate_date <= skip_until:
            continue
        if last_success_date == candidate_date:
            continue
        window_start = datetime(
            candidate_date.year, candidate_date.month, candidate_date.day,
            start_h, start_m, tzinfo=tz,
        )
        window_end = datetime(
            candidate_date.year, candidate_date.month, candidate_date.day,
            end_h, end_m, tzinfo=tz,
        )
        if offset == 0:
            # Today: if we're past the window, the broadcast missed its
            # slot — move on to the next configured day.  Otherwise return
            # the operator-configured window start.  Previously this used
            # ``max(now, window_start)`` which made the UI's "Next
            # scheduled fire" timestamp advance by one minute on every
            # refresh once we were inside the window — operators read
            # that as the scheduler "pushing back" the broadcast.
            if now_local > window_end:
                continue
            return window_start
        return window_start

    return None


def trigger_rwt_broadcast(config: RWTScheduleConfig, logger_instance=None) -> Dict[str, Any]:
    """Trigger an RWT broadcast with the given configuration.

    Args:
        config: RWT schedule configuration
        logger_instance: Logger to use (defaults to module logger)

    Returns:
        Dictionary with broadcast result information
    """
    log = logger_instance or logger

    try:
        from datetime import datetime, timezone
        from types import SimpleNamespace

        # Build RWT identifier
        now = datetime.now(timezone.utc)
        identifier = f"RWT-AUTO-{now.strftime('%Y%m%d%H%M%S')}"

        # Load EAS config (includes originator and station_id from environment)
        eas_config = load_eas_config()

        # Create alert object for RWT
        alert_object = SimpleNamespace(
            identifier=identifier,
            event='Required Weekly Test',
            headline='Automated Required Weekly Test',
            description='This is an automated Required Weekly Test of the Emergency Alert System.',
            instruction='No action required. This is only a test.',
            sent=now,
            expires=now + timedelta(minutes=15),
            status='Test',
            message_type='Alert',
        )

        same_codes = [code for code in (config.same_codes or []) if code]

        # IMPORTANT: RWT broadcasts should ONLY use explicitly configured SAME codes.
        # We do NOT fall back to location filtering FIPS codes because:
        # 1. Location FIPS codes are for FILTERING incoming alerts (includes nationwide 000000)
        # 2. RWT should only target the station's local broadcast area
        # 3. Broadcasting RWT to nationwide would be inappropriate
        if not same_codes:
            raise ValueError(
                "No SAME/FIPS codes configured for RWT broadcasts. "
                "Please configure specific SAME codes for RWT on the RWT Schedule page. "
                "Do NOT use your alert filtering FIPS codes - RWT should only target "
                "your local broadcast area, not nationwide or all monitored areas."
            )

        # Prepare payload wrapper
        payload_wrapper = {
            'identifier': identifier,
            'sent': now,
            'expires': now + timedelta(minutes=15),
            'status': 'Test',
            'message_type': 'Alert',
            'raw_json': {
                'properties': {
                    'geocode': {
                        'SAME': same_codes,
                    }
                }
            },
        }

        # Build SAME header
        header, formatted_locations, resolved_event_code = build_same_header(
            alert_object,
            payload_wrapper,
            eas_config,
            location_settings=None,
        )

        # Generate audio components
        generator = EASAudioGenerator(eas_config, logger=log)

        # For RWT: no TTS, no attention tones (will be auto-detected by event code)
        components = generator.build_manual_components(
            alert_object,
            header,
            tone_profile='none',
            include_tts=False,
        )

        if not components:
            raise ValueError("Failed to generate RWT audio components")

        # Store in database
        activation_record = ManualEASActivation(
            identifier=identifier,
            event_code='RWT',
            event_name='Required Weekly Test',
            status='Test',
            message_type='Alert',
            same_header=header,
            same_locations=formatted_locations,
            tone_profile='none',
            tone_seconds=0.0,
            sample_rate=eas_config.get('sample_rate', 16000),
            includes_tts=False,
            sent_at=now,
            expires_at=now + timedelta(minutes=15),
            headline='Automated Required Weekly Test',
            message_text='This is an automated Required Weekly Test of the Emergency Alert System.',
            instruction_text='No action required. This is only a test.',
            duration_minutes=15,
            metadata_payload={
                'automated': True,
                'schedule_id': config.id,
            },
        )

        db.session.add(activation_record)

        # Log the broadcast
        db.session.add(SystemLog(
            level='INFO',
            message='Automated RWT broadcast sent',
            module='rwt_scheduler',
            details={
                'identifier': identifier,
                'same_header': header,
                'location_count': len(same_codes),
                'schedule_id': config.id,
            }
        ))

        # Update config last run status
        config.last_run_at = now
        config.last_run_status = 'success'
        config.last_run_details = {
            'identifier': identifier,
            'activation_id': activation_record.id,
            'timestamp': now.isoformat(),
        }
        db.session.add(config)

        db.session.commit()

        log.info("RWT broadcast sent successfully: %s", identifier)

        return {
            'success': True,
            'identifier': identifier,
            'activation_id': activation_record.id,
            'same_header': header,
        }

    except Exception as exc:
        log.error("Failed to trigger RWT broadcast: %s", exc, exc_info=True)
        try:
            config.last_run_at = utc_now()
            config.last_run_status = 'failed'
            config.last_run_details = {
                'error': str(exc),
                'timestamp': utc_now().isoformat(),
            }
            db.session.add(config)
            db.session.commit()
        except Exception as db_exc:
            log.error("Failed to update config after error: %s", db_exc)

        return {
            'success': False,
            'error': str(exc),
        }


class RWTScheduler:
    """Manages automatic RWT broadcast scheduling."""

    def __init__(self, app: Flask, check_interval_minutes: int = 1):
        """Initialize the RWT scheduler.

        Args:
            check_interval_minutes: How often to check if RWT should be sent (default: 1 minute)
        """
        if app is None:
            raise ValueError("A Flask application instance is required for the RWT scheduler")

        self.check_interval = timedelta(minutes=check_interval_minutes)
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.logger = logger
        self.app = app
        # Iteration counter for periodic heartbeat logging. Without this the
        # scheduler is silent when no config matches the current time, which
        # makes it impossible to tell whether the loop is running at all.
        self._iteration = 0

    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            self.logger.warning("RWT scheduler is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logger.info("RWT scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("RWT scheduler stopped")

    def _write_heartbeat(self, config: RWTScheduleConfig) -> None:
        """Persist a heartbeat timestamp so the UI can show liveness across
        all Gunicorn workers.  Uses a narrow UPDATE so we never accidentally
        rewrite operator-managed columns from this thread.
        """
        try:
            config.last_heartbeat_at = utc_now()
            db.session.add(config)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            # Heartbeat write failure is not fatal — keep the loop running.
            self.logger.debug("Failed to write RWT heartbeat: %s", exc)

    def _run_loop(self):
        """Main scheduler loop."""
        self.logger.info(
            "RWT scheduler loop started (check interval: %.0f seconds)",
            self.check_interval.total_seconds(),
        )
        while self.running:
            try:
                with self.app.app_context():
                    self._check_and_send_rwt()
            except Exception as e:
                self.logger.error("Error in RWT scheduler loop: %s", e, exc_info=True)
                time.sleep(60)  # Wait before retrying
                continue

            # Sleep for the check interval outside the application context
            time.sleep(self.check_interval.total_seconds())

    def _check_and_send_rwt(self):
        """Check if RWT should be sent and send it if conditions are met.

        Schedule times (start_hour/start_minute, end_hour/end_minute) and
        days_of_week are entered by operators in their local timezone via the
        web UI — the UI shows no timezone selector and displays clocks in
        local time.  Historically this method compared against UTC, which
        silently shifted the firing window by the local UTC offset (so a
        configured "Wed 8 AM–4 PM EDT" really fired "4 AM–12 PM EDT" and
        skipped Wednesday entirely after 8 PM local because that's already
        Thursday in UTC).  Comparing against local time matches the
        operator's mental model.
        """
        ctx = None
        if not has_app_context():
            ctx = self.app.app_context()
            ctx.push()

        try:
            self._iteration += 1

            # Get active configuration
            config = RWTScheduleConfig.query.filter_by(enabled=True).first()
            if config is None:
                # Heartbeat once an hour so operators can confirm the loop is
                # alive even with no enabled config in the database.
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT scheduler loop alive — no enabled RWT schedule configured"
                    )
                return

            # Persist a heartbeat on every iteration so the UI can show the
            # scheduler is alive even when no fire conditions are met.
            self._write_heartbeat(config)

            # Use local time for day/window comparisons because operators
            # configure the schedule in local time via the UI.
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone()  # System local timezone

            # Honour skip_until: operator-set pause for one or more upcoming
            # scheduled days (e.g. "skip this week").
            if config.skip_until and now_local.date() <= config.skip_until:
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT scheduler skipping per skip_until=%s (today=%s)",
                        config.skip_until.isoformat(), now_local.date().isoformat(),
                    )
                return

            # Check if current day is in configured days
            current_day = now_local.weekday()  # 0=Monday, 6=Sunday
            configured_days = list(config.days_of_week or [])
            if current_day not in configured_days:
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT scheduler loop alive — today (weekday %d, local) "
                        "not in configured days %s",
                        current_day, configured_days,
                    )
                return

            # Check if current time is within configured window
            current_time_minutes = now_local.hour * 60 + now_local.minute
            start_time_minutes = config.start_hour * 60 + config.start_minute
            end_time_minutes = config.end_hour * 60 + config.end_minute

            if not (start_time_minutes <= current_time_minutes <= end_time_minutes):
                if self._iteration % 30 == 1:
                    self.logger.info(
                        "RWT scheduler waiting for window: local time %02d:%02d, "
                        "window %02d:%02d–%02d:%02d",
                        now_local.hour, now_local.minute,
                        config.start_hour, config.start_minute,
                        config.end_hour, config.end_minute,
                    )
                return

            # Check if RWT was already sent today (compare in local time to
            # match the operator-facing "once per scheduled day" semantics).
            if config.last_run_at:
                last_run_local = config.last_run_at
                if last_run_local.tzinfo is None:
                    last_run_local = last_run_local.replace(tzinfo=timezone.utc)
                last_run_local = last_run_local.astimezone()
                if (
                    last_run_local.date() == now_local.date()
                    and config.last_run_status == 'success'
                ):
                    if self._iteration % 60 == 1:
                        self.logger.info(
                            "RWT already sent today at %s — skipping",
                            last_run_local.isoformat(timespec='seconds'),
                        )
                    return

            # All conditions met - send RWT
            self.logger.info(
                "Triggering automatic RWT broadcast (local %s, window %02d:%02d–%02d:%02d)",
                now_local.isoformat(timespec='seconds'),
                config.start_hour, config.start_minute,
                config.end_hour, config.end_minute,
            )
            result = trigger_rwt_broadcast(config, self.logger)

            if result.get('success'):
                self.logger.info("Automatic RWT broadcast completed successfully")
            else:
                self.logger.error("Automatic RWT broadcast failed: %s", result.get('error'))

        except Exception as exc:
            self.logger.error("Failed to check/send RWT: %s", exc, exc_info=True)
        finally:
            if ctx is not None:
                ctx.pop()


# Global scheduler instance
_scheduler: Optional[RWTScheduler] = None


def get_scheduler(app: Optional[Flask] = None) -> RWTScheduler:
    """Get the global RWT scheduler instance."""
    global _scheduler
    if _scheduler is None:
        if app is None:
            raise RuntimeError(
                "A Flask application must be provided the first time the RWT scheduler is accessed"
            )
        _scheduler = RWTScheduler(app)
    return _scheduler


def start_scheduler(app: Optional[Flask] = None):
    """Start the global RWT scheduler."""
    scheduler = get_scheduler(app)
    scheduler.start()


def stop_scheduler():
    """Stop the global RWT scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None


__all__ = [
    "RWTScheduler",
    "get_scheduler",
    "start_scheduler",
    "stop_scheduler",
    "trigger_rwt_broadcast",
]
