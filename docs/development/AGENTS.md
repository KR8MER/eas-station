# AI Agent Development Guidelines

This document provides coding standards and guidelines for AI agents (including Claude, GitHub Copilot, Cursor, and other AI assistants) when working on the NOAA CAP Emergency Alert System codebase.

---

## 🎯 Core Principles

1. **Safety First**: Never commit secrets, API keys, or sensitive data
2. **Preserve Existing Patterns**: Follow the established code style and architecture
3. **Test Before Commit**: Always verify changes work in Docker before committing
4. **Focused Changes**: Keep fixes targeted to the specific issue
5. **Document Changes**: Update relevant documentation when adding features
6. **Check Bug Screenshots**: When discussing bugs, always check the `/bugs` directory first for screenshots
7. **Follow Versioning**: Bug fixes increment by 0.0.+1, feature upgrades increment by 0.+1.0
8. **File Naming Convention**: When superseding files, rename the old one with `_old` suffix, NEVER use `_new` suffix for replacement files
9. **Repository Organization**: Every file must live in an appropriate directory unless necessary to be in the root (e.g., `requirements.txt`, `Dockerfile`, `README.md`, `LICENSE`, etc.). Documentation, summaries, and development artifacts belong in the `docs/` directory structure.

## 🐛 Bug Tracking & Screenshots

When discussing or investigating bugs:

1. **Check `/bugs` Directory First** – Before starting any bug investigation, check the `/bugs` directory for screenshots and other evidence
2. **Screenshots Over Text** – Since AI assistants can't receive images directly in chat, users will place bug screenshots in `/bugs`
3. **Name Descriptively** – Screenshot filenames should indicate the issue (e.g., `admin_spacing_issue.jpeg`, `dark_mode_contrast_bug.png`)
4. **Document Fixes** – When fixing a bug shown in a screenshot, reference the screenshot filename in commit messages
5. **Clean Up After** – Once a bug is fixed and verified, move the screenshot to `/bugs/resolved` or delete it

## 🧭 Documentation & UX Standards

- **Link Accuracy Matters** – Reference primary sources (e.g., FCC consent decrees via `docs.fcc.gov`) instead of news summaries. Broken or redirected links must be updated immediately.
- **Theory of Operation Is Canonical** – Whenever you touch ingestion, SAME generation, or verification logic, review and update [`docs/architecture/THEORY_OF_OPERATION.md`](../architecture/THEORY_OF_OPERATION) so diagrams, timelines, and checklists match the code.
- **Surface Docs In-App** – Front-end templates (`templates/`) should link to the corresponding Markdown resources in `docs/`. Keep `/about`, `/help`, `/terms`, and `/privacy` synchronized with repository guidance.
- **Documentation Updates Required** – When adding new features or changing workflows, update:
  - `templates/help.html` – User-facing help documentation
  - `templates/about.html` – System overview and feature descriptions
  - Relevant Markdown files in `docs/` directory
  - This ensures users always have current information about system capabilities
- **Brand Consistency** – Use `static/img/eas-system-wordmark.svg` for hero sections, headers, and major UI cards when expanding documentation pages. The logo must remain accessible (include `alt` text).
- **Mermaid-Friendly Markdown** – GitHub-flavoured Mermaid diagrams are welcome in repository docs. Keep them accurate by naming real modules, packages, and endpoints.

### **🚨 MANDATORY: Frontend UI for Every Backend Feature**

**CRITICAL RULE**: Every backend feature MUST have a corresponding frontend user interface. Backend-only features are UNACCEPTABLE.

When implementing ANY new feature:

1. **Backend + Frontend Together**
   - ✅ **CORRECT**: Create API endpoint `/api/gpio/activate` AND UI page `/gpio_control`
   - ❌ **WRONG**: Create API endpoint without UI (user cannot access it!)

2. **Navigation Access Required**
   - Every new page must be accessible from the navigation menu
   - Add appropriate menu items in `templates/base.html`
   - Consider: Which dropdown menu does this belong in? (Operations, Analytics, Admin, Settings)
   - If creating a new major feature, create a new navigation section

3. **Documentation Requirements**
   - Document the UI access path: "Navigate to Operations → GPIO Control"
   - Include screenshots showing how to access the feature
   - Update `docs/NEW_FEATURES.md` or relevant guides
   - Add inline help text or tooltips in the UI

4. **Form Input Standards**
   - **Binary choices (true/false, yes/no, enabled/disabled)** MUST use:
     - Dropdown menus with fixed options, OR
     - Radio button groups, OR
     - Toggle switches
   - ❌ **NEVER use free-text inputs for binary choices** - users will make capitalization errors
   - ✅ **Example (Dropdown)**:
     ```html
     <select class="form-select" name="enabled">
       <option value="true">Enabled</option>
       <option value="false">Disabled</option>
     </select>
     ```
   - ✅ **Example (Radio)**:
     ```html
     <div class="form-check">
       <input class="form-check-input" type="radio" name="enabled" value="true" id="enabled-yes">
       <label class="form-check-label" for="enabled-yes">Enabled</label>
     </div>
     <div class="form-check">
       <input class="form-check-input" type="radio" name="enabled" value="false" id="enabled-no">
       <label class="form-check-label" for="enabled-no">Disabled</label>
     </div>
     ```
   - ✅ **Example (Toggle Switch)**:
     ```html
     <div class="form-check form-switch">
       <input class="form-check-input" type="checkbox" role="switch" id="enabledSwitch" name="enabled">
       <label class="form-check-label" for="enabledSwitch">Enable Feature</label>
     </div>
     ```

5. **Pre-Commit Checklist for New Features**
   - [ ] Backend API endpoints created
   - [ ] Frontend UI page created (HTML template)
   - [ ] Navigation menu updated to access the page
   - [ ] Forms use proper input types (no text inputs for binary choices)
   - [ ] Documentation updated with access instructions
   - [ ] Feature tested end-to-end through the UI
   - [ ] Error handling displays user-friendly messages

6. **Examples of Complete Features**
   - ✅ **RBAC Management**: Backend routes in `/security/roles` + Frontend UI at `/admin/rbac` + Navigation in Admin menu
   - ✅ **Audit Logs**: Backend routes in `/security/audit-logs` + Frontend UI at `/admin/audit-logs` + Export button + Filtering
   - ✅ **GPIO Control**: Backend API `/api/gpio/*` + Frontend UI `/gpio_control` + Statistics page `/admin/gpio/statistics`

7. **What Counts as "Accessible"**
   - User can find and use the feature without reading code
   - Feature is discoverable through navigation or obvious links
   - No need to manually type URLs or use API tools
   - All CRUD operations (Create, Read, Update, Delete) have UI buttons/forms

**Remember**: If a user cannot access a feature through the web interface, the feature doesn't exist for them. Backend-only work is wasted effort.

### Modularity & File Size

- **Prefer small, focused modules** – Aim to keep Python modules under ~400 lines and HTML templates under ~300 lines.
- **Refactor before things get unwieldy** – When adding more than one new class or multiple functions to a module already above 350 lines, create or use a sibling module/package instead of expanding the existing file.
- **Extract repeated markup** – Move duplicated template fragments into `templates/components/` and use Flask blueprints or helper modules to share behavior.
- **Stay consistent with existing structure** – Place new Python packages within `app_core/` or `app_utils/` as appropriate, and keep front-end assets organized under `static/` and `templates/` using the same layout patterns as current files.
- **File Naming Convention** – When a file supersedes a previous one:
  - **CORRECT**: Rename old file to `filename_old.ext`, new file becomes `filename.ext`
  - **WRONG**: Never use `filename_new.ext` as the replacement - this creates confusion
  - Example: `navbar.html` (active) supersedes `navbar_old.html` (deprecated)
- **Pre-commit self-check** – Confirm any touched file still meets these size expectations or has been split appropriately before finalizing changes.

---

## 📝 Code Style Standards

### Python Code Style

- **Indentation**: Use **4 spaces** (never tabs) for all Python code
- **Line Length**: Keep lines under 100 characters where practical
- **Naming Conventions**:
  - Functions and variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
  - Private methods: `_leading_underscore`

**Example:**
```python
# Good
def calculate_alert_intersections(alert_id, boundary_type="county"):
    """Calculate intersections for a specific alert."""
    pass

# Bad
def calculateAlertIntersections(alertId, boundaryType="county"):  # Wrong naming
  pass  # Wrong indentation
```

### Logging Standards

- **Always use the existing logger** - Never create new logger instances
- **Log Levels**:
  - `logger.debug()` - Detailed diagnostic information
  - `logger.info()` - General informational messages
  - `logger.warning()` - Warning messages for potentially harmful situations
  - `logger.error()` - Error messages for serious problems
  - `logger.critical()` - Critical failures

**Example:**
```python
# Good - Uses existing logger
logger.info(f"Processing alert {alert_id}")
logger.error(f"Failed to connect to database: {str(e)}")

# Bad - Creates new logger
import logging
my_logger = logging.getLogger(__name__)  # Don't do this!
```

### Error Handling

- **Always catch specific exceptions** - Never use bare `except:`
- **Include context in error messages** - Help with debugging
- **Roll back database transactions** on errors

**Example:**
```python
# Good
try:
    alert = CAPAlert.query.get_or_404(alert_id)
    # ... do work ...
    db.session.commit()
except OperationalError as e:
    db.session.rollback()
    logger.error(f"Database error processing alert {alert_id}: {str(e)}")
    return jsonify({'error': 'Database connection failed'}), 500
except Exception as e:
    db.session.rollback()
    logger.error(f"Unexpected error in process_alert: {str(e)}")
    return jsonify({'error': str(e)}), 500

# Bad
try:
    # ... code ...
except:  # Too broad!
    pass  # Silently ignoring errors!
```

---

## 🗄️ Database Guidelines

### SQLAlchemy Patterns

- **Use the session properly** - Always commit or rollback
- **Query efficiently** - Use `.filter()` for conditions, `.all()` or `.first()` appropriately
- **Handle geometry** - Remember that `geom` fields are PostGIS types

**Example:**
```python
# Good
try:
    alert = CAPAlert.query.filter_by(identifier=cap_id).first()
    if alert:
        alert.status = 'expired'
        db.session.commit()
        logger.info(f"Marked alert {cap_id} as expired")
    else:
        logger.warning(f"Alert {cap_id} not found")
except Exception as e:
    db.session.rollback()
    logger.error(f"Error marking alert as expired: {str(e)}")
```

### PostGIS Spatial Queries

- **Use PostGIS functions** - `ST_Intersects`, `ST_Area`, `ST_GeomFromGeoJSON`
- **Check for NULL geometry** - Always verify `alert.geom is not None`
- **Handle spatial queries carefully** - They can be slow on large datasets

**Example:**
```python
# Good - Checks for geometry and uses PostGIS functions
if alert.geom and boundary.geom:
    intersection = db.session.query(
        func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
        func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('area')
    ).first()
```

---

## 🎨 Frontend Guidelines

### Template Standards

- **Extend base.html** - All templates should use `{% extends "base.html" %}`
- **Use theme variables** - Reference CSS variables: `var(--primary-color)`, `var(--text-color)`, `var(--bg-color)`
- **Support all themes** - EAS Station has multiple built-in themes (Cosmo, Dark, Coffee, Spring, and color-based themes)
- **Test in multiple themes** - Always test in both light (Cosmo) and dark themes at minimum
- **Be responsive** - Use Bootstrap 5 grid classes for mobile support
- **Theme Variable Categories**:
  - **Colors**: `--primary-color`, `--secondary-color`, `--accent-color`
  - **Status**: `--success-color`, `--danger-color`, `--warning-color`, `--info-color`
  - **Text**: `--text-color`, `--text-secondary`, `--text-muted`
  - **Backgrounds**: `--bg-color`, `--surface-color`, `--bg-card`
  - **Borders**: `--border-color`, `--shadow-color`

**Example:**
```html
{% extends "base.html" %}

{% block title %}My Feature - EAS Station{% endblock %}

{% block extra_css %}
<style>
    .my-custom-class {
        background-color: var(--bg-color);
        color: var(--text-color);
        border: 1px solid var(--border-color);
    }

    /* All themes automatically inherit CSS variables */
    /* No need for theme-specific overrides unless absolutely necessary */
</style>
{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
    <h1>My Feature</h1>
    <!-- Content here -->
</div>
{% endblock %}
```

### JavaScript Patterns

- **Use existing global functions** - `showToast()`, `toggleTheme()`, `setTheme()`, `showThemeSelector()`, `exportToExcel()`
- **Avoid jQuery** - Use vanilla JavaScript and modern ES6+ features
- **Handle errors gracefully** - Show user-friendly messages using toast notifications
- **Theme System Functions**:
  - `setTheme(themeName)` - Switch to a specific theme
  - `toggleTheme()` - Toggle between light and dark modes
  - `getCurrentTheme()` - Get current active theme name
  - `getCurrentThemeMode()` - Get current theme mode ('light' or 'dark')
  - `getAvailableThemes()` - Get list of all available themes
  - `showThemeSelector()` - Display theme selection modal with import/export
  - `exportTheme(themeName)` - Export theme as JSON
  - `downloadTheme(themeName)` - Download theme file
  - `importTheme(jsonString)` - Import custom theme from JSON
  - `deleteTheme(themeName)` - Remove custom theme (built-in themes cannot be deleted)

### Template Structure & Page Elements

**CRITICAL**: Know which files are actually being used vs orphaned duplicates.

#### Active Template Files

| Element | Active File | Lines | Status |
|---------|------------|-------|--------|
| **Base Template** | `templates/base.html` | 163 | ✅ All pages extend this |
| **Navbar** | `templates/components/navbar.html` | 420+ | ✅ Included in base.html (renamed from navbar_new.html) |
| **Footer** | Inline in `templates/base.html` | 103-144 | ✅ Inline in base template |
| **System Banner** | Inline in `templates/base.html` | 72-81 | ✅ Inline in base template |
| **Flash Messages** | Inline in `templates/base.html` | 84-95 | ✅ Inline in base template |

#### Deprecated Files (DO NOT EDIT)

| File | Status | Action Required |
|------|--------|----------------|
| `templates/base_new.html` | ❌ Not used anywhere | Can be deleted |
| `templates/components/navbar_old.html` | ❌ Superseded by navbar.html | Keep as reference, do not edit |
| `components/navbar.html` | ❌ Wrong directory | Should be deleted |
| `components/footer.html` | ❌ Was deleted (not included) | Already removed |
| `components/page_header.html` | ⚠️ Macro component, wrong location | Move to templates/components/ if used |

#### When Making Changes to Page Elements

**Changing the Navbar:**
- ✅ Edit: `templates/components/navbar.html`
- ❌ Don't edit: `templates/components/navbar_old.html` (deprecated)
- ❌ Don't edit: `components/navbar.html` (wrong location)
- **Features**: Bootstrap 5 navbar, dropdowns, health indicator, theme selector (palette icon), quick theme toggle

**Changing the Footer:**
- ✅ Edit: `templates/base.html` (lines 103-144)
- ❌ Don't edit: `components/footer.html` (deleted - was orphaned)

**Changing System Status Banner:**
- ✅ Edit: `templates/base.html` (lines 72-81)

**Changing Flash Messages:**
- ✅ Edit: `templates/base.html` (lines 84-95)

**Creating New Pages:**
- ✅ Always extend `base.html`
- ✅ Use `{% block content %}` for page content
- ✅ Add navigation link to `templates/components/navbar.html`
- ❌ Never extend `base_new.html` (orphaned)

#### Quick Verification

Before editing any template file:

1. **Search for usage**: `grep -r "include.*filename" templates/`
2. **Check extends**: `grep -r "extends.*filename" templates/`
3. **Verify in Python**: `grep -r "render_template.*filename" .`
4. **Consult documentation**: See [docs/frontend/TEMPLATE_STRUCTURE.md](../frontend/TEMPLATE_STRUCTURE)

**Complete template architecture documentation**: [docs/frontend/TEMPLATE_STRUCTURE.md](../frontend/TEMPLATE_STRUCTURE)

---

## 🎨 Theme System Architecture

### Overview

EAS Station features a comprehensive theme system with 11 built-in themes and support for custom theme import/export.

### Built-in Themes

| Theme | Mode | Description | Primary Use Case |
|-------|------|-------------|------------------|
| **Cosmo** | Light | Default vibrant blue/purple theme | General use, professional |
| **Dark** | Dark | Enhanced dark mode with high contrast | Night use, reduced eye strain |
| **Coffee** | Dark | Warm coffee-inspired browns | Cozy, warm aesthetic |
| **Spring** | Light | Fresh green nature-inspired | Bright, energetic feel |
| **Red** | Light | Bold red accent theme | Alert-focused, high energy |
| **Green** | Light | Nature-inspired green | Calm, environmental |
| **Blue** | Light | Ocean blue theme | Professional, trustworthy |
| **Purple** | Light | Royal purple theme | Creative, elegant |
| **Pink** | Light | Soft pink theme | Friendly, approachable |
| **Orange** | Light | Energetic orange theme | Warm, enthusiastic |
| **Yellow** | Light | Bright yellow theme | Cheerful, optimistic |

### Theme System Files

**Core Files:**
- `static/js/core/theme.js` - Theme management, switching, import/export
- `static/css/base.css` - All theme color definitions (CSS variables)
- `templates/base.html` - Theme initialization (`data-theme="cosmo"`)
- `templates/components/navbar.html` - Theme selector UI (palette icon + quick toggle)

### CSS Variable Structure

Every theme defines these CSS variables:

**Colors:**
- `--primary-color`, `--primary-soft` - Main brand colors
- `--secondary-color`, `--secondary-soft` - Secondary brand colors
- `--accent-color` - Accent/highlight color

**Status:**
- `--success-color` - Success states (green)
- `--danger-color` - Error/danger states (red)
- `--warning-color` - Warning states (yellow/orange)
- `--info-color` - Information states (blue)
- `--critical-color` - Critical alerts (bright red/pink)

**Backgrounds:**
- `--bg-color` - Page background
- `--surface-color` - Card/panel background
- `--bg-card` - Card background (same as surface)
- `--light-color` - Light background shade
- `--dark-color` - Dark background shade

**Text:**
- `--text-color` - Primary text
- `--text-secondary` - Secondary/muted text
- `--text-muted` - Very subtle text

**UI Elements:**
- `--border-color` - Border colors
- `--shadow-color` - Box shadow colors
- `--radius-sm/md/lg` - Border radius values
- `--spacing-xs/sm/md/lg/xl` - Spacing scale

### Adding a New Theme

1. **Add theme definition to `static/js/core/theme.js`:**
```javascript
const THEMES = {
    // ...existing themes...
    'mytheme': {
        name: 'My Theme',
        mode: 'light',  // or 'dark'
        description: 'Description of my theme',
        builtin: true
    }
};
```

2. **Add CSS variables to `static/css/base.css`:**
```css
[data-theme="mytheme"] {
    --primary-color: #your-color;
    --secondary-color: #your-color;
    /* ...all other variables... */
}
```

3. **Test in multiple UI contexts:**
   - Cards and panels
   - Buttons and forms
   - Navigation bar gradient
   - Status indicators
   - Text readability (all three levels)

### Theme Import/Export

Users can create custom themes and share them:

**Export:**
```javascript
window.downloadTheme('cosmo');  // Downloads theme-cosmo.json
```

**Import:**
- Users click theme selector (palette icon in navbar)
- Upload JSON file in modal
- Custom theme appears in selector
- Stored in localStorage

**Custom Theme JSON Structure:**
```json
{
  "name": "mytheme",
  "displayName": "My Theme",
  "mode": "light",
  "description": "My custom theme",
  "version": "1.0",
  "exported": "2025-01-14T13:00:00.000Z"
}
```

### Theme Persistence

- Current theme stored in `localStorage.setItem('theme', themeName)`
- Custom themes stored in `localStorage.setItem('customThemes', jsonString)`
- Automatically loaded on page load
- Survives browser sessions

### Navbar Theme Controls

**Two buttons in navbar:**
1. **Palette Icon** (`<i class="fas fa-palette">`) - Opens theme selector modal
   - Grid of all themes with previews
   - Import/Export functionality
   - Delete custom themes
   
2. **Sun/Moon Icon** (`<i class="fas fa-sun/moon">`) - Quick toggle
   - Toggles between light and dark modes
   - Switches between Cosmo (light) and Dark (dark)

### Dark Mode Best Practices

When designing for dark mode themes:
- **Higher contrast**: Text should be brighter (#f8f9fc not #f5f6fa)
- **Softer shadows**: Use `rgba(0,0,0,0.5)` instead of `rgba(0,0,0,0.4)`
- **Vibrant accents**: Status colors should be 15-20% brighter than light mode
- **Deeper backgrounds**: Multiple levels (#12182a, #1e2538, #2d3548)
- **Muted borders**: Borders should be subtle but visible (#343d54)

---

## 🔒 Security Guidelines

### Critical Security Rules

1. **NEVER commit `.env` file** - It contains secrets
2. **NEVER hardcode credentials** - Always use environment variables
3. **NEVER expose debug endpoints** - Remove before production
4. **ALWAYS validate user input** - Especially file uploads
5. **ALWAYS use parameterized queries** - Prevent SQL injection

### Environment Variables

```python
# Good - Uses environment variable
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY and os.environ.get('FLASK_ENV') == 'production':
    raise ValueError("SECRET_KEY required in production")

# Bad - Hardcoded secret
SECRET_KEY = "my-secret-key-12345"  # NEVER DO THIS!
```

### File Uploads

```python
# Good - Validates file type and content
if not file.filename.lower().endswith('.geojson'):
    return jsonify({'error': 'Only GeoJSON files allowed'}), 400

try:
    geojson_data = json.loads(file.read().decode('utf-8'))
    # Validate structure...
except json.JSONDecodeError:
    return jsonify({'error': 'Invalid JSON format'}), 400
```

---

## 🐳 Docker & Deployment

### Testing Changes

Before committing, always test in Docker:

```bash
# Rebuild and test
sudo docker compose build
sudo docker compose up -d
sudo docker compose logs -f app

# Check for errors
sudo docker compose ps
curl http://localhost:5000/health
```

### Environment Configuration

- **Use `.env.example` as template** - Never commit `.env`
- **Document new variables** - Add to both `.env.example` and README
- **Provide sensible defaults** - Make local development easy

### Persistent Environment System

**CRITICAL CONCEPT**: EAS Station uses a **persistent volume for configuration** that survives container rebuilds, Git pull & redeploy operations, and version upgrades.

#### How It Works

1. **Persistent Volume**: Docker volume `app-config` is mounted at `/app-config/` inside the container
2. **Persistent Config File**: Configuration is stored in `/app-config/.env` (not `/app/.env`)
3. **Setup Wizard**: First-time deployments run the Setup Wizard at `http://localhost/setup` which creates and populates `/app-config/.env`
4. **Web UI Management**: Users configure settings via the Settings → Environment page, which updates `/app-config/.env`
5. **Container Startup**: `docker-entrypoint.sh` checks for `/app-config/.env` and loads it into the application environment

#### Why This Matters

**Without persistent environment:**
- ❌ Portainer "Pull and redeploy" would wipe all configuration
- ❌ Users would need to reconfigure after every Git update
- ❌ Version upgrades would reset all settings to defaults
- ❌ Manual editing of Docker Compose files required for config changes

**With persistent environment:**
- ✅ Configuration survives "Pull and redeploy" operations
- ✅ Git updates don't affect user configuration
- ✅ Settings persist across version upgrades
- ✅ Users configure via web UI (Settings → Environment)
- ✅ Setup Wizard only runs once on first deployment

#### Entrypoint Initialization Logic

The `docker-entrypoint.sh` script handles initialization:

```bash
# If CONFIG_PATH is set (default: /app-config/.env)
if [ -n "$CONFIG_PATH" ]; then
    # Create persistent config directory if needed
    mkdir -p "$(dirname "$CONFIG_PATH")"
    
    # If file doesn't exist or is empty, initialize it
    if [ ! -f "$CONFIG_PATH" ] || [ file is empty ]; then
        # Transfer environment variables from stack.env to persistent file
        # This happens ONCE on first deploy
        echo "SECRET_KEY=${SECRET_KEY:-}" >> "$CONFIG_PATH"
        echo "POSTGRES_HOST=${POSTGRES_HOST:-alerts-db}" >> "$CONFIG_PATH"
        # ... all other variables ...
    fi
    
    # Load the persistent config into environment
    export $(cat "$CONFIG_PATH" | grep -v '^#' | xargs)
fi
```

#### Configuration Flow

**First Deployment (Portainer Git Deploy):**
1. Stack deployed with `stack.env` environment variables
2. Container starts, `docker-entrypoint.sh` runs
3. Creates `/app-config/.env` and copies values from `stack.env`
4. User visits `http://localhost/setup` to complete configuration
5. Setup Wizard writes final config to `/app-config/.env`

**Subsequent Deployments (Pull & Redeploy):**
1. Portainer pulls latest code from Git
2. Rebuilds containers with updated code
3. `docker-entrypoint.sh` finds existing `/app-config/.env`
4. Loads configuration from persistent file
5. **User configuration is preserved automatically**

**Runtime Configuration Changes:**
1. User navigates to Settings → Environment
2. Changes a setting (e.g., poll interval from 180 to 300 seconds)
3. Backend updates `/app-config/.env` file
4. Restart container to apply: `docker compose restart app`

#### Variable Precedence

**Priority order (highest to lowest):**
1. Environment variables set in `docker-compose.yml` `environment:` section
2. Variables loaded from `/app-config/.env` (persistent config)
3. Variables from `stack.env` file (only used on first deploy)
4. Hardcoded defaults in Python code

**Example: DATABASE_HOST**
```yaml
# docker-compose.yml environment section
environment:
  POSTGRES_HOST: ${POSTGRES_HOST:-host.docker.internal}  # From stack.env on first deploy

# First deploy: POSTGRES_HOST=host.docker.internal is written to /app-config/.env

# Pull & redeploy: /app-config/.env still has POSTGRES_HOST=host.docker.internal
# Configuration is preserved!

# User changes it via web UI to external-db.example.com
# /app-config/.env now has: POSTGRES_HOST=external-db.example.com
# Restart applies the change
```

#### Auto-Detected vs User-Configured Variables

Some variables are **auto-detected at runtime** and should NOT be written to the persistent config if not explicitly set:

**Auto-Detected Variables:**
- `GIT_COMMIT` - Auto-detected from `.git/HEAD` and `.git/refs/` at runtime
- `HOSTNAME` - Auto-detected by system
- Build-time values that shouldn't be frozen in config

**User-Configured Variables:**
- `SECRET_KEY` - Must be generated and persisted
- `POSTGRES_HOST` - User's database server
- `EAS_BROADCAST_ENABLED` - User's feature preferences
- All settings in Settings → Environment page

**Implementation Pattern in docker-entrypoint.sh:**
```bash
# ✅ CORRECT - Only write if explicitly set
$([ -n "${GIT_COMMIT:-}" ] && echo "GIT_COMMIT=${GIT_COMMIT}" || echo "# GIT_COMMIT not set - will auto-detect")

# ❌ WRONG - Writes "unknown" and prevents auto-detection
GIT_COMMIT=${GIT_COMMIT:-unknown}
```

### Adding New Environment Variables

When adding a new environment variable to the system, you MUST update these files:

1. **`.env.example`** - Add the variable with documentation and a default value
2. **`stack.env`** - Add the variable with the default value for Docker deployments
3. **`docker-entrypoint.sh`** - Add the variable to the initialization section if it needs to be available during container startup
4. **`webapp/admin/environment.py`** - **REQUIRED**: Add the variable to the appropriate category in `ENV_CATEGORIES` to make it accessible in the web UI settings page. This is how users configure the system!
5. **`app_utils/setup_wizard.py`** - If the variable is part of initial setup, add it to the appropriate wizard section with matching validation

**CRITICAL**: EAS Station uses persistent configuration stored in `/app-config/.env` and managed through the web UI. **ALL** user-configurable environment variables MUST be added to `webapp/admin/environment.py`, otherwise users cannot change them without editing Docker Compose files.

### Environment Variable Validation

**CRITICAL:** Validation rules MUST match between `webapp/admin/environment.py` and `app_utils/setup_wizard.py`. Users should not be able to enter invalid values in either interface.

When adding validation:
- **SECRET_KEY**: Use `_validate_secret_key` in setup wizard (min 32 chars), `minlength: 32, pattern: ^[A-Za-z0-9]{32,}$` in environment.py
- **Port numbers**: Use `_validate_port` in setup wizard, `min: 1, max: 65535` in environment.py
- **IP addresses**: Use `_validate_ipv4` in setup wizard, `pattern: IPv4 regex` in environment.py
- **GPIO pins**: Use `_validate_gpio_pin` in setup wizard, `min: 2, max: 27` in environment.py
- **Station IDs**: Use `_validate_station_id` in setup wizard, `pattern: ^[A-Z0-9/]{1,8}$` in environment.py
- **Originator codes**: Use dropdown in both (4 options: WXR, EAS, PEP, CIV)

### Variable Types in environment.py

- `text` - Text input field
- `number` - Numeric input with optional min/max/step
- `password` - Password field with masking (set `sensitive: True`)
- `select` - Dropdown with predefined options
- `textarea` - Multi-line text input

**IMPORTANT:** Never use `boolean` type. Always use `select` with `options: ['false', 'true']` for yes/no or true/false values. This prevents end users from inputting invalid responses and breaking functionality.

```python
# ❌ WRONG - Don't use boolean type
{
    'key': 'SOME_FLAG',
    'type': 'boolean',
    'default': 'false',
}

# ✅ CORRECT - Use select with explicit options
{
    'key': 'SOME_FLAG',
    'type': 'select',
    'options': ['false', 'true'],
    'default': 'false',
}
```

### Input Validation Best Practices

**ALWAYS add validation attributes to prevent invalid input.**

**Important Principle:** If a field has only a fixed set of valid values (e.g., 4 originator codes, specific status codes), use a `select` dropdown instead of a `text` field with regex validation. This provides the best user experience and prevents any possibility of invalid input.

**Port Numbers:**
```python
{
    'key': 'SOME_PORT',
    'label': 'Port',
    'type': 'number',
    'default': '8080',
    'min': 1,          # Ports start at 1
    'max': 65535,      # Maximum valid port
}
```

**IP Addresses:**
```python
{
    'key': 'SOME_IP',
    'label': 'IP Address',
    'type': 'text',
    'pattern': '^((25[0-5]|(2[0-4]|1\\d|[1-9]|)\\d)\\.?\\b){4}$',
    'title': 'Must be a valid IPv4 address (e.g., 192.168.1.100)',
    'placeholder': '192.168.1.100',
}
```

**GPIO Pins (Raspberry Pi BCM):**
```python
{
    'key': 'GPIO_PIN',
    'label': 'GPIO Pin',
    'type': 'number',
    'min': 2,    # Valid GPIO range
    'max': 27,   # Standard BCM numbering
    'placeholder': 'e.g., 17',
}
```

### Conditional Field Visibility

Use the `category` attribute to group fields that should be disabled when their parent feature is disabled.

**Pattern:** When a feature can be enabled/disabled, use this structure:
1. **Enable/Disable Field** - A select dropdown or text field that controls enablement
2. **Dependent Fields** - Fields with `category` attribute linking them to the parent

**Example - Feature with Enable/Disable Toggle:**
```python
# Parent enable/disable field
{
    'key': 'EAS_BROADCAST_ENABLED',
    'label': 'Enable EAS Broadcasting',
    'type': 'select',
    'options': ['false', 'true'],
    'default': 'false',
    'description': 'Enable SAME/EAS audio generation',
},

# Dependent fields (will be grayed out when EAS_BROADCAST_ENABLED is false)
{
    'key': 'EAS_STATION_ID',
    'label': 'Station ID',
    'type': 'text',
    'category': 'eas_enabled',  # Links to parent feature
},
```

**Category Naming Convention:**
- `eas_enabled` - EAS broadcast feature
- `gpio_enabled` - GPIO control feature
- `led_enabled` - LED display feature
- `vfd_enabled` - VFD display feature
- `email` - Email notification sub-fields
- `azure_openai` - Azure OpenAI TTS sub-fields

### Variable Categories

Variables are organized into categories in `webapp/admin/environment.py`:

- **core** - Essential application configuration (SECRET_KEY, LOG_LEVEL, etc.)
- **database** - PostgreSQL connection settings
- **polling** - CAP feed polling configuration
- **location** - Default location and coverage area
- **eas** - EAS broadcast settings
- **gpio** - GPIO relay control
- **tts** - Text-to-speech providers
- **led** - LED display configuration
- **vfd** - VFD display configuration
- **notifications** - Email and SMS alerts
- **performance** - Caching and worker settings
- **docker** - Container and infrastructure settings
- **icecast** - Icecast streaming server configuration

Choose the most appropriate category for your variable, or create a new one if needed.

### Docker Compose Files - CRITICAL

**IMPORTANT:** When editing Docker Compose files, you MUST update BOTH files:

1. **`docker-compose.yml`** - Main compose file
2. **`docker-compose.embedded-db.yml`** - Embedded database variant

These files have parallel structure but different configurations (external vs embedded database). Any changes to service definitions, environment variables, ports, volumes, etc. must be applied to **BOTH** files to maintain consistency.

---

## 📚 Documentation Standards

### Code Documentation

```python
def calculate_coverage_percentages(alert_id, intersections):
    """
    Calculate actual coverage percentages for each boundary type.

    Args:
        alert_id (int): The CAP alert ID
        intersections (list): List of (intersection, boundary) tuples

    Returns:
        dict: Coverage data by boundary type with percentages and areas

    Example:
        >>> coverage = calculate_coverage_percentages(123, intersections)
        >>> print(coverage['county']['coverage_percentage'])
        45.2
    """
    # Implementation...
```

### When to Update Documentation

- **README.md** - Add new features, API endpoints, configuration options
- **AGENTS.md** - New patterns, standards, or guidelines
- **Inline comments** - Complex logic that isn't obvious
- **Docstrings** - All public functions and classes

### Documentation Location Policy

**CRITICAL**: All documentation files MUST be located in the `/docs` folder, NOT in the repository root.

**Directory Structure:**
- `/docs/development/` - Development guidelines, coding standards, agent instructions
- `/docs/guides/` - User guides, setup instructions, how-to documents
- `/docs/reference/` - Technical reference materials, function trees, known bugs
- `/docs/security/` - Security analysis, implementation checklists, audit reports
- `/docs/architecture/` - System architecture, theory of operation
- `/docs/process/` - Contributing guidelines, PR templates, issue templates
- `/docs/frontend/` - UI/UX documentation, component libraries
- `/docs/hardware/` - Hardware integration, GPIO, SDR setup
- `/docs/audio/` - Audio system documentation
- `/docs/compliance/` - FCC compliance, regulatory documentation
- `/docs/deployment/` - Deployment guides, Docker, infrastructure
- `/docs/roadmap/` - Project roadmap, feature planning
- `/docs/runbooks/` - Operational procedures, troubleshooting

**Files That Stay in Root:**
- `README.md` - Project overview and quick start (GitHub standard)
- `.env.example` - Environment variable template
- `docker-compose.yml` - Docker composition files
- `LICENSE` - License file

**When Creating New Documentation:**
1. **Choose the appropriate subdirectory** based on the content type
2. **Use descriptive filenames** in UPPERCASE_WITH_UNDERSCORES.md format
3. **Update relevant index files** (like `docs/INDEX.md`)
4. **Link from related documents** to ensure discoverability
5. **NEVER create .md files in the root** unless they are README.md

**When Moving/Reorganizing Documentation:**
1. **Use `git mv`** to preserve file history
2. **Update all references** in other markdown files
3. **Update navigation links** in index files
4. **Test all links** to ensure they're not broken

**Examples:**
- ✅ `docs/guides/SETUP_WIZARD.md` - Setup guide
- ✅ `docs/reference/KNOWN_BUGS.md` - Bug list
- ✅ `docs/security/SECURITY_ANALYSIS_INDEX.md` - Security docs
- ❌ `SETUP_GUIDE.md` (in root) - Should be in docs/guides/
- ❌ `BUG_LIST.md` (in root) - Should be in docs/reference/

---

## 🔧 Common Patterns

### Flask Route Pattern

```python
@app.route('/api/my_endpoint', methods=['POST'])
def my_endpoint():
    """Brief description of what this endpoint does."""
    try:
        # 1. Validate input
        data = request.get_json()
        if not data or 'required_field' not in data:
            return jsonify({'error': 'Missing required field'}), 400

        # 2. Do the work
        result = perform_operation(data['required_field'])

        # 3. Log success
        logger.info(f"Successfully processed {data['required_field']}")

        # 4. Return response
        return jsonify({
            'success': True,
            'result': result
        })

    except SpecificException as e:
        logger.error(f"Specific error in my_endpoint: {str(e)}")
        return jsonify({'error': 'Specific error occurred'}), 400
    except Exception as e:
        logger.error(f"Unexpected error in my_endpoint: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
```

### Database Query Pattern

```python
try:
    # Query with joins if needed
    results = db.session.query(CAPAlert, Boundary)\
        .join(Intersection, CAPAlert.id == Intersection.cap_alert_id)\
        .join(Boundary, Boundary.id == Intersection.boundary_id)\
        .filter(CAPAlert.status == 'active')\
        .all()

    # Process results
    for alert, boundary in results:
        # ... do work ...

    # Commit if making changes
    db.session.commit()

except OperationalError as e:
    db.session.rollback()
    logger.error(f"Database error: {str(e)}")
except Exception as e:
    db.session.rollback()
    logger.error(f"Error processing query: {str(e)}")
```

---

## 🚫 Anti-Patterns to Avoid

### Don't Do These

```python
# ❌ Don't use bare excepts
try:
    risky_operation()
except:
    pass

# ❌ Don't create new loggers
import logging
logger = logging.getLogger(__name__)

# ❌ Don't hardcode paths
with open('/app/data/file.txt') as f:
    # Use environment variables or config instead

# ❌ Don't commit commented-out code
# old_function()  # Delete instead of commenting
# def unused_function():
#     pass

# ❌ Don't ignore return values
db.session.commit()  # What if it fails?

# ❌ Don't use mutable default arguments
def process_alerts(alert_ids=[]):  # Bug! Use None instead
    pass
```

### Do These Instead

```python
# ✅ Catch specific exceptions
try:
    risky_operation()
except ValueError as e:
    logger.error(f"Invalid value: {str(e)}")

# ✅ Use existing logger
logger.info("Using the pre-configured logger")

# ✅ Use environment variables or config
data_dir = os.environ.get('DATA_DIR', '/app/data')
with open(os.path.join(data_dir, 'file.txt')) as f:
    pass

# ✅ Remove dead code completely
# Code is in git history if you need it

# ✅ Handle commit errors
try:
    db.session.commit()
except Exception as e:
    db.session.rollback()
    logger.error(f"Commit failed: {str(e)}")

# ✅ Use None for mutable defaults
def process_alerts(alert_ids=None):
    if alert_ids is None:
        alert_ids = []
```

---

## 🧪 Testing Guidelines

### Manual Testing Checklist

Before committing changes:

- [ ] Code passes Python syntax check: `python3 -m py_compile app.py`
- [ ] Docker build succeeds: `sudo docker compose build`
- [ ] Application starts without errors: `sudo docker compose up -d`
- [ ] Health check passes: `curl http://localhost:5000/health`
- [ ] Logs show no errors: `sudo docker compose logs -f app`
- [ ] UI tested in browser (light and dark mode)
- [ ] Database queries work as expected

### Edge Cases to Consider

- **Empty/null data** - What if no alerts exist?
- **Invalid input** - What if user provides bad data?
- **Database failures** - What if connection is lost?
- **Large datasets** - Will this scale?
- **Concurrent access** - What if multiple users access simultaneously?

---

## 📦 Dependency Management

### Adding New Dependencies

**CRITICAL**: When adding ANY new dependency to the project (Python libraries, system packages, Docker images, or infrastructure programs), you MUST update the documentation.

#### For Python Dependencies:

1. **Add to `requirements.txt`** - Include version pin
2. **Test in Docker** - Rebuild and verify
3. **Update attribution** - Add to `docs/reference/dependency_attribution.md`
4. **Document if needed** - Update README if it affects users
5. **Keep minimal** - Only add if truly necessary

**Example:**
```txt
# requirements.txt
flask==2.3.3
requests==2.31.0
new-library==1.2.3  # Add with version
pyshp==2.3.1  # Shapefile reader for converting boundary files to GeoJSON
```

**Current Python Dependencies:**
- **pyshp 2.3.1** - Shapefile reader library for ESRI Shapefile (.shp) processing
  - Used for converting TIGER/Line shapefiles to GeoJSON format
  - Enables web-based shapefile upload and conversion in admin interface
  - Required for `/admin/upload_shapefile` and `/admin/list_shapefiles` endpoints
  - Lightweight alternative to GDAL/Fiona (no complex system dependencies)

#### For System Packages and Infrastructure Components:

When adding system packages (apt/yum), Docker images, or infrastructure programs (nginx, certbot, redis, etc.):

1. **Update Dockerfile or docker-compose.yml** - Add the package/service
2. **Update `docs/reference/dependency_attribution.md`** - Add to "System Package Dependencies" section
   - Package name and version
   - Purpose and what it's used for
   - License information
   - Whether it's required or optional
3. **Update `docs/reference/SYSTEM_DEPENDENCIES.md`** if it exists
4. **Create deployment documentation** - Explain how it works and why it's needed
5. **Attribution is mandatory** - All software used in deployment must be properly credited

**Example entries for dependency_attribution.md:**

```markdown
### Infrastructure Components

| Component | Version | Purpose | License |
| --- | --- | --- | --- |
| **nginx** | 1.25+ (Alpine) | Reverse proxy for HTTPS termination and Let's Encrypt ACME support | BSD-2-Clause |
| **certbot** | 2.0+ | Automated Let's Encrypt SSL certificate management and renewal | Apache-2.0 |
```

**Why this matters:**
- Open source attribution is a legal requirement for many licenses
- Users need to understand what software is running in their deployment
- Proper documentation helps with security audits and compliance
- Future maintainers need to know what dependencies exist and why

---

## 🔄 Git Workflow

### Versioning Convention

**CRITICAL**: Follow semantic versioning for all releases:

- **Bug Fixes**: Increment patch version by `0.0.+1`
  - Example: `2.3.12` → `2.3.13`
  - Includes: Bug fixes, security patches, minor corrections
  - No new features or breaking changes

- **Feature Upgrades**: Increment minor version by `0.+1.0`
  - Example: `2.3.12` → `2.4.0`
  - Includes: New features, enhancements, non-breaking changes
  - Reset patch version to 0

- **Major Releases**: Increment major version by `+1.0.0` (rare)
  - Example: `2.3.12` → `3.0.0`
  - Includes: Breaking changes, major architecture changes
  - Reset minor and patch versions to 0

**Version File Location**: `/VERSION` (single line, format: `MAJOR.MINOR.PATCH`)

**Before Every Commit**:
1. Update `/VERSION` file with appropriate increment
2. Update `docs/reference/CHANGELOG.md` under `[Unreleased]` section
3. Ensure `.env.example` reflects any new environment variables

### Commit Messages

Follow this format:

```
Short summary (50 chars or less)

More detailed explanation if needed. Wrap at 72 characters.
- Bullet points are okay
- Use imperative mood: "Add feature" not "Added feature"

Fixes #123
```

**Good Examples:**
```
Add dark mode support to system health page

Refactors system_health.html to extend base.html template,
adding theme switching and consistent styling across the app.

Remove duplicate endpoint /admin/calculate_single_alert

This endpoint duplicated functionality from calculate_intersections.
Simplifies codebase by ~60 lines.
```

### Branch Naming

- Feature: `feature/feature-name`
- Bug fix: `fix/bug-description`
- Docs: `docs/what-changed`
- Refactor: `refactor/component-name`

---

## 📖 Code Navigation & Architecture Reference

### Function Tree Documentation

For quick navigation and understanding of the codebase structure, refer to the comprehensive function tree documentation:

- **`docs/reference/FUNCTION_TREE.md`** (Primary Reference)
  - Complete catalog of all major modules, classes, and functions
  - 24 database models, 150+ functions, 98+ classes documented
  - Every entry includes file path, line number, and signature
  - Module dependency graph and database schema overview
  - **Use this to:** Find where specific functions are defined, understand module organization

- **`docs/reference/FUNCTION_TREE_INDEX.md`** (Quick Reference)
  - Quick navigation guide for different user types (developers, agents, operators)
  - Task-based lookup table (e.g., "Add API endpoint" → relevant files)
  - Complete module file structure tree
  - Search tips and common patterns
  - **Use this to:** Quickly find where to add new features or fix bugs

- **`docs/reference/FUNCTION_TREE_SUMMARY.txt`** (Overview)
  - Overview of documentation contents
  - Key statistics and metrics
  - Maintenance guidelines
  - **Use this to:** Understand the scope and coverage of the function tree

### How to Use Function Tree for Development

**When adding a new feature:**
1. Search [docs/reference/FUNCTION_TREE_INDEX.md](../reference/FUNCTION_TREE_INDEX) for similar features
2. Identify the module pattern (e.g., routes in `webapp/`, models in `app_core/`)
3. Follow the established patterns from similar functions
4. Update [docs/reference/FUNCTION_TREE.md](../reference/FUNCTION_TREE) if you add new significant functions or modules

**When fixing a bug:**
1. Search [docs/reference/FUNCTION_TREE.md](../reference/FUNCTION_TREE) for the function/class mentioned in the bug report
2. Note the file path and line number
3. Check related functions in the same module
4. Look for similar patterns in other modules for consistency

**When exploring unfamiliar code:**
1. Start with [docs/reference/FUNCTION_TREE_SUMMARY.txt](../reference/FUNCTION_TREE_SUMMARY.txt) to understand subsystem coverage
2. Use [docs/reference/FUNCTION_TREE_INDEX.md](../reference/FUNCTION_TREE_INDEX) to find the subsystem you're interested in
3. Dive into [docs/reference/FUNCTION_TREE.md](../reference/FUNCTION_TREE) for detailed function signatures and locations

### Known Bugs Documentation

**`docs/reference/KNOWN_BUGS.md`** contains a comprehensive list of identified issues:
- RBAC (Role-Based Access Control) issues
- Text-to-Speech (TTS) configuration issues
- Display Screens page issues
- Environment Settings page issues
- GPIO configuration parsing issues
- Docker/Portainer deployment issues

**Before starting any work:**
1. Check [docs/reference/KNOWN_BUGS.md](../reference/KNOWN_BUGS) to see if your issue is already documented
2. If fixing a bug, remove it from [docs/reference/KNOWN_BUGS.md](../reference/KNOWN_BUGS) in your commit
3. If discovering a new bug, add it to [docs/reference/KNOWN_BUGS.md](../reference/KNOWN_BUGS) with detailed analysis

---

## 🎓 Learning Resources

### Python & Flask
- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy ORM Tutorial](https://docs.sqlalchemy.org/en/20/orm/)
- [PEP 8 Style Guide](https://pep8.org/)

### PostGIS & Spatial
- [PostGIS Documentation](https://postgis.net/documentation/)
- [GeoJSON Specification](https://geojson.org/)
- [GeoAlchemy2 Documentation](https://geoalchemy-2.readthedocs.io/)

### Docker
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Dockerfile Best Practices](https://docs.docker.com/develop/dev-best-practices/)

---

## 🤝 Getting Help

If you're unsure about something:

1. **Check existing code** - Look for similar patterns
2. **Review this document** - Follow established guidelines
3. **Check documentation** - README, code comments, docstrings
4. **Ask questions** - Better to ask than break things

---

## ✅ Pre-Commit Checklist

Before committing code, verify:

- [ ] **Version incremented properly** – Bug fix (+0.0.1) or feature (+0.1.0) in `/VERSION` file
- [ ] **Documentation updated** – If features changed, update `templates/help.html` and `templates/about.html`
- [ ] **Bug screenshots checked** – If fixing a bug, verified screenshot in `/bugs` directory
- [ ] Follows Python PEP 8 style (4-space indentation)
- [ ] Uses existing logger, not new logger instance
- [ ] Includes proper error handling with specific exceptions
- [ ] Bump `VERSION`, mirror `.env.example`, and update `[Unreleased]` in `docs/reference/CHANGELOG.md` for any behavioural change (see `tests/test_release_metadata.py`)
- [ ] Touched files remain within recommended size guidelines or were refactored into smaller units
- [ ] No secrets or credentials in code
- [ ] No `.env` file committed (check git status)
- [ ] Templates extend `base.html` with theme support
- [ ] Database transactions properly handled (commit/rollback)
- [ ] Tested in Docker locally
- [ ] Documentation updated if needed
- [ ] Cross-check docs and UI links (README, Theory of Operation, `/about`, `/help`) for accuracy and live references
- [ ] Commit message follows format guidelines

---

**Remember:** When in doubt, look at existing code patterns and follow them. Consistency is more important than perfection.

---

## 🤖 Agent Activity Log

- 2024-11-12: Repository automation agent reviewed these guidelines before making any changes. All updates in this session comply with the established standards.
- 2025-01-14: Updated AGENTS.md with comprehensive theme system documentation, file naming conventions (_old suffix rule), template structure updates (navbar.html active, navbar_old.html deprecated), and JavaScript theme API functions. Added detailed theme architecture section covering all 11 built-in themes, CSS variable structure, import/export functionality, and dark mode best practices.
