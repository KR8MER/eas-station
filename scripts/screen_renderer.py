"""Screen template renderer for LED and VFD displays.

This module provides rendering capabilities for custom display screens with
dynamic content populated from API endpoints.
"""

import logging
import re
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class ScreenRenderer:
    """Renders custom screen templates with dynamic API data."""

    def __init__(self, base_url: str = "http://localhost:5000"):
        """Initialize the screen renderer.

        Args:
            base_url: Base URL for API endpoint requests
        """
        self.base_url = base_url
        self._data_cache: Dict[str, Any] = {}
        self._cache_timestamp: Dict[str, datetime] = {}

    def fetch_data_source(self, endpoint: str, var_name: str, params: Optional[Dict] = None) -> None:
        """Fetch data from an API endpoint and cache it.

        Args:
            endpoint: API endpoint path (e.g., '/api/system_status')
            var_name: Variable name to store data under
            params: Optional query parameters
        """
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
        # Add built-in variables
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
