"""Screen template renderer for LED and VFD displays.

This module provides rendering capabilities for custom display screens with
dynamic content populated from API endpoints.
"""

import logging
import re
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


class ScreenRenderer:
    """Renders custom screen templates with dynamic API data."""

    # Allowed API endpoint prefixes to prevent SSRF attacks
    ALLOWED_ENDPOINT_PREFIXES: Set[str] = {
        '/api/',
        '/health',
        '/ping',
        '/version',
    }

    def __init__(self, base_url: str = "http://localhost:5000"):
        """Initialize the screen renderer.

        Args:
            base_url: Base URL for API endpoint requests
        """
        self.base_url = base_url
        self._data_cache: Dict[str, Any] = {}
        self._cache_timestamp: Dict[str, datetime] = {}

    def _validate_endpoint(self, endpoint: str) -> bool:
        """Validate that an endpoint is safe to fetch from.

        Args:
            endpoint: API endpoint path to validate

        Returns:
            True if endpoint is allowed, False otherwise
        """
        # Ensure endpoint is a relative path (starts with /)
        if not endpoint.startswith('/'):
            logger.warning(f"Endpoint must be a relative path: {endpoint}")
            return False

        # Check for absolute URLs or protocol prefixes
        if '://' in endpoint or endpoint.startswith('//'):
            logger.warning(f"Absolute URLs not allowed: {endpoint}")
            return False

        # Check if endpoint starts with allowed prefix
        for prefix in self.ALLOWED_ENDPOINT_PREFIXES:
            if endpoint.startswith(prefix):
                return True

        logger.warning(f"Endpoint not in allowed list: {endpoint}")
        return False

    def fetch_data_source(self, endpoint: str, var_name: str, params: Optional[Dict] = None) -> None:
        """Fetch data from an API endpoint and cache it.

        Args:
            endpoint: API endpoint path (e.g., '/api/system_status')
            var_name: Variable name to store data under
            params: Optional query parameters
        """
        # Validate endpoint to prevent SSRF attacks
        if not self._validate_endpoint(endpoint):
            logger.error(f"Endpoint rejected for security reasons: {endpoint}")
            self._data_cache[var_name] = {}
            return

        try:
            url = urljoin(self.base_url, endpoint)
            response = requests.get(url, params=params or {}, timeout=5)
            response.raise_for_status()

            self._data_cache[var_name] = response.json()
            self._cache_timestamp[var_name] = datetime.utcnow()

            logger.debug(f"Fetched data from {endpoint} as '{var_name}'")
        except Exception as e:
            logger.error(f"Failed to fetch data from {endpoint}: {e}")
            self._data_cache[var_name] = {}

    def get_nested_value(self, data: Dict, path: str, default: Any = "") -> Any:
        """Get a nested value from a dictionary using dot notation.

        Args:
            data: Dictionary to search
            path: Dot-separated path (e.g., 'status.cpu_usage_percent')
            default: Default value if path not found

        Returns:
            Value at the path or default
        """
        keys = path.split('.')
        value = data

        try:
            for key in keys:
                # Handle array indexing (e.g., 'alerts[0]')
                if '[' in key and ']' in key:
                    base_key = key[:key.index('[')]
                    index = int(key[key.index('[')+1:key.index(']')])
                    value = value[base_key][index]
                else:
                    value = value[key]
            return value
        except (KeyError, IndexError, TypeError):
            return default

    def substitute_variables(self, template: str, data: Dict[str, Any]) -> str:
        """Substitute template variables with actual data.

        Supports:
        - Simple variables: {var_name}
        - Nested properties: {status.cpu_usage_percent}
        - Array indexing: {alerts[0].event}
        - Built-in functions: {system.ip_address}, {now.time}, {now.date}

        Args:
            template: Template string with {variable} placeholders
            data: Data dictionary with variable values

        Returns:
            String with variables substituted
        """
        # Add built-in variables using local timezone
        try:
            from app_utils.time import local_now
            now = local_now()
        except ImportError:
            # Fallback to system local time if app_utils not available
            now = datetime.now()

        builtin_data = {
            'now': {
                'time': now.strftime('%I:%M %p'),
                'time_24': now.strftime('%H:%M'),
                'date': now.strftime('%m/%d/%Y'),
                'datetime': now.strftime('%m/%d/%Y %I:%M %p'),
            }
        }

        # Merge data with built-ins
        all_data = {**data, **builtin_data}

        # Find all {variable} patterns
        pattern = r'\{([^}]+)\}'

        def replace_var(match):
            var_path = match.group(1)

            # Split into variable name and property path
            if '.' in var_path:
                var_name = var_path.split('.')[0]
                property_path = '.'.join(var_path.split('.')[1:])

                if var_name in all_data:
                    value = self.get_nested_value({var_name: all_data[var_name]}, var_path)
                else:
                    value = ""
            else:
                value = all_data.get(var_path, "")

            # Format the value
            if isinstance(value, float):
                # Round floats to 1 decimal place
                return f"{value:.1f}"
            elif isinstance(value, bool):
                return "Yes" if value else "No"
            elif value is None:
                return ""
            else:
                return str(value)

        return re.sub(pattern, replace_var, template)

    def render_led_screen(self, screen_data: Dict[str, Any], api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Render a LED screen template.

        Args:
            screen_data: Screen template data
            api_data: Fetched API data for variable substitution

        Returns:
            Dictionary with LED display parameters
        """
        template = screen_data.get('template_data', {})

        # Extract LED configuration
        lines = template.get('lines', [])
        color = template.get('color', 'AMBER')
        mode = template.get('mode', 'HOLD')
        speed = template.get('speed', 'SPEED_3')
        font = template.get('font', 'FONT_7x9')

        # Substitute variables in each line
        rendered_lines = []
        for line in lines[:4]:  # LED supports max 4 lines
            if isinstance(line, str):
                # Simple string line
                rendered_line = self.substitute_variables(line, api_data)
                rendered_lines.append(rendered_line[:20])  # Max 20 chars per line
            elif isinstance(line, dict):
                # Line with formatting options
                text = line.get('text', '')
                rendered_text = self.substitute_variables(text, api_data)
                rendered_lines.append({
                    'text': rendered_text[:20],
                    'color': line.get('color', color),
                    'font': line.get('font', font),
                    'mode': line.get('mode', mode),
                })

        # Pad to 4 lines
        while len(rendered_lines) < 4:
            rendered_lines.append('')

        return {
            'lines': rendered_lines,
            'color': color,
            'mode': mode,
            'speed': speed,
            'font': font,
        }

    def render_vfd_screen(self, screen_data: Dict[str, Any], api_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Render a VFD screen template.

        Args:
            screen_data: Screen template data
            api_data: Fetched API data for variable substitution

        Returns:
            List of VFD drawing commands
        """
        template = screen_data.get('template_data', {})
        commands = []

        # Clear screen first
        commands.append({'type': 'clear'})

        # Process elements
        elements = template.get('elements', [])

        for element in elements:
            elem_type = element.get('type')

            if elem_type == 'text':
                # Text element
                text = self.substitute_variables(element.get('text', ''), api_data)
                commands.append({
                    'type': 'text',
                    'x': element.get('x', 0),
                    'y': element.get('y', 0),
                    'text': text,
                })

            elif elem_type == 'progress_bar':
                # Progress bar / VU meter
                value_template = element.get('value', '0')
                value_str = self.substitute_variables(value_template, api_data)

                try:
                    value = float(value_str)
                except (ValueError, TypeError):
                    value = 0.0

                # Clamp to 0-100
                value = max(0, min(100, value))

                x = element.get('x', 0)
                y = element.get('y', 0)
                width = element.get('width', 100)
                height = element.get('height', 8)

                # Draw label if provided
                label = element.get('label', '')
                if label:
                    commands.append({
                        'type': 'text',
                        'x': x,
                        'y': max(0, y - 10),
                        'text': f"{label}: {value:.0f}%",
                    })

                # Draw progress bar outline
                commands.append({
                    'type': 'rectangle',
                    'x1': x,
                    'y1': y,
                    'x2': x + width,
                    'y2': y + height,
                    'filled': False,
                })

                # Draw filled portion
                filled_width = int((value / 100) * (width - 2))
                if filled_width > 0:
                    commands.append({
                        'type': 'rectangle',
                        'x1': x + 1,
                        'y1': y + 1,
                        'x2': x + 1 + filled_width,
                        'y2': y + height - 1,
                        'filled': True,
                    })

            elif elem_type == 'rectangle':
                # Rectangle element
                commands.append({
                    'type': 'rectangle',
                    'x1': element.get('x1', 0),
                    'y1': element.get('y1', 0),
                    'x2': element.get('x2', 10),
                    'y2': element.get('y2', 10),
                    'filled': element.get('filled', False),
                })

            elif elem_type == 'line':
                # Line element
                commands.append({
                    'type': 'line',
                    'x1': element.get('x1', 0),
                    'y1': element.get('y1', 0),
                    'x2': element.get('x2', 10),
                    'y2': element.get('y2', 10),
                })

        return commands

    def render_oled_screen(self, screen_data: Dict[str, Any], api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Render an OLED screen template.

        Supports both legacy 'lines' format and new 'elements' format for graphics.
        """

        template = screen_data.get('template_data', {})

        # Check if using new elements-based format (for bar graphs, etc.)
        elements_config = template.get('elements', [])
        if elements_config:
            return self._render_oled_elements(template, api_data)

        # Legacy lines-based format
        lines_config = template.get('lines', [])
        default_wrap = bool(template.get('wrap', True))
        default_spacing = template.get('spacing', 2)
        default_max_width = template.get('max_width')
        default_font = template.get('font')

        rendered_lines: List[Dict[str, Any]] = []
        for entry in lines_config:
            if isinstance(entry, str):
                text_value = self.substitute_variables(entry, api_data)
                rendered_lines.append({'text': text_value})
                continue

            if not isinstance(entry, dict):
                continue

            text_template = entry.get('text', '')
            rendered_text = self.substitute_variables(text_template, api_data)

            line_payload: Dict[str, Any] = {'text': rendered_text}

            if 'x' in entry:
                line_payload['x'] = entry.get('x', 0)
            if 'y' in entry:
                line_payload['y'] = entry.get('y')

            # If a template pins a line to an explicit Y coordinate and doesn't
            # override wrapping, default to False so wrapped segments don't
            # stack on top of each other at the same position.
            has_explicit_y = entry.get('y') is not None
            wrap_value = entry.get('wrap')
            if wrap_value is None:
                wrap_value = default_wrap if not has_explicit_y else False

            line_payload['wrap'] = wrap_value

            max_width_value = entry.get('max_width', default_max_width)
            if max_width_value is not None:
                line_payload['max_width'] = max_width_value

            spacing_value = entry.get('spacing', default_spacing)
            if spacing_value is not None:
                line_payload['spacing'] = spacing_value

            font_value = entry.get('font', default_font)
            if font_value:
                line_payload['font'] = font_value

            if 'invert' in entry:
                line_payload['invert'] = entry.get('invert')
            if 'allow_empty' in entry:
                line_payload['allow_empty'] = bool(entry.get('allow_empty'))

            rendered_lines.append(line_payload)

        scroll_block = template.get('scroll', {}) if isinstance(template.get('scroll'), dict) else {}
        scroll_effect = template.get('scroll_effect') or scroll_block.get('effect')
        scroll_speed = template.get('scroll_speed', scroll_block.get('speed'))
        scroll_fps = template.get('scroll_fps', scroll_block.get('fps'))

        scroll_payload = {
            'effect': scroll_effect.lower() if isinstance(scroll_effect, str) else None,
            'speed': scroll_speed,
            'fps': scroll_fps,
        }

        return {
            'lines': rendered_lines,
            'invert': template.get('invert'),
            'clear': template.get('clear', True),
            'allow_empty_frame': bool(template.get('allow_empty_frame', False)),
            'scroll_effect': scroll_payload['effect'],
            'scroll_speed': scroll_payload['speed'],
            'scroll_fps': scroll_payload['fps'],
        }

    def _render_oled_elements(self, template: Dict[str, Any], api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Render OLED screen using elements format (supports bar graphs, shapes, etc.)."""

        elements_config = template.get('elements', [])
        rendered_elements: List[Dict[str, Any]] = []

        for element in elements_config:
            if not isinstance(element, dict):
                continue

            elem_type = element.get('type', '')

            if elem_type == 'text':
                # Text element
                text_template = element.get('text', '')
                rendered_text = self.substitute_variables(text_template, api_data)

                rendered_elements.append({
                    'type': 'text',
                    'text': rendered_text,
                    'x': element.get('x', 0),
                    'y': element.get('y', 0),
                    'font': element.get('font', 'small'),
                    'invert': element.get('invert'),
                })

            elif elem_type == 'bar':
                # Bar graph element
                value_template = element.get('value', '0')
                value_str = self.substitute_variables(value_template, api_data)

                try:
                    value = float(value_str)
                except (ValueError, TypeError):
                    value = 0.0

                # Clamp to 0-100
                value = max(0.0, min(100.0, value))

                rendered_elements.append({
                    'type': 'bar',
                    'x': element.get('x', 0),
                    'y': element.get('y', 0),
                    'width': element.get('width', 50),
                    'height': element.get('height', 8),
                    'value': value,
                    'border': element.get('border', True),
                })

            elif elem_type == 'rectangle':
                # Rectangle element
                rendered_elements.append({
                    'type': 'rectangle',
                    'x': element.get('x', 0),
                    'y': element.get('y', 0),
                    'width': element.get('width', 10),
                    'height': element.get('height', 10),
                    'filled': element.get('filled', False),
                })

        return {
            'elements': rendered_elements,
            'invert': template.get('invert'),
            'clear': template.get('clear', True),
            'allow_empty_frame': bool(template.get('allow_empty_frame', False)),
        }

    def render_screen(self, screen: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Render a complete screen with data fetching.

        Args:
            screen: Screen configuration from database

        Returns:
            Rendered screen data ready for display, or None if error
        """
        try:
            # Fetch data sources
            data_sources = screen.get('data_sources', [])
            api_data = {}

            for source in data_sources:
                endpoint = source.get('endpoint')
                var_name = source.get('var_name')
                params = source.get('params')

                if endpoint and var_name:
                    self.fetch_data_source(endpoint, var_name, params)
                    api_data[var_name] = self._data_cache.get(var_name, {})

            # Check conditions
            conditions = screen.get('conditions')
            if conditions and not self.evaluate_condition(conditions, api_data):
                logger.debug(f"Screen '{screen.get('name')}' condition not met")
                return None

            # Render based on display type
            display_type = screen.get('display_type', 'led')

            if display_type == 'led':
                return self.render_led_screen(screen, api_data)
            elif display_type == 'vfd':
                return self.render_vfd_screen(screen, api_data)
            elif display_type == 'oled':
                return self.render_oled_screen(screen, api_data)
            else:
                logger.error(f"Unknown display type: {display_type}")
                return None

        except Exception as e:
            logger.error(f"Error rendering screen '{screen.get('name')}': {e}")
            return None

    def evaluate_condition(self, condition: Dict[str, Any], data: Dict[str, Any]) -> bool:
        """Evaluate a conditional expression.

        Simple condition evaluation supporting:
        - Comparisons: ==, !=, >, <, >=, <=
        - Logical operators: and, or

        Args:
            condition: Condition configuration
            data: Data for variable substitution

        Returns:
            True if condition is met, False otherwise
        """
        try:
            # Simple condition: {"var": "alerts.count", "op": ">", "value": 0}
            if 'var' in condition and 'op' in condition:
                var_path = condition['var']
                operator = condition['op']
                expected = condition['value']

                # Get actual value
                actual_str = self.substitute_variables(f"{{{var_path}}}", data)

                # Try to convert to number
                try:
                    actual = float(actual_str)
                    expected = float(expected)
                except (ValueError, TypeError):
                    actual = actual_str

                # Evaluate
                if operator == '==':
                    return actual == expected
                elif operator == '!=':
                    return actual != expected
                elif operator == '>':
                    return actual > expected
                elif operator == '<':
                    return actual < expected
                elif operator == '>=':
                    return actual >= expected
                elif operator == '<=':
                    return actual <= expected
                else:
                    logger.warning(f"Unknown operator: {operator}")
                    return True

            # Default to true if no condition or invalid
            return True

        except Exception as e:
            logger.error(f"Error evaluating condition: {e}")
            return True  # Fail open
