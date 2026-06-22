#!/usr/bin/env python3
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

"""
Test repository statistics generation and documentation integration.

This test validates:
1. The statistics generation script works correctly
2. The generated HTML file with Chart.js is valid
3. The documentation system properly includes the statistics
"""

import re
from pathlib import Path


def test_statistics_generation():
    """Test that statistics can be generated successfully."""
    repo_root = Path(__file__).parent.parent
    stats_file = repo_root / 'static' / 'repo_stats.html'
    
    # Check that statistics file exists
    assert stats_file.exists(), "repo_stats.html should exist in static/"
    
    # Read the content
    with open(stats_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Validate HTML structure
    assert '<!DOCTYPE html>' in content, "Should be valid HTML"
    assert 'Repository Statistics' in content, "Should have main heading"
    assert 'Chart.js' in content or 'chart.js' in content, "Should include Chart.js"
    assert 'Quick Stats' in content or 'Total Files' in content, "Should have stats section"
    assert 'Files by Type' in content, "Should have Files by Type section"
    assert 'Lines of Code' in content, "Should have LOC section"
    assert 'API Routes' in content or 'Routes by Module' in content, "Should have Routes section"
    
    # Validate that it has actual data
    assert 'Total Files' in content, "Should show total files"
    assert 'Total Lines' in content, "Should show total lines"
    assert 'Code Lines' in content, "Should show code lines"
    assert 'Comments' in content, "Should show comment lines"
    
    # Check for Chart.js canvases
    assert 'canvas' in content, "Should contain canvas elements for charts"
    assert 'codeCompositionChart' in content, "Should have code composition chart"
    assert 'filesByTypeChart' in content, "Should have files by type chart"
    assert 'linesByLanguageChart' in content, "Should have lines by language chart"
    
    print("✓ Statistics file structure validated")


def test_documentation_integration():
    """Test that statistics are integrated into documentation system."""
    repo_root = Path(__file__).parent.parent
    
    # Test the new HTML file location
    static_dir = Path('static')
    repo_stats_file = static_dir / 'repo_stats.html'
    
    assert repo_stats_file.exists(), "Statistics HTML file should exist in static/"
    
    # Test file resolution
    file_path = static_dir / 'repo_stats.html'
    assert file_path.exists(), "Should resolve to existing HTML file"
    
    # Test security: file should be within static directory
    try:
        file_path.resolve().relative_to(static_dir.resolve())
        print("✓ Security check passed: file is within static/")
    except ValueError:
        raise AssertionError("Security check failed: file not in allowed directory")
    
    print("✓ Documentation integration validated")


def test_statistics_content_quality():
    """Test that the statistics contain reasonable data."""
    repo_root = Path(__file__).parent.parent
    stats_file = repo_root / 'static' / 'repo_stats.html'
    
    with open(stats_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract numeric values from HTML content
    total_files_match = re.search(r'<div class="value">(\d{1,3}(?:,\d{3})*)</div>\s*<div class="label">Total Files</div>', content, re.DOTALL)
    total_lines_match = re.search(r'<div class="value">(\d{1,3}(?:,\d{3})*)</div>\s*<div class="label">Total Lines</div>', content, re.DOTALL)
    total_routes_match = re.search(r'<div class="value">(\d+)</div>\s*<div class="label">API Routes</div>', content, re.DOTALL)
    
    assert total_files_match, "Should find total files count"
    assert total_lines_match, "Should find total lines count"
    assert total_routes_match, "Should find total routes count"
    
    # Parse numbers (remove commas)
    total_files = int(total_files_match.group(1).replace(',', ''))
    total_lines = int(total_lines_match.group(1).replace(',', ''))
    total_routes = int(total_routes_match.group(1))
    
    # Sanity checks
    assert total_files > 100, f"Expected > 100 files, got {total_files}"
    assert total_lines > 10000, f"Expected > 10k lines, got {total_lines}"
    assert total_routes > 50, f"Expected > 50 routes, got {total_routes}"
    
    print(f"✓ Statistics quality validated:")
    print(f"  Files: {total_files:,}")
    print(f"  Lines: {total_lines:,}")
    print(f"  Routes: {total_routes}")


def test_workflow_file():
    """Test that the GitHub Actions workflow is properly configured."""
    repo_root = Path(__file__).parent.parent
    workflow_file = repo_root / '.github' / 'workflows' / 'update-repo-stats.yml'
    
    assert workflow_file.exists(), "Workflow file should exist"
    
    with open(workflow_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check key components
    assert 'name: Update Repository Statistics' in content, "Should have correct name"
    assert 'push:' in content, "Should trigger on push"
    assert 'branches:' in content, "Should specify branches"
    assert 'main' in content, "Should include main branch"
    assert 'python scripts/generate_repo_stats.py' in content, "Should run stats script"
    assert 'static/repo_stats.html' in content, "Should track the HTML file"
    assert 'git commit' in content, "Should commit changes"
    assert '[skip ci]' in content, "Should skip CI to prevent loops"
    assert 'permissions:' in content, "Should have explicit permissions"
    assert 'contents: write' in content, "Should have write permission"
    
    print("✓ GitHub Actions workflow validated")


if __name__ == '__main__':
    print("Running repository statistics tests...\n")
    
    try:
        test_statistics_generation()
        test_documentation_integration()
        test_statistics_content_quality()
        test_workflow_file()
        
        print("\n" + "="*50)
        print("All tests passed! ✓")
        print("="*50)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        raise
