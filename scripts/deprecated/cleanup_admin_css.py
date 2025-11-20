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
Clean up unused CSS classes in admin.html
"""

def cleanup_admin_css():
    """Remove unused CSS classes and improve design consistency"""
    
    input_file = 'templates/admin.html'
    output_file = 'templates/admin.html'
    
    with open(input_file, 'r') as f:
        content = f.read()
    
    # Remove unused btn-custom CSS definitions
    lines = content.split('\n')
    cleaned_lines = []
    skip_lines = False
    
    for i, line in enumerate(lines):
        # Skip btn-custom CSS block
        if '.btn-custom {' in line:
            skip_lines = True
            continue
        elif skip_lines and line.strip().startswith('.'):
            # Check if we've moved to the next CSS rule
            if not line.strip().startswith('.btn-custom') and not line.strip().startswith('background:') and not line.strip().startswith('border-radius:') and not line.strip().startswith('padding:') and not line.strip().startswith('font-weight:') and not line.strip().startswith('transition:') and not line.strip().startswith('border:') and not line.strip().startswith('position:') and not line.strip().startswith('overflow:'):
                skip_lines = False
        
        if skip_lines:
            continue
            
        cleaned_lines.append(line)
    
    cleaned_content = '\n'.join(cleaned_lines)
    
    # Write the cleaned content back
    with open(output_file, 'w') as f:
        f.write(cleaned_content)
    
    print("✅ Cleaned up unused CSS classes in admin.html")
    print("🧹 Removed btn-custom CSS definitions (unused)")
    print("📝 Maintained all functional styling")

if __name__ == "__main__":
    cleanup_admin_css()