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

from flask import Flask, render_template, abort, make_response, redirect, url_for
from markupsafe import escape, Markup

logger = logging.getLogger(__name__)


def _markdown_to_html(content: str) -> str:
    """Convert markdown to HTML with basic formatting.

    This is a simple markdown converter. For production, consider using
    markdown2 or mistune for more complete markdown support.
    """
    # Extract HTML anchor tags before escaping to preserve them
    anchor_tags = {}
    anchor_pattern = r'<a\s+name=["\']([^"\']+)["\']\s*></a>'

    def save_anchor(match):
        placeholder = f'%%%ANCHORTAG{len(anchor_tags)}%%%'
        anchor_tags[placeholder] = match.group(0)
        return placeholder

    content = re.sub(anchor_pattern, save_anchor, content)

    # Extract mermaid blocks before escaping to preserve syntax
    mermaid_blocks = {}
    # Support both Unix (\n) and Windows (\r\n) line endings after ```mermaid
    mermaid_pattern = r'```mermaid\r?\n(.*?)```'

    def save_mermaid(match):
        placeholder = f'%%%MERMAIDBLOCK{len(mermaid_blocks)}%%%'
        mermaid_blocks[placeholder] = match.group(1)
        return placeholder

    content = re.sub(mermaid_pattern, save_mermaid, content, flags=re.DOTALL)

    # Extract images and links before escaping to preserve them from emphasis parsing
    images_and_links = {}
    
    # Extract images first (they have ! before [)
    def save_image(match):
        placeholder = f'%%%IMAGE{len(images_and_links)}%%%'
        images_and_links[placeholder] = f'![{match.group(1)}]({match.group(2)})'
        return placeholder
    
    content = re.sub(r'!\[([^\]]+)\]\(([^)]+)\)', save_image, content)
    
    # Extract links
    def save_link(match):
        placeholder = f'%%%LINK{len(images_and_links)}%%%'
        images_and_links[placeholder] = f'[{match.group(1)}]({match.group(2)})'
        return placeholder
    
    content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', save_link, content)

    # Escape HTML first
    html = escape(content)

    # Convert headers
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^##### (.+)$', r'<h5>\1</h5>', str(html), flags=re.MULTILINE)

    # Convert bold and italic (now safe from link URLs)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', str(html))
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', str(html))
    html = re.sub(r'__(.+?)__', r'<strong>\1</strong>', str(html))
    html = re.sub(r'_(.+?)_', r'<em>\1</em>', str(html))

    # Convert code blocks (triple backticks)
    html = re.sub(
        r'```(\w+)?\n(.*?)```',
        lambda m: f'<pre><code class="language-{m.group(1) or "text"}">{m.group(2)}</code></pre>',
        str(html),
        flags=re.DOTALL
    )

    # Convert inline code
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', str(html))

    # Restore and convert images and links
    for placeholder, markdown in images_and_links.items():
        escaped_placeholder = escape(placeholder)
        if markdown.startswith('!'):
            # It's an image: ![alt](url)
            match = re.match(r'!\[([^\]]+)\]\(([^)]+)\)', markdown)
            if match:
                alt_text = escape(match.group(1))
                url = escape(match.group(2))
                html = str(html).replace(str(escaped_placeholder), f'<img alt="{alt_text}" src="{url}" />')
        else:
            # It's a link: [text](url)
            match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', markdown)
            if match:
                link_text = match.group(1)  # Already escaped during escape(content)
                url = escape(match.group(2))
                html = str(html).replace(str(escaped_placeholder), f'<a href="{url}">{link_text}</a>')

    # Convert unordered lists
    lines = str(html).split('\n')
    in_list = False
    result = []
    for line in lines:
        if line.strip().startswith('- ') or line.strip().startswith('* '):
            if not in_list:
                result.append('<ul>')
                in_list = True
            item = line.strip()[2:]
            result.append(f'<li>{item}</li>')
        else:
            if in_list:
                result.append('</ul>')
                in_list = False
            result.append(line)
    if in_list:
        result.append('</ul>')
    html = '\n'.join(result)

    # Convert ordered lists
    lines = str(html).split('\n')
    in_list = False
    result = []
    for line in lines:
        if re.match(r'^\d+\.\s+', line.strip()):
            if not in_list:
                result.append('<ol>')
                in_list = True
            item = re.sub(r'^\d+\.\s+', '', line.strip())
            result.append(f'<li>{item}</li>')
        else:
            if in_list:
                result.append('</ol>')
                in_list = False
            result.append(line)
    if in_list:
        result.append('</ol>')
    html = '\n'.join(result)

    # Convert blockquotes
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', str(html), flags=re.MULTILINE)

    # Convert horizontal rules (but not table separators)
    html = re.sub(r'^---$', r'<hr>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^\*\*\*$', r'<hr>', str(html), flags=re.MULTILINE)

    # Convert tables
    lines = str(html).split('\n')
    result = []
    in_table = False
    for i, line in enumerate(lines):
        # Check if this is a table row (has pipes)
        if '|' in line and line.strip().startswith('|'):
            # Check if next line is separator (---|---|)
            is_header = False
            if i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i + 1]):
                is_header = True
                if not in_table:
                    result.append('<table class="table table-striped table-bordered">')
                    in_table = True
                # Process header row
                cells = [cell.strip() for cell in line.split('|')[1:-1]]
                result.append('<thead><tr>')
                for cell in cells:
                    result.append(f'<th>{cell}</th>')
                result.append('</tr></thead><tbody>')
                continue
            elif in_table and re.match(r'^\|[\s\-:|]+\|$', line):
                # Skip separator row
                continue
            elif in_table:
                # Process data row
                cells = [cell.strip() for cell in line.split('|')[1:-1]]
                result.append('<tr>')
                for cell in cells:
                    result.append(f'<td>{cell}</td>')
                result.append('</tr>')
                continue
        else:
            # Not a table line
            if in_table:
                result.append('</tbody></table>')
                in_table = False
            result.append(line)

    if in_table:
        result.append('</tbody></table>')

    html = '\n'.join(result)

    # Convert line breaks to paragraphs
    paragraphs = html.split('\n\n')
    html = ''.join(f'<p>{p}</p>' if not p.strip().startswith('<') else p for p in paragraphs)

    # Restore mermaid blocks as div elements with proper escaping
    for placeholder, mermaid_code in mermaid_blocks.items():
        # The placeholder was already escaped during the escape(content) step
        escaped_placeholder = escape(placeholder)
        # Escape the mermaid code so HTML tags in diagrams (like <br/>) don't get parsed
        # Mermaid.js will read the text content and parse it correctly
        escaped_mermaid = escape(mermaid_code)
        mermaid_div = f'<div class="mermaid">{escaped_mermaid}</div>'
        # Replace both plain and paragraph-wrapped placeholders
        html = str(html).replace(str(escaped_placeholder), mermaid_div)
        html = str(html).replace(f'<p>{escaped_placeholder}</p>', mermaid_div)

    # Restore HTML anchor tags
    for placeholder, anchor_tag in anchor_tags.items():
        # The placeholder was already escaped during the escape(content) step
        escaped_placeholder = escape(placeholder)
        # Replace the placeholder with the original anchor tag
        html = str(html).replace(str(escaped_placeholder), anchor_tag)

    return Markup(html)


def _get_docs_structure() -> Dict[str, List[Dict[str, str]]]:
    """Get the documentation file structure organized by category."""
    docs_root = Path(__file__).parent.parent / 'docs'
    static_docs_root = Path(__file__).parent.parent / 'static' / 'docs'

    structure = {
        'Getting Started': [],
        'Operations': [],
        'Architecture': [],
        'Development': [],
        'Reference': [],
        'Guides': [],
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
    }

    # Add main docs
    if (docs_root / 'README.md').exists():
        structure['Getting Started'].append({
            'title': 'Documentation Index',
            'path': 'README',
            'url': '/docs/README'
        })

    # Add repository statistics from static/docs (if exists)
    repo_stats_file = static_docs_root / 'REPO_STATS.md'
    if repo_stats_file.exists():
        structure['Reference'].append({
            'title': 'Repository Statistics',
            'path': 'static/REPO_STATS',
            'url': '/docs/static/REPO_STATS'
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

        # Security: prevent directory traversal
        if '..' in doc_path or doc_path.startswith('/'):
            abort(404)

        # Check if this is a static docs file
        if doc_path.startswith('static/'):
            static_docs_root = Path(app.root_path) / 'static' / 'docs'
            # Remove 'static/' prefix
            relative_path = doc_path[7:]  # len('static/') = 7
            file_path = static_docs_root / f'{relative_path}.md'
            root_for_security = static_docs_root
        else:
            # Regular docs file
            file_path = docs_root / f'{doc_path}.md'
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


__all__ = ['register_documentation_routes']
