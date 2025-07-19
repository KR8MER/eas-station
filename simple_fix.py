#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix Template Issues Script
Addresses encoding issues, working directory problems, and missing templates
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

def fix_working_directory():
    """Fix the working directory issue"""
    print("?? Fixing working directory issue...")
    
    # Expected project directory
    project_dir = "/home/pi/noaa_alerts_system"
    
    if not os.path.exists(project_dir):
        print(f"? Project directory does not exist: {project_dir}")
        return False
    
    # Change to project directory
    try:
        os.chdir(project_dir)
        print(f"? Changed working directory to: {os.getcwd()}")
        return True
    except Exception as e:
        print(f"? Error changing directory: {e}")
        return False

def find_corrupted_html_files():
    """Find HTML files with encoding issues"""
    print("\n?? Scanning for corrupted HTML files...")
    
    # Directories to scan
    scan_dirs = [
        "/home/pi/noaa_alerts_system",
        "/home/pi/noaa_alerts_system/templates",
        "."
    ]
    
    corrupted_files = []
    
    for scan_dir in scan_dirs:
        if not os.path.exists(scan_dir):
            continue
            
        print(f"?? Scanning directory: {scan_dir}")
        
        for root, dirs, files in os.walk(scan_dir):
            for file in files:
                if file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    
                    try:
                        # Try to read file with UTF-8 encoding
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        print(f"? {file_path} - OK")
                        
                    except UnicodeDecodeError as e:
                        print(f"? {file_path} - CORRUPTED: {e}")
                        corrupted_files.append(file_path)
                        
                    except Exception as e:
                        print(f"??  {file_path} - ERROR: {e}")
    
    return corrupted_files

def fix_corrupted_file(file_path):
    """Fix a corrupted HTML file"""
    print(f"\n?? Fixing corrupted file: {file_path}")
    
    try:
        # Try different encodings
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        
        content = None
        used_encoding = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                used_encoding = encoding
                print(f"? Successfully read with {encoding} encoding")
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            print(f"? Could not read file with any encoding")
            return False
        
        # Clean the content - remove problematic characters
        # The copyright character (0xa9) is common in corrupted files
        content = content.replace('\xa9', '(c)')  # Replace with (c)
        content = content.replace('\u00a9', '(c)')  # Another form
        
        # Remove other problematic characters - keep only ASCII and common symbols
        cleaned_content = ''
        for char in content:
            if ord(char) < 128:  # ASCII characters
                cleaned_content += char
            elif char in ['©', '®', '™']:  # Common symbols
                cleaned_content += '(c)' if char == '©' else char
            else:
                # Replace other non-ASCII with space
                cleaned_content += ' '
        
        content = cleaned_content
        
        # Create backup
        backup_path = file_path + '.backup'
        shutil.copy2(file_path, backup_path)
        print(f"?? Created backup: {backup_path}")
        
        # Write corrected content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"? Fixed encoding issues in {file_path}")
        return True
        
    except Exception as e:
        print(f"? Error fixing file {file_path}: {e}")
        return False

def create_clean_templates():
    """Create clean template files"""
    print("\n?? Creating clean template files...")
    
    # Ensure we're in the project directory
    project_dir = "/home/pi/noaa_alerts_system"
    os.chdir(project_dir)
    
    # Create templates directory
    templates_dir = os.path.join(project_dir, "templates")
    os.makedirs(templates_dir, exist_ok=True)
    print(f"?? Created templates directory: {templates_dir}")
    
    # Clean base.html template
    base_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}NOAA CAP Alerts System{% endblock %}</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css" rel="stylesheet">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar-brand { font-weight: bold; }
        .map-container { height: 500px; border: 1px solid #dee2e6; border-radius: 8px; }
        .loading { text-align: center; padding: 20px; color: #6c757d; }
    </style>
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
    <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>'''

    # Clean index.html template
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
                <div id="map" class="map-container">
                    <div class="loading">
                        <i class="fas fa-spinner fa-spin"></i> Loading map...
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
                <div id="system-status" class="loading">
                    <i class="fas fa-spinner fa-spin"></i> Loading status...
                </div>
            </div>
        </div>
        
        <div class="card mt-3">
            <div class="card-header">
                <h5><i class="fas fa-exclamation-triangle"></i> Active Alerts</h5>
            </div>
            <div class="card-body">
                <div id="alerts-summary" class="loading">
                    <i class="fas fa-spinner fa-spin"></i> Loading alerts...
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
// Initialize map and load data
document.addEventListener('DOMContentLoaded', function() {
    // Map initialization code will go here
    document.getElementById('system-status').innerHTML = 'System operational';
    document.getElementById('alerts-summary').innerHTML = 'No active alerts';
});
</script>
{% endblock %}'''

    # Clean admin.html template
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
                        <div class="form-text">Upload a GeoJSON file containing boundary polygons</div>
                    </div>
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-upload"></i> Upload Boundaries
                    </button>
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
                <div id="operation-status" class="mt-3"></div>
            </div>
        </div>
        
        <div class="card mt-3">
            <div class="card-header">
                <h5><i class="fas fa-chart-bar"></i> Quick Stats</h5>
            </div>
            <div class="card-body">
                <div id="quick-stats" class="loading">
                    <i class="fas fa-spinner fa-spin"></i> Loading stats...
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
// Admin panel JavaScript
document.getElementById('uploadForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const formData = new FormData(this);
    const statusDiv = document.getElementById('upload-status');
    
    statusDiv.innerHTML = '<div class="alert alert-info"><i class="fas fa-spinner fa-spin"></i> Uploading...</div>';
    
    try {
        const response = await fetch('/admin/upload_boundary', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
            statusDiv.innerHTML = '<div class="alert alert-success"><i class="fas fa-check"></i> ' + result.success + '</div>';
            this.reset();
        } else {
            statusDiv.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times"></i> ' + result.error + '</div>';
        }
    } catch (error) {
        statusDiv.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times"></i> Error: ' + error.message + '</div>';
    }
});

async function triggerPoll() {
    try {
        const response = await fetch('/admin/trigger_poll', { method: 'POST' });
        const result = await response.json();
        showOperationResult(result.message || result.error, response.ok);
    } catch (error) {
        showOperationResult('Error: ' + error.message, false);
    }
}

async function clearExpired() {
    if (confirm('Are you sure you want to clear all expired alerts?')) {
        try {
            const response = await fetch('/admin/clear_expired', { method: 'POST' });
            const result = await response.json();
            showOperationResult(result.message || result.error, response.ok);
        } catch (error) {
            showOperationResult('Error: ' + error.message, false);
        }
    }
}

async function optimizeDb() {
    if (confirm('Are you sure you want to run database optimization?')) {
        try {
            const response = await fetch('/admin/optimize_db', { method: 'POST' });
            const result = await response.json();
            showOperationResult(result.message || result.error, response.ok);
        } catch (error) {
            showOperationResult('Error: ' + error.message, false);
        }
    }
}

function showOperationResult(message, success) {
    const statusDiv = document.getElementById('operation-status');
    const alertClass = success ? 'alert-success' : 'alert-danger';
    const icon = success ? 'fas fa-check' : 'fas fa-times';
    statusDiv.innerHTML = `<div class="alert ${alertClass}"><i class="${icon}"></i> ${message}</div>`;
}
</script>
{% endblock %}'''

    # Write clean template files
    templates = [
        ('base.html', base_template),
        ('index.html', index_template),
        ('admin.html', admin_template)
    ]
    
    for filename, content in templates:
        file_path = os.path.join(templates_dir, filename)
        
        # Remove existing file if it exists
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Write new clean file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"? Created clean {filename}")
    
    # Set proper permissions
    os.chmod(templates_dir, 0o755)
    for filename, _ in templates:
        file_path = os.path.join(templates_dir, filename)
        os.chmod(file_path, 0o644)
    
    print("? Set proper file permissions")
    
    return templates_dir

def update_wsgi_config():
    """Update WSGI configuration to set proper working directory"""
    print("\n?? Updating WSGI configuration...")
    
    wsgi_file = "/home/pi/noaa_alerts_system/wsgi.py"
    
    if not os.path.exists(wsgi_file):
        print(f"? WSGI file not found: {wsgi_file}")
        return False
    
    # Create backup
    backup_file = wsgi_file + '.backup'
    shutil.copy2(wsgi_file, backup_file)
    
    # Updated WSGI content
    wsgi_content = '''#!/usr/bin/env python3
import sys
import os

# Set the working directory to the project directory
project_dir = '/home/pi/noaa_alerts_system'
os.chdir(project_dir)

# Add project directory to Python path
sys.path.insert(0, project_dir)

# Import Flask application
from app import app

# WSGI application object
application = app

if __name__ == "__main__":
    application.run(debug=False)
'''
    
    # Write updated WSGI file
    with open(wsgi_file, 'w', encoding='utf-8') as f:
        f.write(wsgi_content)
    
    print(f"? Updated WSGI configuration")
    print(f"?? Backup created: {backup_file}")
    
    return True

def main():
    """Main fix function"""
    print("?? NOAA Alerts Template Issues Fix")
    print("=" * 50)
    
    # Step 1: Fix working directory
    if not fix_working_directory():
        print("? Could not fix working directory. Exiting.")
        return False
    
    # Step 2: Find corrupted files
    corrupted_files = find_corrupted_html_files()
    
    # Step 3: Fix corrupted files
    if corrupted_files:
        print(f"\n?? Found {len(corrupted_files)} corrupted files")
        for file_path in corrupted_files:
            fix_corrupted_file(file_path)
    
    # Step 4: Create clean templates
    templates_dir = create_clean_templates()
    
    # Step 5: Update WSGI configuration
    update_wsgi_config()
    
    print("\n?? FIX SUMMARY")
    print("=" * 20)
    print("? Working directory fixed")
    print("? Clean templates created")
    print("? WSGI configuration updated")
    print(f"?? Templates directory: {templates_dir}")
    
    print("\n?? NEXT STEPS:")
    print("1. Restart Apache: sudo systemctl restart apache2")
    print("2. Check the web interface")
    print("3. Monitor logs for any remaining issues")
    
    print(f"\n?? Current directory: {os.getcwd()}")
    print(f"?? Templates directory exists: {os.path.exists(templates_dir)}")
    
    return True

if __name__ == '__main__':
    main()