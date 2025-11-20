"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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
from datetime import datetime, timedelta, timezone
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
        if not same_codes:
            same_codes = manual_default_same_codes()

        if not same_codes:
            raise ValueError(
                "No SAME/FIPS codes are configured for automatic RWT broadcasts"
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

    def _run_loop(self):
        """Main scheduler loop."""
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
        """Check if RWT should be sent and send it if conditions are met."""
        ctx = None
        if not has_app_context():
            ctx = self.app.app_context()
            ctx.push()

        try:
            # Get active configuration
            config = RWTScheduleConfig.query.filter_by(enabled=True).first()
            if config is None:
                return  # No active configuration

            now = datetime.now(timezone.utc)

            # Check if current day is in configured days
            current_day = now.weekday()  # 0=Monday, 6=Sunday
            if current_day not in (config.days_of_week or []):
                return  # Not a configured day

            # Check if current time is within configured window
            current_time_minutes = now.hour * 60 + now.minute
            start_time_minutes = config.start_hour * 60 + config.start_minute
            end_time_minutes = config.end_hour * 60 + config.end_minute

            if not (start_time_minutes <= current_time_minutes <= end_time_minutes):
                return  # Not within time window

            # Check if RWT was already sent today
            if config.last_run_at:
                last_run_date = config.last_run_at.date()
                today_date = now.date()

                if last_run_date == today_date and config.last_run_status == 'success':
                    # Already sent today
                    return

            # All conditions met - send RWT
            self.logger.info("Triggering automatic RWT broadcast")
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
