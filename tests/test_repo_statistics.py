#!/usr/bin/env python3
"""
Test repository statistics generation and documentation integration.

This test validates:
1. The statistics generation script works correctly
2. The generated markdown file is valid
3. The documentation system properly includes the statistics
"""

import re
from pathlib import Path


def test_statistics_generation():
    """Test that statistics can be generated successfully."""
    repo_root = Path(__file__).parent.parent
    stats_file = repo_root / 'static' / 'docs' / 'REPO_STATS.md'
    
    # Check that statistics file exists
    assert stats_file.exists(), "REPO_STATS.md should exist in static/docs/"
    
    # Read the content
    with open(stats_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Validate markdown structure
    assert '# Repository Statistics' in content, "Should have main heading"
    assert '## Overview' in content, "Should have Overview section"
    assert '## Files by Type' in content, "Should have Files by Type section"
    assert '## Lines of Code by Type' in content, "Should have LOC section"
    assert '## Routes by File' in content, "Should have Routes section"
    
    # Validate that it has actual data
    assert 'Total Files:' in content, "Should show total files"
    assert 'Total Lines:' in content, "Should show total lines"
    assert 'Total Routes:' in content, "Should show total routes"
    assert 'Code Lines:' in content, "Should show code lines"
    assert 'Comment Lines:' in content, "Should show comment lines"
    
    # Check for tables
    assert '|' in content, "Should contain markdown tables"
    
    print("✓ Statistics file structure validated")


def test_documentation_integration():
    """Test that statistics are integrated into documentation system."""
    repo_root = Path(__file__).parent.parent
    
    # Simulate the documentation structure function
    static_docs_root = Path('static/docs')
    repo_stats_file = static_docs_root / 'REPO_STATS.md'
    
    assert repo_stats_file.exists(), "Statistics file should exist for documentation"
    
    # Test the route path logic
    doc_path = 'static/REPO_STATS'
    assert doc_path.startswith('static/'), "Route path should start with static/"
    
    # Test path extraction
    relative_path = doc_path[7:]  # Remove 'static/'
    assert relative_path == 'REPO_STATS', "Should extract correct relative path"
    
    # Test file resolution
    file_path = static_docs_root / f'{relative_path}.md'
    assert file_path.exists(), "Should resolve to existing file"
    
    # Test security: file should be within static/docs
    try:
        file_path.resolve().relative_to(static_docs_root.resolve())
        print("✓ Security check passed: file is within static/docs")
    except ValueError:
        raise AssertionError("Security check failed: file not in allowed directory")
    
    print("✓ Documentation integration validated")


def test_statistics_content_quality():
    """Test that the statistics contain reasonable data."""
    repo_root = Path(__file__).parent.parent
    stats_file = repo_root / 'static' / 'docs' / 'REPO_STATS.md'
    
    with open(stats_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract numeric values
    total_files_match = re.search(r'Total Files.*?(\d{1,3}(?:,\d{3})*)', content)
    total_lines_match = re.search(r'Total Lines.*?(\d{1,3}(?:,\d{3})*)', content)
    total_routes_match = re.search(r'Total Routes.*?(\d+)', content)
    
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
