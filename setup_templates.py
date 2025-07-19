#!/usr/bin/env python3
"""
Template Setup Script
Ensures proper template directory structure for Flask application
"""

import os
import shutil
from pathlib import Path

def setup_template_directory():
    """Set up the templates directory structure"""
    print("?? Setting up NOAA Alerts template directory structure...")
    
    current_dir = os.getcwd()
    templates_dir = os.path.join(current_dir, 'templates')
    
    # Create templates directory if it doesn't exist
    if not os.path.exists(templates_dir):
        print(f"?? Creating templates directory: {templates_dir}")
        os.makedirs(templates_dir, exist_ok=True)
    else:
        print(f"? Templates directory already exists: {templates_dir}")
    
    # List of HTML files that should be in templates directory
    html_files = [
        'index.html',
        'admin.html', 
        'base.html'
    ]
    
    moved_files = []
    
    # Check if HTML files are in the current directory and move them
    for html_file in html_files:
        current_location = os.path.join(current_dir, html_file)
        template_location = os.path.join(templates_dir, html_file)
        
        if os.path.exists(current_location):
            if not os.path.exists(template_location):
                print(f"?? Moving {html_file} to templates directory...")
                shutil.move(current_location, template_location)
                moved_files.append(html_file)
            else:
                print(f"??  {html_file} exists in both locations. Keeping template version.")
        elif os.path.exists(template_location):
            print(f"? {html_file} already in templates directory")
        else:
            print(f"? {html_file} not found in current directory or templates")
    
    if moved_files:
        print(f"? Moved {len(moved_files)} files to templates directory: {moved_files}")
    
    # Set proper permissions
    try:
        os.chmod(templates_dir, 0o755)
        print(f"? Set templates directory permissions to 755")
        
        # Set permissions for HTML files
        for html_file in html_files:
            template_path = os.path.join(templates_dir, html_file)
            if os.path.exists(template_path):
                os.chmod(template_path, 0o644)
                print(f"? Set {html_file} permissions to 644")
                
    except Exception as e:
        print(f"??  Could not set permissions: {e}")
    
    return templates_dir

def verify_template_structure():
    """Verify the template directory structure"""
    print("\n?? Verifying template structure...")
    
    templates_dir = os.path.join(os.getcwd(), 'templates')
    
    if not os.path.exists(templates_dir):
        print("? Templates directory does not exist!")
        return False
    
    required_files = ['index.html', 'admin.html', 'base.html']
    missing_files = []
    
    for file in required_files:
        file_path = os.path.join(templates_dir, file)
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            print(f"? {file} exists ({file_size} bytes)")
        else:
            print(f"? {file} is missing")
            missing_files.append(file)
    
    if missing_files:
        print(f"??  Missing template files: {missing_files}")
        return False
    
    print("? All required template files are present")
    return True

def create_missing_templates():
    """Create basic template files if they're missing"""
    print("\n?? Creating missing template files...")
    
    templates_dir = os.path.join(os.getcwd(), 'templates')
    
    # Basic base.html template
    base_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}NOAA CAP Alerts System{% endblock %}</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="fas fa-satellite-dish"></i> NOAA CAP Alerts
            </a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="/">Map</a>
                <a class="nav-link" href="/admin">Admin</a>
                <a class="nav-link" href="/stats">Stats</a>
                <a class="nav-link" href="/logs">Logs</a>
            </div>
        </div>
    </nav>
    
    <div class="container-fluid mt-3">
        {% block content %}{% endblock %}
    </div>
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
</body>
</html>'''

    # Basic index.html template
    index_template = '''{% extends "base.html" %}

{% block title %}NOAA CAP Alerts - Map{% endblock %}

{% block content %}
<div class="row">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header">
                <h5><i class="fas fa-map"></i> Interactive Map</h5>
            </div>
            <div class="card-body">
                <div id="map" style="height: 500px; background: #f8f9fa;">
                    <div class="d-flex justify-content-center align-items-center h-100">
                        <div class="text-center">
                            <i class="fas fa-map fa-3x text-muted mb-3"></i>
                            <h5 class="text-muted">Map Loading...</h5>
                            <p class="text-muted">Interactive map will appear here</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-4">
        <div class="card">
            <div class="card-header">
                <h5><i class="fas fa-info-circle"></i> System Status</h5>
            </div>
            <div class="card-body">
                <div id="system-status">Loading...</div>
            </div>
        </div>
        
        <div class="card mt-3">
            <div class="card-header">
                <h5><i class="fas fa-exclamation-triangle"></i> Active Alerts</h5>
            </div>
            <div class="card-body">
                <div id="alerts-summary">Loading...</div>
            </div>
        </div>
    </div>
</div>
{% endblock %}'''

    # Basic admin.html template
    admin_template = '''{% extends "base.html" %}

{% block title %}NOAA CAP Alerts - Admin{% endblock %}

{% block content %}
<div class="row">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header">
                <h5><i class="fas fa-upload"></i> Upload Boundary Files</h5>
            </div>
            <div class="card-body">
                <form id="uploadForm" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label for="boundary_type" class="form-label">Boundary Type</label>
                        <select class="form-select" id="boundary_type" name="boundary_type" required>
                            <option value="">Select boundary type...</option>
                            <option value="fire">Fire District</option>
                            <option value="ems">EMS District</option>
                            <option value="electric">Electric District</option>
                            <option value="township">Township</option>
                            <option value="villages">Village</option>
                            <option value="telephone">Telephone Provider</option>
                            <option value="school">School District</option>
                            <option value="county">County Outline</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label for="file" class="form-label">GeoJSON File</label>
                        <input type="file" class="form-control" id="file" name="file" accept=".geojson,.json" required>
                    </div>
                    <button type="submit" class="btn btn-primary">Upload Boundaries</button>
                </form>
                <div id="upload-status" class="mt-3"></div>
            </div>
        </div>
    </div>
    
    <div class="col-md-4">
        <div class="card">
            <div class="card-header">
                <h5><i class="fas fa-cog"></i> System Operations</h5>
            </div>
            <div class="card-body">
                <div class="d-grid gap-2">
                    <button class="btn btn-success" onclick="triggerPoll()">
                        <i class="fas fa-download"></i> Trigger CAP Poll
                    </button>
                    <button class="btn btn-warning" onclick="clearExpired()">
                        <i class="fas fa-trash"></i> Clear Expired Alerts
                    </button>
                    <button class="btn btn-info" onclick="optimizeDb()">
                        <i class="fas fa-database"></i> Optimize Database
                    </button>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
async function triggerPoll() {
    try {
        const response = await fetch('/admin/trigger_poll', { method: 'POST' });
        const result = await response.json();
        alert(result.message || result.error);
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

async function clearExpired() {
    if (confirm('Clear all expired alerts?')) {
        try {
            const response = await fetch('/admin/clear_expired', { method: 'POST' });
            const result = await response.json();
            alert(result.message || result.error);
        } catch (error) {
            alert('Error: ' + error.message);
        }
    }
}

async function optimizeDb() {
    if (confirm('Run database optimization?')) {
        try {
            const response = await fetch('/admin/optimize_db', { method: 'POST' });
            const result = await response.json();
            alert(result.message || result.error);
        } catch (error) {
            alert('Error: ' + error.message);
        }
    }
}
</script>
{% endblock %}'''

    # Create missing template files
    templates_to_create = [
        ('base.html', base_template),
        ('index.html', index_template),
        ('admin.html', admin_template)
    ]
    
    created_files = []
    
    for filename, content in templates_to_create:
        file_path = os.path.join(templates_dir, filename)
        
        if not os.path.exists(file_path):
            print(f"?? Creating {filename}...")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            created_files.append(filename)
        else:
            print(f"? {filename} already exists")
    
    if created_files:
        print(f"? Created {len(created_files)} template files: {created_files}")
    
    return created_files

def main():
    """Main setup function"""
    print("?? NOAA Alerts Template Setup")
    print("=" * 40)
    
    # Setup template directory
    templates_dir = setup_template_directory()
    
    # Verify structure
    structure_ok = verify_template_structure()
    
    # Create missing templates if needed
    if not structure_ok:
        print("\n?? Some templates are missing. Creating basic templates...")
        created_files = create_missing_templates()
        
        # Verify again
        structure_ok = verify_template_structure()
    
    print("\n?? SETUP SUMMARY")
    print("=" * 20)
    
    if structure_ok:
        print("? Template setup completed successfully!")
        print(f"?? Templates directory: {templates_dir}")
        print("\n?? NEXT STEPS:")
        print("1. Start your Flask application")
        print("2. Visit the web interface to test template loading")
        print("3. Check application logs for any issues")
    else:
        print("? Template setup incomplete")
        print("Please check the errors above and run the setup again")
    
    print(f"\n?? Current directory: {os.getcwd()}")

if __name__ == '__main__':
    main()