 # Go to project directory
cd /home/pi/noaa_alerts_system

# Remove corrupted files
for html_file in *.html; do
    if [ -f "$html_file" ]; then
        mv "$html_file" "${html_file}.corrupted_backup"
        echo "Moved $html_file to ${html_file}.corrupted_backup"
    fi
done

# Backup existing templates
if [ -d "templates" ]; then
    mv templates templates_backup
    echo "Backed up existing templates"
fi

# Create new templates directory
mkdir -p templates

# Create base.html
cat > templates/base.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}NOAA CAP Alerts System{% endblock %}</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">NOAA CAP Alerts</a>
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
    {% block scripts %}{% endblock %}
</body>
</html>
EOF

# Create index.html
cat > templates/index.html << 'EOF'
{% extends "base.html" %}
{% block content %}
<div class="row">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header">Interactive Map</div>
            <div class="card-body">
                <div id="map" style="height: 500px; background: #f8f9fa;">
                    Map will load here
                </div>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card">
            <div class="card-header">System Status</div>
            <div class="card-body">
                <div id="system-status">Loading...</div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
EOF

# Create admin.html
cat > templates/admin.html << 'EOF'
{% extends "base.html" %}
{% block content %}
<div class="card">
    <div class="card-header">Admin Panel</div>
    <div class="card-body">
        <h5>Upload Boundary Files</h5>
        <form id="uploadForm" enctype="multipart/form-data">
            <div class="mb-3">
                <label class="form-label">Boundary Type</label>
                <select class="form-select" name="boundary_type" required>
                    <option value="">Select type...</option>
                    <option value="fire">Fire District</option>
                    <option value="ems">EMS District</option>
                </select>
            </div>
            <div class="mb-3">
                <label class="form-label">GeoJSON File</label>
                <input type="file" class="form-control" name="file" accept=".geojson,.json" required>
            </div>
            <button type="submit" class="btn btn-primary">Upload</button>
        </form>
    </div>
</div>
{% endblock %}
EOF

# Fix WSGI file
cp wsgi.py wsgi.py.backup
cat > wsgi.py << 'EOF'
#!/usr/bin/env python3
import sys
import os

# Set working directory
project_dir = '/home/pi/noaa_alerts_system'
os.chdir(project_dir)
sys.path.insert(0, project_dir)

# Import Flask application
from app import app

# WSGI application object
application = app
EOF

# Set permissions
chmod 755 templates
chmod 644 templates/*.html
chmod 755 wsgi.py

# Verify
echo "Templates created:"
ls -la templates/