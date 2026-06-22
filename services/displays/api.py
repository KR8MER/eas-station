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

"""Flask blueprint for ``/api/hardware/display/push``.

This is the single endpoint the web service calls when an operator
pushes a configured ``DisplayScreen`` to OLED / LED / VFD hardware.
All blocking I2C / GPIO / serial ioctl() calls happen here in the
hardware-service process so the web service's gevent workers never
touch device drivers directly (which deadlocks the event loop).
"""

import logging
from typing import Callable

from flask import Blueprint, Flask, jsonify, request

logger = logging.getLogger(__name__)


def create_blueprint(*, get_flask_app: Callable[[], Flask]) -> Blueprint:
    """Build and return the ``/api/hardware/display/push`` blueprint.

    Parameters
    ----------
    get_flask_app:
        Returns the orchestrator's SQLAlchemy-configured Flask app — the
        push handler enters its app context to query ``DisplayScreen``
        and commit the rendered-counter back to the DB.
    """
    bp = Blueprint("display_api", __name__)

    @bp.route('/api/hardware/display/push', methods=['POST'])
    def push_screen_to_display():
        """Render a DisplayScreen and push it to the physical display.

        The web service proxies POST /api/screens/<id>/display here so that
        all blocking I2C / GPIO / serial ioctl() calls happen in this process
        (eas-station-hardware.service), never in the gevent web workers.

        Request body (JSON): { "screen_id": <int> }
        """
        try:
            data = request.json or {}
            screen_id = data.get('screen_id')
            if not screen_id:
                return jsonify({'success': False, 'error': 'screen_id is required'}), 400

            _flask_app = get_flask_app()
            with _flask_app.app_context():
                from app_core.models import DisplayScreen
                from scripts.screen_renderer import ScreenRenderer

                screen = DisplayScreen.query.get(int(screen_id))
                if not screen:
                    return jsonify({'success': False, 'error': 'Screen not found'}), 404

                renderer = ScreenRenderer(allow_preview_samples=False)
                rendered = renderer.render_screen(screen.to_dict())
                if not rendered:
                    return jsonify({'success': False, 'error': 'Failed to render screen'}), 500

                if screen.display_type == 'oled':
                    from app_core.oled import oled_controller, OLEDLine
                    if not oled_controller:
                        return jsonify({'success': False, 'error': 'OLED controller not available'}), 503

                    # New elements-based format (bar graphs, shapes, icons, etc.)
                    raw_elements = rendered.get('elements')
                    if raw_elements is not None and isinstance(raw_elements, list):
                        oled_controller.render_frame(
                            raw_elements,
                            clear=rendered.get('clear', True),
                            invert=rendered.get('invert'),
                        )
                    else:
                        # Legacy lines-based format
                        raw_lines = rendered.get('lines', [])
                        line_objects = []
                        for entry in raw_lines:
                            if not isinstance(entry, dict):
                                continue
                            try:
                                x_val = int(entry.get('x', 0) or 0)
                            except (TypeError, ValueError):
                                x_val = 0
                            y_raw = entry.get('y')
                            try:
                                y_val = int(y_raw) if y_raw is not None else None
                            except (TypeError, ValueError):
                                y_val = None
                            mw_raw = entry.get('max_width')
                            try:
                                mw_val = int(mw_raw) if mw_raw is not None else None
                            except (TypeError, ValueError):
                                mw_val = None
                            try:
                                sp_val = int(entry.get('spacing', 2))
                            except (TypeError, ValueError):
                                sp_val = 2
                            line_objects.append(OLEDLine(
                                text=str(entry.get('text', '')),
                                x=x_val,
                                y=y_val,
                                font=str(entry.get('font', 'small')),
                                wrap=bool(entry.get('wrap', True)),
                                max_width=mw_val,
                                spacing=sp_val,
                                invert=entry.get('invert'),
                                allow_empty=bool(entry.get('allow_empty', False)),
                            ))
                        oled_controller.display_lines(
                            line_objects,
                            clear=rendered.get('clear', True),
                            invert=rendered.get('invert'),
                        )

                elif screen.display_type == 'led':
                    import app_core.led as led_module
                    if not led_module.led_controller:
                        return jsonify({'success': False, 'error': 'LED controller not available'}), 503
                    from webapp.routes_screens import _convert_led_enum
                    lines = rendered.get('lines', [])
                    color_str = rendered.get('color', 'AMBER')
                    mode_str = rendered.get('mode', 'HOLD')
                    speed_str = rendered.get('speed', 'SPEED_3')
                    color = _convert_led_enum(led_module.Color, color_str,
                                             led_module.Color.AMBER if led_module.Color else color_str)
                    mode = _convert_led_enum(led_module.DisplayMode, mode_str,
                                            led_module.DisplayMode.HOLD if led_module.DisplayMode else mode_str)
                    speed = _convert_led_enum(led_module.Speed, speed_str,
                                             led_module.Speed.SPEED_3 if led_module.Speed else speed_str)
                    led_module.led_controller.send_message(lines=lines, color=color, mode=mode, speed=speed)

                elif screen.display_type == 'vfd':
                    from app_core.vfd import vfd_controller
                    if not vfd_controller:
                        return jsonify({'success': False, 'error': 'VFD controller not available'}), 503
                    for command in rendered:
                        cmd_type = command.get('type')
                        if cmd_type == 'clear':
                            vfd_controller.clear_screen()
                        elif cmd_type == 'text':
                            vfd_controller.draw_text(
                                command.get('x', 0), command.get('y', 0), command.get('text', ''))
                        elif cmd_type == 'rectangle':
                            vfd_controller.draw_rectangle(
                                command.get('x1', 0), command.get('y1', 0),
                                command.get('x2', 10), command.get('y2', 10),
                                filled=command.get('filled', False))
                        elif cmd_type == 'line':
                            vfd_controller.draw_line(
                                command.get('x1', 0), command.get('y1', 0),
                                command.get('x2', 10), command.get('y2', 10))
                else:
                    return jsonify({'success': False,
                                    'error': f"Unknown display_type '{screen.display_type}'"}), 400

                # Update display statistics
                screen.display_count = (screen.display_count or 0) + 1
                from app_utils import utc_now as _utc_now
                screen.last_displayed_at = _utc_now()
                from app_core.extensions import db as _db
                _db.session.commit()

            return jsonify({'success': True,
                            'message': f"Screen '{screen.name}' displayed on {screen.display_type}"})

        except Exception as exc:
            logger.error('Error pushing screen to display: %s', exc, exc_info=True)
            return jsonify({'success': False, 'error': str(exc)}), 500

    return bp
