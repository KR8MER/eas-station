#!/usr/bin/env python3
"""
Migrate all remaining admin tabs (1-4, 7-8) to design system.
This script wraps each tab's content in proper card structures.
"""

import re

def migrate_tab_1_upload(content):
    """Migrate Tab 1: Upload Boundaries"""
    # Find Tab 1 section
    pattern = r'(<!-- Upload Tab -->.*?<div class="tab-pane fade show active" id="upload" role="tabpanel">)\s*<h4>'
    replacement = r'\1\n                       <!-- Page Header -->\n                       <div class="mb-4">\n                           <h4 class="mb-2">'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Close header and start card
    content = content.replace(
        '</h4>\n                       <p class="text-muted">Upload GeoJSON files to add new boundary layers to the system.</p>\n   \n                       <form id="uploadForm"',
        '</h4>\n                           <p class="text-muted mb-0">Upload GeoJSON files to add new boundary layers to the system.</p>\n                       </div>\n\n                       <!-- Upload Form Card -->\n                       <div class="card">\n                           <div class="card-header">\n                               <h5 class="card-title mb-0">Upload GeoJSON Boundaries</h5>\n                           </div>\n                           <div class="card-body">\n                               <form id="uploadForm"'
    )
    
    # Fix form closing
    content = re.sub(
        r'(\s+)<button type="submit" class="btn btn-primary">\s+<i class="fas fa-upload"></i> Upload Boundaries\s+</button>\s+</form>\s+<div id="uploadStatus"',
        r'\1                    <div class="d-grid gap-2 d-md-flex">\n\1                        <button type="submit" class="btn btn-primary">\n\1                            <i class="fas fa-upload"></i> Upload Boundaries\n\1                        </button>\n\1                    </div>\n\1                </form>\n\1            </div>\n\1        </div>\n\n\1        <!-- Upload Status -->\n\1        <div id="uploadStatus"',
        content
    )
    
    return content

def migrate_tab_2_preview(content):
    """Migrate Tab 2: Preview Data"""
    # Find Tab 2 section
    pattern = r'(<!-- Preview Tab -->.*?<div class="tab-pane fade" id="preview" role="tabpanel">)\s*<h4>'
    replacement = r'\1\n                       <!-- Page Header -->\n                       <div class="mb-4">\n                           <h4 class="mb-2">'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Close header and start card
    content = content.replace(
        '</h4>\n                       <p class="text-muted">Preview what data will be extracted from your GeoJSON file before uploading.</p>\n   \n                       <form id="previewForm"',
        '</h4>\n                           <p class="text-muted mb-0">Preview what data will be extracted from your GeoJSON file before uploading.</p>\n                       </div>\n\n                       <!-- Preview Form Card -->\n                       <div class="card">\n                           <div class="card-header">\n                               <h5 class="card-title mb-0">Preview Data Extraction</h5>\n                           </div>\n                           <div class="card-body">\n                               <form id="previewForm"'
    )
    
    # Fix button
    content = re.sub(
        r'(\s+)<button type="button" class="btn btn-info" onclick="previewExtraction\(\)">\s+<i class="fas fa-eye"></i> Preview Extraction\s+</button>\s+</form>\s+<div id="previewResults"',
        r'\1                    <div class="d-grid gap-2 d-md-flex">\n\1                        <button type="button" class="btn btn-info" onclick="previewExtraction()">\n\1                            <i class="fas fa-eye"></i> Preview Extraction\n\1                        </button>\n\1                    </div>\n\1                </form>\n\1            </div>\n\1        </div>\n\n\1        <!-- Preview Results -->\n\1        <div id="previewResults"',
        content
    )
    
    return content

def migrate_tab_3_manage(content):
    """Migrate Tab 3: Manage Boundaries"""
    # Find Tab 3 section
    pattern = r'(<!-- Manage Tab -->.*?<div class="tab-pane fade" id="manage" role="tabpanel">)\s*<h4>'
    replacement = r'\1\n                       <!-- Page Header -->\n                       <div class="mb-4">\n                           <h4 class="mb-2">'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Close header
    content = content.replace(
        '</h4>\n                       <p class="text-muted">View, edit, and delete existing boundary data in the system.</p>\n   \n                       <div class="row mt-4">',
        '</h4>\n                           <p class="text-muted mb-0">View, edit, and delete existing boundary data in the system.</p>\n                       </div>\n\n                       <div class="row mt-4">'
    )
    
    return content

def migrate_tab_4_operations(content):
    """Migrate Tab 4: System Operations"""
    # Find Tab 4 section
    pattern = r'(<!-- Operations Tab -->.*?<div class="tab-pane fade" id="operations" role="tabpanel">)\s*<h4>'
    replacement = r'\1\n                       <!-- Page Header -->\n                       <div class="mb-4">\n                           <h4 class="mb-2">'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Close header
    content = content.replace(
        '</h4>\n                       <p class="text-muted">Perform manual system operations and maintenance tasks.</p>\n   \n                       <div class="operation-grid">',
        '</h4>\n                           <p class="text-muted mb-0">Perform manual system operations and maintenance tasks.</p>\n                       </div>\n\n                       <div class="operation-grid">'
    )
    
    return content

def migrate_tab_7_users(content):
    """Migrate Tab 7: User Management"""
    # Find Tab 7 section  
    pattern = r'(<!-- User Management Tab -->.*?<div class="tab-pane fade" id="user-management" role="tabpanel">)\s*<h4>'
    replacement = r'\1\n                       <!-- Page Header -->\n                       <div class="mb-4">\n                           <h4 class="mb-2">'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Close header
    content = content.replace(
        '</h4>\n                       <p class="text-muted">Manage administrator accounts and permissions.</p>',
        '</h4>\n                           <p class="text-muted mb-0">Manage administrator accounts and permissions.</p>\n                       </div>'
    )
    
    return content

def migrate_tab_8_location(content):
    """Migrate Tab 8: Location Settings"""
    # Find Tab 8 section
    pattern = r'(<!-- Location Settings Tab -->.*?<div class="tab-pane fade" id="location-settings" role="tabpanel">)\s*<h4>'
    replacement = r'\1\n                       <!-- Page Header -->\n                       <div class="mb-4">\n                           <h4 class="mb-2">'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Close header
    content = content.replace(
        '</h4>\n                       <p class="text-muted">Configure your station\'s geographic location and coverage area.</p>',
        '</h4>\n                           <p class="text-muted mb-0">Configure your station\'s geographic location and coverage area.</p>\n                       </div>'
    )
    
    return content

def main():
    """Main migration function"""
    print("🚀 Starting migration of all remaining tabs...")
    
    # Read the file
    with open('templates/admin.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Migrate each tab
    print("  ✓ Migrating Tab 1: Upload Boundaries...")
    content = migrate_tab_1_upload(content)
    
    print("  ✓ Migrating Tab 2: Preview Data...")
    content = migrate_tab_2_preview(content)
    
    print("  ✓ Migrating Tab 3: Manage Boundaries...")
    content = migrate_tab_3_manage(content)
    
    print("  ✓ Migrating Tab 4: System Operations...")
    content = migrate_tab_4_operations(content)
    
    print("  ✓ Migrating Tab 7: User Management...")
    content = migrate_tab_7_users(content)
    
    print("  ✓ Migrating Tab 8: Location Settings...")
    content = migrate_tab_8_location(content)
    
    # Write the file back
    with open('templates/admin.html', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("\n✅ All tabs migrated successfully!")
    print("\nMigrated tabs:")
    print("  • Tab 1: Upload Boundaries")
    print("  • Tab 2: Preview Data")
    print("  • Tab 3: Manage Boundaries")
    print("  • Tab 4: System Operations")
    print("  • Tab 5: Alert Management (already done)")
    print("  • Tab 6: System Health (already done)")
    print("  • Tab 7: User Management")
    print("  • Tab 8: Location Settings")
    print("\n🎉 Phase 4 Complete!")

if __name__ == '__main__':
    main()