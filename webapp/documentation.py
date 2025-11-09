"""Documentation viewer for serving markdown documentation through the web UI.

This module provides routes to serve all markdown documentation files from the docs/
directory through the web interface, ensuring users don't need to visit the repository
to access documentation.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, render_template, abort
from markupsafe import escape, Markup

logger = logging.getLogger(__name__)


def _markdown_to_html(content: str) -> str:
    """Convert markdown to HTML with basic formatting.

    This is a simple markdown converter. For production, consider using
    markdown2 or mistune for more complete markdown support.
    """
    # Escape HTML first
    html = escape(content)

    # Convert headers
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', str(html), flags=re.MULTILINE)
    html = re.sub(r'^##### (.+)$', r'<h5>\1</h5>', str(html), flags=re.MULTILINE)

    # Convert bold and italic
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

    # Convert links
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', str(html))

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

    return Markup(html)


def _get_docs_structure() -> Dict[str, List[Dict[str, str]]]:
    """Get the documentation file structure organized by category."""
    docs_root = Path(__file__).parent.parent / 'docs'

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

        structure[category].append({
            'title': title,
            'path': str(rel_path),
            'url': f'/docs/{url_path}'
        })

    # Sort each category
    for category in structure:
        structure[category].sort(key=lambda x: x['title'])

    # Remove empty categories
    structure = {k: v for k, v in structure.items() if v}

    return structure


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
            return render_template('docs_index.html', structure=structure)
        except Exception as exc:
            logger.error('Error rendering docs index: %s', exc)
            return render_template('error.html',
                                   error='Unable to load documentation index',
                                   details=str(exc)), 500

    @app.route('/docs/<path:doc_path>')
    def view_doc(doc_path: str):
        """View a specific documentation file."""
        # Security: prevent directory traversal
        if '..' in doc_path or doc_path.startswith('/'):
            abort(404)

        # Construct file path
        file_path = docs_root / f'{doc_path}.md'

        # Check if file exists
        if not file_path.exists() or not file_path.is_file():
            logger.warning('Documentation file not found: %s', file_path)
            abort(404)

        # Check if file is within docs directory (security)
        try:
            file_path.resolve().relative_to(docs_root.resolve())
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
                return render_template('error.html',
                                       error='Unable to read documentation file',
                                       details='File encoding error'), 500

            # Convert to HTML
            html_content = _markdown_to_html(markdown_content)

            # Get title from first H1 or filename
            title_match = re.search(r'^#\s+(.+)$', markdown_content, re.MULTILINE)
            title = title_match.group(1) if title_match else doc_path.replace('/', ' / ').title()

            # Get navigation structure
            structure = _get_docs_structure()

            return render_template('doc_viewer.html',
                                   title=title,
                                   content=html_content,
                                   doc_path=doc_path,
                                   structure=structure)

        except Exception as exc:
            logger.error('Error rendering documentation %s: %s', doc_path, exc)
            return render_template('error.html',
                                   error='Unable to load documentation',
                                   details=str(exc)), 500


__all__ = ['register_documentation_routes']
