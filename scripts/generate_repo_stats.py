#!/usr/bin/env python3
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

"""
Generate repository statistics and save to markdown file.

This script analyzes the repository structure and generates statistics including:
- Total files count by type
- Routes count
- Lines of code
- Directory structure metrics
"""

import os
import re
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Tuple


def count_lines_of_code(file_path: Path) -> Tuple[int, int, int]:
    """
    Count lines of code in a file.
    
    Returns:
        Tuple of (total_lines, code_lines, comment_lines)
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        code_lines = 0
        comment_lines = 0
        in_multiline_comment = False
        
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines
            if not stripped:
                continue
            
            # Python/Shell comments
            if file_path.suffix in ['.py', '.sh']:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    in_multiline_comment = not in_multiline_comment
                    comment_lines += 1
                elif in_multiline_comment:
                    comment_lines += 1
                elif stripped.startswith('#'):
                    comment_lines += 1
                else:
                    code_lines += 1
            # JavaScript/CSS comments
            elif file_path.suffix in ['.js', '.css']:
                if '/*' in stripped:
                    in_multiline_comment = True
                    comment_lines += 1
                elif '*/' in stripped:
                    in_multiline_comment = False
                    comment_lines += 1
                elif in_multiline_comment:
                    comment_lines += 1
                elif stripped.startswith('//'):
                    comment_lines += 1
                else:
                    code_lines += 1
            # HTML/XML comments
            elif file_path.suffix in ['.html', '.xml', '.svg']:
                if '<!--' in stripped or '-->' in stripped:
                    comment_lines += 1
                else:
                    code_lines += 1
            # YAML comments
            elif file_path.suffix in ['.yml', '.yaml']:
                if stripped.startswith('#'):
                    comment_lines += 1
                else:
                    code_lines += 1
            # Dockerfile comments
            elif file_path.name.startswith('Dockerfile'):
                if stripped.startswith('#'):
                    comment_lines += 1
                else:
                    code_lines += 1
            else:
                code_lines += 1
        
        return total_lines, code_lines, comment_lines
    except Exception:
        return 0, 0, 0


def count_routes(repo_root: Path) -> Dict[str, int]:
    """
    Count Flask routes in the repository.
    
    Returns:
        Dict with route counts by file
    """
    routes = defaultdict(int)
    webapp_dir = repo_root / 'webapp'
    
    if not webapp_dir.exists():
        return routes
    
    route_pattern = re.compile(r'@(?:app|bp)\.route\(["\']([^"\']+)["\']')
    
    for py_file in webapp_dir.rglob('*.py'):
        try:
            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                matches = route_pattern.findall(content)
                if matches:
                    rel_path = py_file.relative_to(repo_root)
                    routes[str(rel_path)] = len(matches)
        except Exception:
            continue
    
    # Also check app.py in root
    app_py = repo_root / 'app.py'
    if app_py.exists():
        try:
            with open(app_py, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                matches = route_pattern.findall(content)
                if matches:
                    routes['app.py'] = len(matches)
        except Exception:
            pass
    
    return routes


def analyze_repository(repo_root: Path) -> Dict:
    """
    Analyze repository structure and gather statistics.
    
    Returns:
        Dict containing all statistics
    """
    stats = {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'files_by_type': defaultdict(int),
        'lines_by_type': defaultdict(lambda: {'total': 0, 'code': 0, 'comments': 0}),
        'total_files': 0,
        'total_lines': 0,
        'total_code_lines': 0,
        'total_comment_lines': 0,
        'routes': {},
        'directories': set(),
    }
    
    # Extensions to track
    extensions = {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.html': 'HTML',
        '.css': 'CSS',
        '.yml': 'YAML',
        '.yaml': 'YAML',
        '.md': 'Markdown',
        '.sh': 'Shell',
        '.json': 'JSON',
        '.sql': 'SQL',
        '.txt': 'Text',
        '.xml': 'XML',
        '.svg': 'SVG',
    }
    
    # Directories to exclude
    exclude_dirs = {
        '.git', '__pycache__', 'node_modules', '.pytest_cache',
        'venv', 'env', '.venv', 'dist', 'build', '.egg-info'
    }
    
    # Count routes
    stats['routes'] = count_routes(repo_root)
    
    # Walk through repository
    for root, dirs, files in os.walk(repo_root):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        root_path = Path(root)
        rel_dir = root_path.relative_to(repo_root)
        stats['directories'].add(str(rel_dir))
        
        for file in files:
            file_path = root_path / file
            
            # Skip files in excluded directories
            if any(excluded in file_path.parts for excluded in exclude_dirs):
                continue
            
            stats['total_files'] += 1
            
            # Get extension
            ext = file_path.suffix.lower()
            
            # Special handling for Dockerfile
            if file.startswith('Dockerfile'):
                ext = 'Dockerfile'
            
            # Count by extension
            file_type = extensions.get(ext, 'Other')
            stats['files_by_type'][file_type] += 1
            
            # Count lines for tracked extensions
            if ext in extensions or file.startswith('Dockerfile'):
                total, code, comments = count_lines_of_code(file_path)
                stats['lines_by_type'][file_type]['total'] += total
                stats['lines_by_type'][file_type]['code'] += code
                stats['lines_by_type'][file_type]['comments'] += comments
                stats['total_lines'] += total
                stats['total_code_lines'] += code
                stats['total_comment_lines'] += comments
    
    return stats


def generate_markdown(stats: Dict) -> str:
    """
    Generate markdown content from statistics.
    
    Returns:
        Markdown formatted string
    """
    md = []
    
    md.append('# Repository Statistics')
    md.append('')
    md.append(f'**Generated:** {stats["timestamp"]}')
    md.append('')
    
    # Overview
    md.append('## Overview')
    md.append('')
    md.append(f'- **Total Files:** {stats["total_files"]:,}')
    md.append(f'- **Total Directories:** {len(stats["directories"]):,}')
    md.append(f'- **Total Lines:** {stats["total_lines"]:,}')
    md.append(f'- **Code Lines:** {stats["total_code_lines"]:,}')
    md.append(f'- **Comment Lines:** {stats["total_comment_lines"]:,}')
    md.append(f'- **Total Routes:** {sum(stats["routes"].values())}')
    md.append('')
    
    # Files by type
    md.append('## Files by Type')
    md.append('')
    md.append('| File Type | Count |')
    md.append('|-----------|-------|')
    
    sorted_types = sorted(stats['files_by_type'].items(), key=lambda x: x[1], reverse=True)
    for file_type, count in sorted_types:
        md.append(f'| {file_type} | {count:,} |')
    md.append('')
    
    # Lines of code by type
    md.append('## Lines of Code by Type')
    md.append('')
    md.append('| Language | Total Lines | Code Lines | Comment Lines |')
    md.append('|----------|-------------|------------|---------------|')
    
    sorted_lines = sorted(
        stats['lines_by_type'].items(),
        key=lambda x: x[1]['total'],
        reverse=True
    )
    for lang, counts in sorted_lines:
        if counts['total'] > 0:
            md.append(
                f'| {lang} | {counts["total"]:,} | {counts["code"]:,} | {counts["comments"]:,} |'
            )
    md.append('')
    
    # Routes
    if stats['routes']:
        md.append('## Routes by File')
        md.append('')
        md.append('| File | Route Count |')
        md.append('|------|-------------|')
        
        sorted_routes = sorted(stats['routes'].items(), key=lambda x: x[1], reverse=True)
        for file, count in sorted_routes:
            md.append(f'| {file} | {count} |')
        md.append('')
    
    # Code distribution visualization
    md.append('## Code Distribution')
    md.append('')
    md.append('### Top Languages by Lines of Code')
    md.append('')
    
    # Create a simple bar chart using markdown
    top_langs = sorted_lines[:5]  # Top 5 languages
    if top_langs:
        max_lines = max(counts['code'] for _, counts in top_langs)
        for lang, counts in top_langs:
            if counts['code'] > 0:
                bar_length = int((counts['code'] / max_lines) * 50)
                bar = '█' * bar_length
                md.append(f'**{lang}:** {counts["code"]:,} lines  ')
                md.append(f'`{bar}`')
                md.append('')
    
    return '\n'.join(md)


def main():
    """Main function to generate and save repository statistics."""
    # Determine repository root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    
    print('Analyzing repository...')
    stats = analyze_repository(repo_root)
    
    print('Generating markdown...')
    markdown_content = generate_markdown(stats)
    
    # Save to static/docs directory for frontend access
    output_path = repo_root / 'static' / 'docs' / 'REPO_STATS.md'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    print(f'Statistics saved to: {output_path}')
    print(f'Total files: {stats["total_files"]:,}')
    print(f'Total lines: {stats["total_lines"]:,}')
    print(f'Total routes: {sum(stats["routes"].values())}')


if __name__ == '__main__':
    main()
