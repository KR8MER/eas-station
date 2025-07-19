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
