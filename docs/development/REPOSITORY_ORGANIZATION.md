# Repository Root Directory Organization

This document explains what belongs in the repository root and what should be organized into subdirectories.

## Files That MUST Stay in Root

### Python Entry Points
- **`app.py`** - Main Flask application entry point (imported by wsgi.py, referenced in docs)
- **`wsgi.py`** - WSGI entry point for Gunicorn (referenced in Dockerfile ENTRYPOINT)

### Docker Entrypoint Scripts
These scripts are referenced in Dockerfiles and must remain in root:
- **`docker-entrypoint.sh`** - Main application container entrypoint (COPY'd in Dockerfile)
- **`docker-entrypoint-icecast.sh`** - Icecast container entrypoint (COPY'd in Dockerfile.icecast)
- **`nginx-init.sh`** - Nginx initialization script (COPY'd in Dockerfile.nginx)

### Docker Configuration
- **`Dockerfile`** - Main application container
- **`Dockerfile.icecast`** - Icecast streaming server container
- **`Dockerfile.nginx`** - Nginx reverse proxy container
- **`docker-compose.yml`** - Main compose file
- **`docker-compose.*.yml`** - Deployment-specific compose files
- **`.dockerignore`** - Docker build exclusions

### Configuration Files
- **`.env`** - Environment variables (user-editable)
- **`.env.example`** - Environment template
- **`stack.env`** - Portainer stack environment (user-editable)
- **`stack.env.example`** - Portainer template
- **`nginx.conf`** - Nginx configuration template
- **`alembic.ini`** - Database migration configuration
- **`mkdocs.yml`** - Documentation site configuration
- **`requirements.txt`** - Python dependencies
- **`requirements-docs.txt`** - Documentation build dependencies

### Project Meta Files
- **`README.md`** - Project overview and quick start
- **`LICENSE`** - MIT license
- **`VERSION`** - Current version number
- **`.gitignore`** - Git exclusions

### Documentation Summaries
These files document significant changes/features and should stay in root for visibility:
- **`FUNCTION_TREE_SUMMARY.txt`** - Code structure documentation
- **`GPIO_FIX_SUMMARY.md`** - GPIO implementation fixes
- **`GPIO_IMPROVEMENTS_*.md`** - GPIO enhancement documentation
- **`ROUTE_SECURITY_ANALYSIS.txt`** - Security audit results

## Organization by Directory

### `scripts/` - Application Scripts
All Python scripts and shell scripts that are part of the application functionality:
- **`scripts/diagnostics/`** - Diagnostic and troubleshooting tools
- **`scripts/deprecated/`** - Obsolete scripts kept for reference
- **`scripts/database/`** - Database utilities and migrations
- Other operational scripts (LED control, screen management, etc.)

### `tools/` - Developer/Admin Tools
Standalone tools for maintenance and administration:
- Backup/restore utilities
- Setup wizards
- Audio debugging tools
- Zone catalog synchronization

### `docs/` - Documentation
All documentation organized by topic:
- **`docs/guides/`** - User guides and tutorials
- **`docs/deployment/`** - Deployment instructions
- **`docs/development/`** - Developer documentation

### `app_core/` - Core Application Code
Backend application logic and models

### `webapp/` - Web Frontend
Routes, templates, and web UI components

### `static/` - Static Assets
CSS, JavaScript, images, and generated audio files

### `templates/` - HTML Templates
Jinja2 templates for the web interface

### `tests/` - Test Suite
Unit and integration tests

### Other Directories
- **`poller/`** - Alert polling service
- **`assets/`** - Design assets and resources
- **`examples/`** - Example configurations
- **`samples/`** - Sample data files
- **`app_utils/`** - Shared utility functions

## Adding New Files

**Before adding files to root, ask:**
1. Is it required by Docker? → Root
2. Is it a Python/shell script? → `scripts/` or `tools/`
3. Is it documentation? → `docs/`
4. Is it configuration? → Consider if it belongs in a subdirectory
5. Is it a meta file (LICENSE, README)? → Root

**General rule:** Root should only contain files that are:
- Required by the Docker build process
- Entry points for the application
- Top-level configuration files
- Essential project documentation (README, LICENSE)

## Moving Files to Root (⚠️ Warning)

If you need to move a file to root that was previously in a subdirectory:
1. Check if any Dockerfiles reference it with `COPY`
2. Update all documentation references
3. Add a redirect/note in the old location if the file was frequently referenced
4. Update any scripts that use relative paths

## Review Checklist

When reviewing PRs that add files to root:
- [ ] Is this file necessary in root?
- [ ] Could it be organized into an existing subdirectory?
- [ ] Is there a README in its destination directory explaining its purpose?
- [ ] Are all documentation references updated?
- [ ] Does the file follow naming conventions (kebab-case for scripts)?
