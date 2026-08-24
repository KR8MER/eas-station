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

"""Live REST API reference computed from the running app's URL map.

There was no backend API reference at all before this: ``docs/README.md``
pointed at ``docs/frontend/JAVASCRIPT_API.md`` and labelled it "REST API
reference", but that file documents frontend JS globals (``EASApi``,
``EASWebSocket``, ...), not the ~300 ``/api/*`` Flask routes, and its own
banner already says large parts of it are aspirational.

Rather than hand-write and immediately let stale a Markdown list of ~300
endpoints, this reads the exact routes Flask has registered -- the same
"trust the live app, not a regex over source text" approach
:mod:`app_utils.repo_stats` already uses for its own route count, after the
old regex-based counter there missed roughly half the app's routes by only
matching ``@app.route``/``@bp.route`` and not every named blueprint.

Per-route documentation comes from each view function's docstring (already
present on ~80% of ``/api/*`` handlers) via :func:`inspect.getdoc`, which
survives ``functools.wraps``. Per-route auth/permission requirements come
from an ``eas_auth_requirement`` attribute the permission decorators in
``app_core.auth.decorators`` / ``app_core.auth.roles`` stamp onto the
wrapped function -- also survives ``@wraps`` since it's set on the
*decorated* function object, not something ``@wraps`` would need to copy.
A route with neither decorator has no such attribute and is reported as
requiring no auth (accurate: nothing gates it).
"""

import inspect
import re
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


#: Google-style section headers recognized inside a route docstring, in the
#: order they should render. "Body"/"Query"/"Path" are this project's own
#: convention for a request's JSON body / query string / URL path params;
#: "Args"/"Params" are accepted too since ~100 existing route docstrings
#: already used one of those loosely for the same purpose before this
#: parser existed. "Returns" documents the response shape per status code.
SECTION_HEADERS: Tuple[str, ...] = ('Body', 'Query', 'Path', 'Args', 'Params', 'Returns')

_HEADER_RE = re.compile(r'^(' + '|'.join(SECTION_HEADERS) + r'):\s*$')


def _parse_docstring_sections(docstring: str) -> Tuple[str, Dict[str, str]]:
    """Split a docstring into its leading narrative and any structured sections.

    A section header is a line that, stripped, is exactly ``"<Name>:"`` for
    one of :data:`SECTION_HEADERS`. Everything from there until the next
    recognized header (or the end of the docstring) belongs to that
    section, dedented back to a common left margin. A docstring with no
    recognized headers returns its full text as the narrative and an empty
    sections dict -- this is the common case today (most routes only have
    a one-line summary), so it must be cheap and never raise.

    Returns:
        ``(narrative, sections)`` where ``sections`` preserves header order
        and omits any header whose body was empty.
    """
    lines = docstring.splitlines()
    narrative_lines: List[str] = []
    raw_sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for line in lines:
        match = _HEADER_RE.match(line.strip())
        if match:
            current = match.group(1)
            raw_sections.setdefault(current, [])
            continue
        if current is not None:
            raw_sections[current].append(line)
        else:
            narrative_lines.append(line)

    narrative = '\n'.join(narrative_lines).strip()
    sections: Dict[str, str] = {}
    for name in SECTION_HEADERS:
        if name not in raw_sections:
            continue
        body = textwrap.dedent('\n'.join(raw_sections[name])).strip()
        if body:
            sections[name] = body
    return narrative, sections


def _group_for_module(module: str) -> str:
    """Collapse a view function's ``__module__`` into a readable group.

    ``webapp.admin.audio_ingest.routes_alerts`` -> ``webapp.admin.audio_ingest``
    (drop the leaf file, keep the package) so routes split across many
    ``routes_*.py`` files in the same feature area land in one group instead
    of one row-of-one per file.
    """
    if not module:
        return 'unknown'
    parts = module.split('.')
    if len(parts) > 1:
        return '.'.join(parts[:-1])
    return module


def compute_api_reference(app) -> Dict[str, object]:
    """Build a reference of every ``/api/*`` route from the live URL map.

    Args:
        app: The running Flask app (its ``url_map`` and ``view_functions``
            are the source of truth).

    Returns:
        A JSON-serialisable dict: ``generated_at``, ``total`` route count,
        ``documented`` count (has a docstring), ``gated`` count (has an
        auth/permission requirement), and ``groups`` -- a
        group-name -> list-of-route-dicts mapping, each route dict carrying
        ``path``, ``endpoint``, ``methods``, ``summary`` (docstring's first
        line), ``docstring`` (full text), ``narrative`` (the docstring with
        any :data:`SECTION_HEADERS` blocks stripped out), ``sections`` (a
        header-name -> dedented-body dict for whichever of Body/Query/Path/
        Args/Params/Returns the docstring actually used), ``auth`` (the
        ``eas_auth_requirement`` dict or ``None``), and ``module``.
    """
    entries: List[dict] = []

    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static' or rule.endpoint.endswith('.static'):
            continue
        path = str(rule.rule)
        if not path.startswith('/api/'):
            continue

        view = app.view_functions.get(rule.endpoint)
        methods = sorted(
            m for m in (rule.methods or set()) if m not in ('HEAD', 'OPTIONS')
        )
        docstring = (inspect.getdoc(view) or '').strip() if view else ''
        summary = docstring.splitlines()[0].strip() if docstring else ''
        narrative, sections = _parse_docstring_sections(docstring) if docstring else ('', {})
        auth = getattr(view, 'eas_auth_requirement', None) if view else None
        module = getattr(view, '__module__', '') or ''

        entries.append({
            'path': path,
            'endpoint': rule.endpoint,
            'methods': methods,
            'summary': summary,
            'docstring': docstring,
            'narrative': narrative,
            'sections': sections,
            'auth': auth,
            'module': module,
            'group': _group_for_module(module),
        })

    entries.sort(key=lambda e: (e['path'], e['endpoint']))

    groups: Dict[str, List[dict]] = defaultdict(list)
    for entry in entries:
        groups[entry['group']].append(entry)

    return {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'total': len(entries),
        'documented': sum(1 for e in entries if e['summary']),
        'gated': sum(1 for e in entries if e['auth']),
        'groups': dict(sorted(groups.items())),
    }


__all__ = ['compute_api_reference']
