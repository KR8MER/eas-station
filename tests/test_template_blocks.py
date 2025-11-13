"""Tests to ensure template blocks are consistent across all templates.

This test prevents template block mismatches that can cause JavaScript and CSS
to silently fail to load.
"""

import os
import re
from pathlib import Path


def test_template_blocks_are_defined_in_base():
    """Verify that all template blocks used in child templates are defined in base.html."""
    
    # Get project root
    project_root = Path(__file__).resolve().parents[1]
    templates_dir = project_root / 'templates'
    base_template = templates_dir / 'base.html'
    
    if not base_template.exists():
        raise FileNotFoundError(f"base.html not found at {base_template}")
    
    # Read base.html and find all defined blocks
    with open(base_template, 'r') as f:
        base_content = f.read()
    
    # Pattern to match {% block blockname %}
    defined_blocks = set(re.findall(r'\{%\s*block\s+(\w+)\s*%\}', base_content))
    print(f"Blocks defined in base.html: {sorted(defined_blocks)}")
    
    # Find all template files
    template_files = []
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html') and file != 'base.html':
                template_files.append(Path(root) / file)
    
    print(f"Checking {len(template_files)} template files...")
    
    # Check each template file for block usage
    missing_blocks = {}
    for template_file in template_files:
        with open(template_file, 'r') as f:
            content = f.read()
        
        # Find all blocks used in this template
        used_blocks = set(re.findall(r'\{%\s*block\s+(\w+)\s*%\}', content))
        
        # Check if template extends base.html
        extends_base = 'extends "base.html"' in content or "extends 'base.html'" in content
        
        if extends_base and used_blocks:
            # Find blocks that are used but not defined in base
            undefined_blocks = used_blocks - defined_blocks
            if undefined_blocks:
                relative_path = template_file.relative_to(templates_dir)
                missing_blocks[str(relative_path)] = undefined_blocks
    
    # Report findings
    if missing_blocks:
        error_msg = "Templates using blocks not defined in base.html:\n"
        for template, blocks in sorted(missing_blocks.items()):
            error_msg += f"  {template}: {', '.join(sorted(blocks))}\n"
        error_msg += f"\nDefined blocks in base.html: {', '.join(sorted(defined_blocks))}\n"
        error_msg += "\nTo fix: Add the missing blocks to templates/base.html"
        raise AssertionError(error_msg)
    
    print("✓ All template blocks are properly defined in base.html")


def test_critical_blocks_exist_in_base():
    """Verify that critical blocks exist in base.html."""
    
    project_root = Path(__file__).resolve().parents[1]
    base_template = project_root / 'templates' / 'base.html'
    
    if not base_template.exists():
        raise FileNotFoundError(f"base.html not found at {base_template}")
    
    with open(base_template, 'r') as f:
        base_content = f.read()
    
    # Critical blocks that should always exist
    required_blocks = {
        'title': 'Page title',
        'content': 'Main page content',
        'extra_css': 'Additional CSS',
        'scripts': 'Page-specific JavaScript',
    }
    
    defined_blocks = set(re.findall(r'\{%\s*block\s+(\w+)\s*%\}', base_content))
    
    missing_required = set(required_blocks.keys()) - defined_blocks
    
    if missing_required:
        error_msg = "Critical blocks missing from base.html:\n"
        for block in sorted(missing_required):
            error_msg += f"  - {block}: {required_blocks[block]}\n"
        raise AssertionError(error_msg)
    
    print("✓ All critical blocks exist in base.html")


def test_js_block_consistency():
    """Verify JavaScript blocks are used consistently."""
    
    project_root = Path(__file__).resolve().parents[1]
    templates_dir = project_root / 'templates'
    
    # Count usage of different JS block names
    js_block_usage = {
        'extra_js': [],
        'scripts': [],
    }
    
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html') and file != 'base.html':
                template_file = Path(root) / file
                with open(template_file, 'r') as f:
                    content = f.read()
                
                # Check if extends base
                extends_base = 'extends "base.html"' in content or "extends 'base.html'" in content
                if not extends_base:
                    continue
                
                relative_path = str(template_file.relative_to(templates_dir))
                
                if '{% block extra_js %}' in content:
                    js_block_usage['extra_js'].append(relative_path)
                if '{% block scripts %}' in content:
                    js_block_usage['scripts'].append(relative_path)
    
    print(f"Templates using '{{% block extra_js %}}': {len(js_block_usage['extra_js'])}")
    print(f"Templates using '{{% block scripts %}}': {len(js_block_usage['scripts'])}")
    
    # Report usage
    if js_block_usage['scripts']:
        print(f"\n✓ All {len(js_block_usage['scripts'])} templates consistently use 'scripts' block")
    
    # Error if extra_js is still used (should be migrated)
    if js_block_usage['extra_js']:
        error_msg = "ERROR: Templates still using deprecated 'extra_js' block:\n"
        for template in sorted(js_block_usage['extra_js']):
            error_msg += f"  - {template}\n"
        error_msg += "\nAll templates should use '{% block scripts %}' for consistency."
        error_msg += "\nRun: sed -i 's/{% block extra_js %}/{% block scripts %}/g' <template_file>"
        raise AssertionError(error_msg)


if __name__ == "__main__":
    print("Running template block consistency tests...\n")
    
    try:
        test_critical_blocks_exist_in_base()
        test_template_blocks_are_defined_in_base()
        test_js_block_consistency()
        
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
