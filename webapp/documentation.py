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

"""Documentation viewer for serving markdown documentation through the web UI.

This module provides routes to serve all markdown documentation files from the docs/
directory through the web interface, ensuring users don't need to visit the repository
to access documentation.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, render_template, abort, make_response, redirect, url_for, request, jsonify
from markupsafe import escape, Markup
import mistune
from mistune.renderers.html import HTMLRenderer

logger = logging.getLogger(__name__)


class MermaidRenderer(HTMLRenderer):
    """Custom HTML renderer that handles Mermaid diagrams.
    
    Extends the default HTMLRenderer to intercept mermaid code blocks
    and render them as <div class="mermaid"> for client-side rendering.
    All other markdown elements use the parent's escaping logic.
    """
    
    def block_code(self, code, info=None):
        """Override block_code to handle mermaid diagrams specially.
        
        Args:
            code: The code block content
            info: Language identifier (e.g., 'python', 'bash', 'mermaid')
            
        Returns:
            HTML string with properly escaped content
        """
        if info and info.strip().lower() == 'mermaid':
            # Render mermaid blocks as divs with the mermaid class
            # Escape the code content so HTML entities are preserved for Mermaid.js
            escaped_code = escape(code)
            return f'<div class="mermaid">{escaped_code}</div>\n'
        
        # For all other code blocks, use parent's default rendering
        # This ensures consistent escaping and formatting
        return super().block_code(code, info)


def _markdown_to_html(content: str) -> str:
    """Convert markdown to HTML using mistune with support for Mermaid diagrams.
    
    Uses mistune v3 with a custom renderer to properly handle:
    - GitHub Flavored Markdown (tables, strikethrough, task lists)
    - Mermaid diagram blocks
    - Code blocks with syntax highlighting
    - All standard markdown features
    
    Security: All user content is properly escaped by mistune's default renderer.
    Only Mermaid diagram blocks receive special handling, with explicit escaping.
    
    Args:
        content: Raw markdown content from documentation files
        
    Returns:
        Safe HTML markup ready for rendering in templates
    """
    # Create markdown parser with custom renderer
    # escape=True ensures all content is properly escaped by default
    renderer = MermaidRenderer(escape=True)
    markdown = mistune.create_markdown(
        renderer=renderer,
        plugins=[
            'strikethrough',  # ~~text~~
            'table',          # GitHub-style tables
            'task_lists',     # - [ ] and - [x]
            'url',            # Auto-link URLs
        ]
    )
    
    # Convert markdown to HTML (all escaping handled by renderer)
    html = markdown(content)
    
    return Markup(html)


def _get_docs_structure() -> Dict[str, List[Dict[str, str]]]:
    """Get the documentation file structure organized by category."""
    docs_root = Path(__file__).parent.parent / 'docs'
    static_docs_root = Path(__file__).parent.parent / 'static' / 'docs'

    structure = {
        'Getting Started': [],
        'Architecture': [],
        'Development': [],
        'Hardware': [],
        'Guides': [],
        'Troubleshooting': [],
        'Security': [],
        'Reference': [],
        'Policies': [],
    }

    # Map directories to categories
    dir_mapping = {
        'guides': 'Guides',
        'architecture': 'Architecture',
        'development': 'Development',
        'reference': 'Reference',
        'policies': 'Policies',
        'roadmap': 'Reference',
        'process': 'Development',
        'frontend': 'Development',
        'hardware': 'Hardware',
        'audio': 'Guides',
        'installation': 'Getting Started',
        'maintenance': 'Guides',
        'security': 'Security',
        'troubleshooting': 'Troubleshooting',
    }

    # Add main docs
    if (docs_root / 'README.md').exists():
        structure['Getting Started'].append({
            'title': 'Documentation Index',
            'path': 'README',
            'url': '/docs/README'
        })

    # Add repository statistics from static (if exists)
    repo_stats_file = Path(__file__).parent.parent / 'static' / 'repo_stats.html'
    if repo_stats_file.exists():
        structure['Reference'].append({
            'title': 'Repository Statistics',
            'path': 'repo_stats',
            'url': '/repo-stats'
        })

    # Scan all markdown files
    for md_file in docs_root.rglob('*.md'):
        if md_file.name.startswith('.'):
            continue

        rel_path = md_file.relative_to(docs_root)
        parent_dir = rel_path.parent.name if rel_path.parent != Path('.') else ''

        # Determine category
        category = dir_mapping.get(parent_dir, 'Reference')

        # Create title from filename
        title = md_file.stem.replace('_', ' ').replace('-', ' ').title()
        if title == 'Readme':
            title = f'{parent_dir.title()} Overview' if parent_dir else 'Overview'

        # Create URL path
        url_path = str(rel_path.with_suffix('')).replace('\\', '/')

        # Policies are canonicalized to dedicated routes to avoid duplicate content
        if rel_path == Path('policies/TERMS_OF_USE.md'):
            url = '/terms'
        elif rel_path == Path('policies/PRIVACY_POLICY.md'):
            url = '/privacy'
        else:
            url = f'/docs/{url_path}'

        structure[category].append({
            'title': title,
            'path': str(rel_path),
            'url': url
        })

    # Sort each category
    for category in structure:
        structure[category].sort(key=lambda x: x['title'])

    # Remove empty categories
    structure = {k: v for k, v in structure.items() if v}

    return structure


_DOC_INDEX_CACHE: Dict[str, Any] = {'mtime': 0.0, 'entries': []}


def _build_doc_search_index(docs_root: Path) -> List[Dict[str, Any]]:
    """Scan every markdown file under docs_root and build an in-memory index.

    Cached and invalidated when any file's mtime changes. Each entry holds the
    full lowercased content so substring matching is straightforward, plus the
    original content for snippet generation.
    """
    if not docs_root.exists():
        return []

    md_files = sorted(docs_root.rglob('*.md'))
    latest_mtime = max((f.stat().st_mtime for f in md_files), default=0.0)

    if _DOC_INDEX_CACHE['entries'] and _DOC_INDEX_CACHE['mtime'] >= latest_mtime:
        return _DOC_INDEX_CACHE['entries']

    # Map directories to categories (mirrors _get_docs_structure)
    dir_mapping = {
        'guides': 'Guides',
        'architecture': 'Architecture',
        'development': 'Development',
        'reference': 'Reference',
        'policies': 'Policies',
        'roadmap': 'Reference',
        'process': 'Development',
        'frontend': 'Development',
        'hardware': 'Hardware',
        'audio': 'Guides',
        'installation': 'Getting Started',
        'maintenance': 'Guides',
        'security': 'Security',
        'troubleshooting': 'Troubleshooting',
    }

    entries: List[Dict[str, Any]] = []
    for md_file in md_files:
        if md_file.name.startswith('.'):
            continue
        try:
            content = md_file.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue

        rel_path = md_file.relative_to(docs_root)
        parent_dir = rel_path.parent.name if rel_path.parent != Path('.') else ''
        category = dir_mapping.get(parent_dir, 'Reference')

        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = md_file.stem.replace('_', ' ').replace('-', ' ').title()

        url_path = str(rel_path.with_suffix('')).replace('\\', '/')
        if rel_path == Path('policies/TERMS_OF_USE.md'):
            url = '/terms'
        elif rel_path == Path('policies/PRIVACY_POLICY.md'):
            url = '/privacy'
        else:
            url = f'/docs/{url_path}'

        entries.append({
            'title': title,
            'url': url,
            'category': category,
            'path': str(rel_path),
            'content': content,
            'content_lower': content.lower(),
            'title_lower': title.lower(),
        })

    _DOC_INDEX_CACHE['mtime'] = latest_mtime
    _DOC_INDEX_CACHE['entries'] = entries
    return entries


def _make_snippet(content: str, query: str, window: int = 80) -> str:
    """Return a ~160-char excerpt around the first case-insensitive match of query."""
    idx = content.lower().find(query.lower())
    if idx == -1:
        cleaned = re.sub(r'\s+', ' ', content[:200]).strip()
        return cleaned + ('…' if len(content) > 200 else '')
    start = max(0, idx - window)
    end = min(len(content), idx + len(query) + window)
    snippet = content[start:end]
    snippet = re.sub(r'\s+', ' ', snippet).strip()
    prefix = '…' if start > 0 else ''
    suffix = '…' if end < len(content) else ''
    return f'{prefix}{snippet}{suffix}'


def _search_docs(docs_root: Path, query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search the docs index for `query`. Title hits rank above content hits."""
    query = query.strip()
    if not query:
        return []

    q_lower = query.lower()
    results: List[Tuple[int, Dict[str, Any]]] = []

    for entry in _build_doc_search_index(docs_root):
        title_hit = q_lower in entry['title_lower']
        content_hit = q_lower in entry['content_lower']
        if not (title_hit or content_hit):
            continue

        # Score: title matches first, then by number of content occurrences.
        occurrences = entry['content_lower'].count(q_lower)
        score = (1000 if title_hit else 0) + occurrences

        results.append((score, {
            'title': entry['title'],
            'url': entry['url'],
            'category': entry['category'],
            'snippet': _make_snippet(entry['content'], query),
            'matches': occurrences,
        }))

    results.sort(key=lambda item: item[0], reverse=True)
    return [r[1] for r in results[:limit]]


def _render_no_cache(template_name: str, **context: Any):
    """Render a template with response headers that disable caching."""

    response = make_response(render_template(template_name, **context))
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def register_documentation_routes(app: Flask, logger_instance: Any) -> None:
    """Register documentation viewer routes."""

    global logger
    logger = logger_instance

    docs_root = Path(app.root_path) / 'docs'

    @app.route('/docs')
    def docs_index():
        """Documentation index page."""
        try:
            structure = _get_docs_structure()
            return _render_no_cache('docs_index.html', structure=structure)
        except Exception as exc:
            logger.error('Error rendering docs index: %s', exc)
            return _render_no_cache('error.html',
                                   error='Unable to load documentation index',
                                   details=str(exc)), 500

    @app.route('/docs/search')
    def docs_search():
        """Documentation search page."""
        try:
            structure = _get_docs_structure()
            return _render_no_cache('docs/search.html', structure=structure)
        except Exception as exc:
            logger.error('Error rendering docs search: %s', exc)
            return _render_no_cache('error.html',
                                   error='Unable to load documentation search',
                                   details=str(exc)), 500

    @app.route('/docs/search/api')
    def docs_search_api():
        """JSON search endpoint backing the /docs/search page."""
        query = (request.args.get('q') or '').strip()
        if not query:
            return jsonify({'query': '', 'results': [], 'count': 0})
        try:
            results = _search_docs(docs_root, query)
        except Exception as exc:
            logger.error('Error searching docs for %r: %s', query, exc)
            return jsonify({'query': query, 'results': [], 'count': 0,
                            'error': 'Search failed'}), 500
        return jsonify({'query': query, 'results': results, 'count': len(results)})

    @app.route('/docs/rbac/visual')
    def docs_rbac_visual():
        """Visual RBAC permission tree."""
        return _render_no_cache('docs/rbac_visual.html')

    @app.route('/docs/assets/<path:asset_path>')
    def serve_doc_asset(asset_path: str):
        """Serve static assets from docs/assets directory."""
        from flask import send_from_directory

        # Security: prevent directory traversal
        if '..' in asset_path or asset_path.startswith('/'):
            abort(404)

        assets_dir = docs_root / 'assets'
        asset_file = assets_dir / asset_path

        # Check if file exists and is within assets directory
        if not asset_file.exists() or not asset_file.is_file():
            logger.warning('Asset file not found: %s', asset_file)
            abort(404)

        try:
            asset_file.resolve().relative_to(assets_dir.resolve())
        except ValueError:
            logger.warning('Attempted access outside assets directory: %s', asset_file)
            abort(404)

        return send_from_directory(assets_dir, asset_path)

    @app.route('/docs/<path:doc_path>')
    def view_doc(doc_path: str):
        """View a specific documentation file."""
        normalized_path = doc_path.removesuffix('.md')

        if normalized_path == 'policies/TERMS_OF_USE':
            return redirect(url_for('terms_page'))

        if normalized_path == 'policies/PRIVACY_POLICY':
            return redirect(url_for('privacy_page'))

        # Redirect bare top-level names that have moved into subdirectories
        _doc_redirects = {
            'DIAGRAMS': 'reference/DIAGRAMS',
            'CHANGELOG': 'reference/CHANGELOG',
            'ABOUT': 'reference/ABOUT',
        }
        if normalized_path in _doc_redirects:
            return redirect(url_for('view_doc', doc_path=_doc_redirects[normalized_path]))

        # Security: prevent directory traversal
        if '..' in doc_path or doc_path.startswith('/'):
            abort(404)

        # Check if this is a static docs file
        if normalized_path.startswith('static/'):
            static_docs_root = Path(app.root_path) / 'static' / 'docs'
            # Remove 'static/' prefix
            relative_path = normalized_path[7:]  # len('static/') = 7
            file_path = static_docs_root / f'{relative_path}.md'
            root_for_security = static_docs_root
        else:
            # Regular docs file
            file_path = docs_root / f'{normalized_path}.md'
            root_for_security = docs_root

        # Check if file exists
        if not file_path.exists() or not file_path.is_file():
            logger.warning('Documentation file not found: %s', file_path)
            abort(404)

        # Check if file is within appropriate docs directory (security)
        try:
            file_path.resolve().relative_to(root_for_security.resolve())
        except ValueError:
            logger.warning('Attempted access outside docs directory: %s', file_path)
            abort(404)

        # Read and convert markdown
        try:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
            except UnicodeDecodeError:
                logger.error('Unable to decode file as UTF-8: %s', file_path)
                return _render_no_cache('error.html',
                                       error='Unable to read documentation file',
                                       details='File encoding error'), 500

            # Convert to HTML
            html_content = _markdown_to_html(markdown_content)

            # Get title from first H1 or filename
            title_match = re.search(r'^#\s+(.+)$', markdown_content, re.MULTILINE)
            title = title_match.group(1) if title_match else doc_path.replace('/', ' / ').title()

            # Get navigation structure
            structure = _get_docs_structure()

            return _render_no_cache('doc_viewer.html',
                                   title=title,
                                   content=html_content,
                                   doc_path=doc_path,
                                   structure=structure)

        except Exception as exc:
            logger.error('Error rendering documentation %s: %s', doc_path, exc)
            return _render_no_cache('error.html',
                                   error='Unable to load documentation',
                                   details=str(exc)), 500

    @app.route('/repo-stats')
    def repo_stats():
        """Serve the repository statistics HTML page."""
        from flask import send_from_directory
        
        static_dir = Path(app.root_path) / 'static'
        repo_stats_file = static_dir / 'repo_stats.html'
        
        if not repo_stats_file.exists():
            logger.warning('Repository statistics file not found: %s', repo_stats_file)
            return _render_no_cache('error.html',
                                   error='Repository statistics not available',
                                   details='Please run scripts/generate_repo_stats.py to generate statistics'), 404
        
        return send_from_directory(static_dir, 'repo_stats.html')


__all__ = ['register_documentation_routes']
