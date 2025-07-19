#!/usr/bin/env python3
"""
Template Diagnostic Script
Diagnose template loading issues in Flask application
"""

import os
import sys
from pathlib import Path

def diagnose_template_setup():
    """Diagnose template setup issues"""
    print("?? NOAA Alerts Template Diagnostic")
    print("=" * 50)
    
    # Get current directory
    current_dir = os.getcwd()
    print(f"?? Current working directory: {current_dir}")
    
    # Check for Flask application file
    app_file = os.path.join(current_dir, 'app.py')
    if os.path.exists(app_file):
        print("? app.py found")
    else:
        print("? app.py not found")
        return False
    
    # Check for templates directory
    templates_dir = os.path.join(current_dir, 'templates')
    print(f"?? Expected templates directory: {templates_dir}")
    
    if os.path.exists(templates_dir):
        print("? templates directory exists")
        
        # Check permissions
        if os.access(templates_dir, os.R_OK):
            print("? templates directory is readable")
        else:
            print("? templates directory is NOT readable")
            return False
            
        # List contents
        try:
            contents = os.listdir(templates_dir)
            print(f"?? Templates directory contents: {contents}")
            
            # Check for required templates
            required_templates = ['index.html', 'admin.html', 'base.html']
            missing_templates = []
            
            for template in required_templates:
                template_path = os.path.join(templates_dir, template)
                if os.path.exists(template_path):
                    print(f"? {template} exists")
                    
                    # Check file size
                    file_size = os.path.getsize(template_path)
                    print(f"   ?? Size: {file_size} bytes")
                    
                    # Check permissions
                    if os.access(template_path, os.R_OK):
                        print(f"   ? {template} is readable")
                    else:
                        print(f"   ? {template} is NOT readable")
                        
                    # Check if it's a valid file (not directory)
                    if os.path.isfile(template_path):
                        print(f"   ? {template} is a file")
                    else:
                        print(f"   ? {template} is NOT a file")
                        
                else:
                    print(f"? {template} is missing")
                    missing_templates.append(template)
                    
            if missing_templates:
                print(f"??  Missing templates: {missing_templates}")
                return False
                
        except Exception as e:
            print(f"? Error reading templates directory: {e}")
            return False
            
    else:
        print("? templates directory does not exist")
        
        # Check if templates are in the same directory as app.py
        print("?? Checking for templates in current directory...")
        html_files = [f for f in os.listdir(current_dir) if f.endswith('.html')]
        
        if html_files:
            print(f"?? HTML files found in current directory: {html_files}")
            print("?? Consider creating a 'templates' directory and moving HTML files there")
            
            # Create templates directory and move files
            try:
                os.makedirs(templates_dir, exist_ok=True)
                print(f"? Created templates directory: {templates_dir}")
                
                for html_file in html_files:
                    src = os.path.join(current_dir, html_file)
                    dst = os.path.join(templates_dir, html_file)
                    
                    # Copy file instead of moving to be safe
                    import shutil
                    shutil.copy2(src, dst)
                    print(f"?? Copied {html_file} to templates directory")
                    
                print("? Template setup completed!")
                return True
                
            except Exception as e:
                print(f"? Error creating templates directory: {e}")
                return False
        else:
            print("? No HTML files found in current directory")
            return False
    
    print("? Template setup appears to be correct")
    return True

def check_flask_configuration():
    """Check Flask configuration"""
    print("\n?? Flask Configuration Check")
    print("=" * 30)
    
    try:
        # Try to import Flask and create app
        from flask import Flask
        app = Flask(__name__)
        
        print(f"? Flask imported successfully")
        print(f"?? Default template folder: {app.template_folder}")
        print(f"?? Absolute template path: {os.path.abspath(app.template_folder)}")
        
        # Check if template folder exists
        if os.path.exists(app.template_folder):
            print("? Template folder exists")
        else:
            print("? Template folder does not exist")
            
        return True
        
    except Exception as e:
        print(f"? Error with Flask setup: {e}")
        return False

def check_file_permissions():
    """Check file permissions"""
    print("\n?? File Permissions Check")
    print("=" * 30)
    
    current_dir = os.getcwd()
    
    # Check current directory permissions
    if os.access(current_dir, os.R_OK):
        print("? Current directory is readable")
    else:
        print("? Current directory is NOT readable")
        
    if os.access(current_dir, os.W_OK):
        print("? Current directory is writable")
    else:
        print("? Current directory is NOT writable")
        
    # Check user/group
    try:
        import pwd
        import grp
        
        stat = os.stat(current_dir)
        user = pwd.getpwuid(stat.st_uid).pw_name
        group = grp.getgrgid(stat.st_gid).gr_name
        
        print(f"?? Directory owner: {user}:{group}")
        print(f"?? Directory permissions: {oct(stat.st_mode)[-3:]}")
        
    except Exception as e:
        print(f"??  Could not get detailed permissions: {e}")

def main():
    """Main diagnostic function"""
    print("?? Starting NOAA Alerts Template Diagnostics\n")
    
    # Run diagnostics
    template_ok = diagnose_template_setup()
    flask_ok = check_flask_configuration()
    check_file_permissions()
    
    print("\n?? DIAGNOSTIC SUMMARY")
    print("=" * 30)
    
    if template_ok and flask_ok:
        print("? All checks passed! Templates should load correctly.")
        print("\n?? NEXT STEPS:")
        print("1. Restart your Flask application")
        print("2. Check the application logs for any remaining issues")
        print("3. Test template loading by visiting the web interface")
    else:
        print("? Issues found. Please resolve the problems above.")
        if not template_ok:
            print("   - Template setup issues")
        if not flask_ok:
            print("   - Flask configuration issues")
        
        print("\n?? RECOMMENDED FIXES:")
        print("1. Ensure templates directory exists in the same folder as app.py")
        print("2. Check file permissions (templates should be readable)")
        print("3. Verify HTML files are valid and not corrupted")
        print("4. Run this diagnostic again after making changes")
    
    print(f"\n?? Current directory: {os.getcwd()}")
    print(f"?? Run this script from your Flask app directory")

if __name__ == '__main__':
    main()