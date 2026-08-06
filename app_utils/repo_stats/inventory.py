"""Route counting and the structural component inventory.

The old generator matched only ``@app.route`` and ``@bp.route``, so every
named blueprint (``@security_bp.route`` and roughly thirty siblings) was
invisible and the page under-reported the API by more than half. When a live
Flask app is available its URL map is the authoritative answer; the source
scan is a fallback for running outside an app context.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_ROUTE_DECORATOR = re.compile(r'@[A-Za-z_][A-Za-z0-9_]*\.route\(')
_DB_MODEL = re.compile(r'^class\s+\w+\s*\([^)]*db\.Model', re.MULTILINE)
_BLUEPRINT = re.compile(r'=\s*Blueprint\(')

#: Directories scanned by the source-scan fallback.
_ROUTE_DIRS = ('webapp', 'services', 'app_core', 'app_utils')


def routes_from_url_map(app) -> Optional[Dict[str, object]]:
    """Count registered routes from a live Flask URL map."""
    try:
        rules = list(app.url_map.iter_rules())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug('Unable to read url_map: %s', exc)
        return None

    by_module: Dict[str, int] = defaultdict(int)
    total = 0
    for rule in rules:
        if rule.endpoint == 'static' or rule.endpoint.endswith('.static'):
            continue
        total += 1
        view = app.view_functions.get(rule.endpoint)
        module = getattr(view, '__module__', None) or rule.endpoint.split('.')[0]
        by_module[module] += 1

    return {
        'total': total,
        'by_module': sorted(by_module.items(), key=lambda item: item[1], reverse=True),
        'source': 'url_map',
    }


def routes_from_source(root: Path) -> Dict[str, object]:
    """Fallback: count ``.route(`` decorators across the Python sources."""
    by_module: Dict[str, int] = {}
    total = 0

    candidates = []
    for directory in _ROUTE_DIRS:
        base = root / directory
        if base.exists():
            candidates.extend(base.rglob('*.py'))
    app_py = root / 'app.py'
    if app_py.exists():
        candidates.append(app_py)

    for py_file in candidates:
        try:
            content = py_file.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        count = len(_ROUTE_DECORATOR.findall(content))
        if count:
            by_module[str(py_file.relative_to(root))] = count
            total += count

    return {
        'total': total,
        'by_module': sorted(by_module.items(), key=lambda item: item[1], reverse=True),
        'source': 'source-scan',
    }


def count_components(root: Path, files: Iterable[Path]) -> Dict[str, int]:
    """Count the project's structural pieces (blueprints, models, tests...)."""
    counts = {
        'blueprints': 0,
        'models': 0,
        'migrations': 0,
        'templates': 0,
        'tests': 0,
        'systemd_units': 0,
        'scripts': 0,
    }

    for path in files:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        name = Path(rel).name

        if rel.startswith('templates/') and rel.endswith('.html'):
            counts['templates'] += 1
        elif rel.startswith('tests/') and name.startswith('test_'):
            counts['tests'] += 1
        elif rel.startswith('systemd/') and rel.endswith(('.service', '.target', '.timer')):
            counts['systemd_units'] += 1
        elif rel.startswith('scripts/') and rel.endswith(('.py', '.sh')):
            counts['scripts'] += 1
        elif rel.startswith('app_core/migrations/versions/') and rel.endswith('.py'):
            if name != '__init__.py':
                counts['migrations'] += 1

        if rel.endswith('.py') and rel.startswith(('app_core/', 'webapp/')):
            try:
                content = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            counts['models'] += len(_DB_MODEL.findall(content))
            counts['blueprints'] += len(_BLUEPRINT.findall(content))

    return counts


__all__ = ['count_components', 'routes_from_source', 'routes_from_url_map']
