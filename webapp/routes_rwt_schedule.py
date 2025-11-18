"""Routes for RWT schedule configuration management."""

from __future__ import annotations

from typing import List

from flask import jsonify, render_template, request
from app_core.extensions import db
from app_core.models import RWTScheduleConfig, SystemLog
from app_utils.eas import manual_default_same_codes
from app_utils.fips_codes import get_us_state_county_tree, get_same_lookup


def register_routes(app, logger):
    """Register RWT schedule configuration routes."""

    @app.route('/rwt-schedule')
    def rwt_schedule_page():
        """Render the RWT schedule configuration page."""
        # Provide state/county tree for proper selection UI
        state_tree = get_us_state_county_tree()
        same_lookup = get_same_lookup()

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
                # Return default configuration
                default_same_codes = manual_default_same_codes()
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
                        'same_codes': default_same_codes,
                        'last_run_at': None,
                        'last_run_status': None,
                        'last_run_details': {},
                        'same_codes_source': 'location_defaults',
                    }
                })

            payload = config.to_dict()
            if not payload.get('same_codes'):
                payload['same_codes'] = manual_default_same_codes()
            payload['same_codes_source'] = 'location_defaults'

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
            if same_codes_input is None:
                same_codes_input = manual_default_same_codes()
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
                'config': config.to_dict()
            })

        except ValueError as exc:
            return jsonify({'success': False, 'error': f'Invalid value: {exc}'}), 400
        except Exception as exc:
            logger.error('Failed to save RWT schedule config: %s', exc)
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Failed to save configuration'}), 500

    @app.route('/api/rwt-schedule/test', methods=['POST'])
    def test_rwt_schedule():
        """Manually trigger a test RWT broadcast."""
        try:
            config = RWTScheduleConfig.query.first()
            if config is None:
                return jsonify({'success': False, 'error': 'No configuration found'}), 404

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
