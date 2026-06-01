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

"""Routes for RWT schedule configuration management."""

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from flask import jsonify, render_template, request
from app_core.extensions import db
from app_core.models import RWTScheduleConfig, SystemLog
from app_utils.fips_codes import get_us_state_county_tree, get_extended_same_lookup


def _serialize_config(config: Optional[RWTScheduleConfig]) -> dict:
    """Return the config dict augmented with next_fire_at (ISO local)."""
    from app_core.rwt_scheduler import compute_next_fire
    if config is None:
        return {}
    payload = config.to_dict()
    try:
        next_fire = compute_next_fire(config)
        payload['next_fire_at'] = next_fire.isoformat() if next_fire else None
    except Exception:
        payload['next_fire_at'] = None
    return payload


def _next_configured_date(
    configured_days: List[int],
    skip_until: Optional[date],
    today: date,
) -> Optional[date]:
    """Return the first configured-weekday date strictly after ``skip_until``
    (or after today if no skip set)."""
    if not configured_days:
        return None
    anchor = (skip_until or today)
    for offset in range(1, 15):
        candidate = anchor + timedelta(days=offset)
        if candidate.weekday() in configured_days:
            return candidate
    return None


def register_routes(app, logger):
    """Register RWT schedule configuration routes."""

    @app.route('/rwt-schedule')
    def rwt_schedule_page():
        """Render the RWT schedule configuration page."""
        # Provide state/county tree for proper selection UI
        state_tree = get_us_state_county_tree()
        same_lookup = get_extended_same_lookup()

        return render_template(
            'rwt_schedule.html',
            state_tree=state_tree,
            same_lookup=same_lookup,
        )

    @app.route('/api/rwt-schedule/config', methods=['GET'])
    def get_rwt_schedule_config():
        """Get current RWT schedule configuration."""
        try:
            config = RWTScheduleConfig.query.first()

            if config is None:
                # Return default configuration with EMPTY same_codes
                # RWT should NOT auto-populate with location filtering FIPS codes
                # because those include nationwide (000000) and are meant for
                # filtering incoming alerts, NOT for RWT broadcast targeting.
                return jsonify({
                    'success': True,
                    'config': {
                        'id': None,
                        'enabled': False,
                        'days_of_week': [],
                        'start_hour': 8,
                        'start_minute': 0,
                        'end_hour': 16,
                        'end_minute': 0,
                        'same_codes': [],  # Empty - must be explicitly configured for RWT
                        'last_run_at': None,
                        'last_run_status': None,
                        'last_run_details': {},
                        'skip_until': None,
                        'next_fire_at': None,
                        'last_heartbeat_at': None,
                        'same_codes_source': 'not_configured',
                        'same_codes_note': 'RWT SAME codes must be explicitly configured. Use only your local broadcast area codes, NOT your alert filtering FIPS codes.',
                    }
                })

            payload = _serialize_config(config)
            # Do NOT auto-populate with location filtering FIPS codes
            if not payload.get('same_codes'):
                payload['same_codes'] = []
                payload['same_codes_source'] = 'not_configured'
                payload['same_codes_note'] = 'RWT SAME codes must be explicitly configured. Use only your local broadcast area codes, NOT your alert filtering FIPS codes.'
            else:
                payload['same_codes_source'] = 'configured'

            return jsonify({
                'success': True,
                'config': payload
            })

        except Exception as exc:
            logger.error('Failed to get RWT schedule config: %s', exc)
            return jsonify({'success': False, 'error': 'Failed to load configuration'}), 500

    @app.route('/api/rwt-schedule/config', methods=['POST'])
    def save_rwt_schedule_config():
        """Save RWT schedule configuration."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400

            # Validate data
            enabled = bool(data.get('enabled', False))
            days_of_week = data.get('days_of_week', [])
            if not isinstance(days_of_week, list):
                return jsonify({'success': False, 'error': 'days_of_week must be an array'}), 400

            # Validate days are 0-6 (Monday-Sunday)
            for day in days_of_week:
                if not isinstance(day, int) or day < 0 or day > 6:
                    return jsonify({'success': False, 'error': 'Invalid day of week (must be 0-6)'}), 400

            start_hour = int(data.get('start_hour', 8))
            start_minute = int(data.get('start_minute', 0))
            end_hour = int(data.get('end_hour', 16))
            end_minute = int(data.get('end_minute', 0))

            # Validate time ranges
            if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
                return jsonify({'success': False, 'error': 'Invalid start time'}), 400
            if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
                return jsonify({'success': False, 'error': 'Invalid end time'}), 400

            same_codes_input = data.get('same_codes')
            # Do NOT fallback to location filtering FIPS codes - RWT codes must be explicit
            if same_codes_input is None:
                same_codes_input = []
            elif not isinstance(same_codes_input, list):
                return jsonify({'success': False, 'error': 'same_codes must be an array'}), 400

            same_codes: List[str] = []
            seen_codes = set()
            for code in same_codes_input:
                digits = ''.join(ch for ch in str(code) if ch.isdigit())
                if not digits:
                    continue
                normalized = digits.zfill(6)[:6]
                if normalized in seen_codes:
                    continue
                seen_codes.add(normalized)
                same_codes.append(normalized)

            if len(same_codes) > 31:
                same_codes = same_codes[:31]

            if enabled and not same_codes:
                return jsonify({'success': False, 'error': 'Configure at least one SAME/FIPS code before enabling automatic RWT broadcasts.'}), 400

            # Get or create configuration
            config = RWTScheduleConfig.query.first()
            if config is None:
                config = RWTScheduleConfig()

            # Update configuration
            config.enabled = enabled
            config.days_of_week = days_of_week
            config.start_hour = start_hour
            config.start_minute = start_minute
            config.end_hour = end_hour
            config.end_minute = end_minute
            config.same_codes = same_codes

            db.session.add(config)

            # Log the configuration change
            db.session.add(SystemLog(
                level='INFO',
                message='RWT schedule configuration updated',
                module='rwt_schedule',
                details={
                    'enabled': enabled,
                    'days_of_week': days_of_week,
                    'time_window': f"{start_hour:02d}:{start_minute:02d}-{end_hour:02d}:{end_minute:02d}",
                    'same_codes_count': len(same_codes),
                }
            ))

            db.session.commit()

            return jsonify({
                'success': True,
                'config': _serialize_config(config)
            })

        except ValueError as exc:
            return jsonify({'success': False, 'error': f'Invalid value: {exc}'}), 400
        except Exception as exc:
            logger.error('Failed to save RWT schedule config: %s', exc)
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Failed to save configuration'}), 500

    @app.route('/api/rwt-schedule/skip-week', methods=['POST'])
    def skip_rwt_week():
        """Skip the upcoming scheduled RWT broadcast(s).

        Sets ``skip_until`` to a date that covers all configured days in
        the current scheduled week.  If today is itself a configured day
        and the broadcast hasn't fired yet, today is included.
        """
        try:
            config = RWTScheduleConfig.query.first()
            if config is None:
                return jsonify({'success': False, 'error': 'No configuration found'}), 404

            configured_days = sorted(int(d) for d in (config.days_of_week or []))
            if not configured_days:
                return jsonify({
                    'success': False,
                    'error': 'No days configured — nothing to skip',
                }), 400

            now_local = datetime.now(timezone.utc).astimezone()
            today = now_local.date()

            # Find the next configured weekday strictly AFTER today.  Setting
            # skip_until to the day BEFORE that means the scheduler will
            # suppress all configured fires from today through the end of
            # this scheduled "week" but resume at the next one.
            next_after = _next_configured_date(configured_days, None, today)
            if next_after is None:
                # Shouldn't happen given configured_days is non-empty.
                return jsonify({
                    'success': False,
                    'error': 'Could not determine next scheduled date',
                }), 500

            new_skip = next_after - timedelta(days=1)
            config.skip_until = new_skip
            db.session.add(config)
            db.session.add(SystemLog(
                level='INFO',
                message='RWT schedule: skip-week activated',
                module='rwt_schedule',
                details={
                    'skip_until': new_skip.isoformat(),
                    'next_fire_after': next_after.isoformat(),
                },
            ))
            db.session.commit()

            return jsonify({
                'success': True,
                'config': _serialize_config(config),
            })

        except Exception as exc:
            logger.error('Failed to skip RWT week: %s', exc)
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Failed to skip week'}), 500

    @app.route('/api/rwt-schedule/skip-week', methods=['DELETE'])
    def clear_rwt_skip():
        """Clear ``skip_until`` so the scheduler resumes immediately."""
        try:
            config = RWTScheduleConfig.query.first()
            if config is None:
                return jsonify({'success': False, 'error': 'No configuration found'}), 404

            if config.skip_until is None:
                return jsonify({
                    'success': True,
                    'config': _serialize_config(config),
                })

            previous = config.skip_until
            config.skip_until = None
            db.session.add(config)
            db.session.add(SystemLog(
                level='INFO',
                message='RWT schedule: skip-week cleared',
                module='rwt_schedule',
                details={'previous_skip_until': previous.isoformat()},
            ))
            db.session.commit()

            return jsonify({
                'success': True,
                'config': _serialize_config(config),
            })

        except Exception as exc:
            logger.error('Failed to clear RWT skip: %s', exc)
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Failed to clear skip'}), 500

    @app.route('/api/rwt-schedule/test', methods=['POST'])
    def test_rwt_schedule():
        """Manually trigger a test RWT broadcast."""
        try:
            config = RWTScheduleConfig.query.first()
            if config is None:
                return jsonify({'success': False, 'error': 'No configuration found'}), 404

            # Refuse to start a second broadcast while one is already holding
            # the airchain.  The composite now plays on a background thread, so
            # the request returns immediately and the button re-enables right
            # away — without this guard an operator could stack overlapping
            # transmissions on the relay before the first one finishes.
            from app_utils.eas import get_broadcast_state
            broadcast_state = get_broadcast_state()
            if broadcast_state.get('active'):
                return jsonify({
                    'success': False,
                    'error': (
                        'A broadcast is already in progress. Wait for the '
                        'air-chain to be released before sending another RWT.'
                    ),
                }), 409

            # Import here to avoid circular dependencies
            from app_core.rwt_scheduler import trigger_rwt_broadcast

            result = trigger_rwt_broadcast(config, logger)

            return jsonify({
                'success': True,
                'result': result
            })

        except Exception as exc:
            logger.error('Failed to test RWT broadcast: %s', exc)
            return jsonify({'success': False, 'error': str(exc)}), 500
