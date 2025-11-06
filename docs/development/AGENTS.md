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

## 🐛 Bug Tracking & Screenshots

When discussing or investigating bugs:

1. **Check `/bugs` Directory First** – Before starting any bug investigation, check the `/bugs` directory for screenshots and other evidence
2. **Screenshots Over Text** – Since AI assistants can't receive images directly in chat, users will place bug screenshots in `/bugs`
3. **Name Descriptively** – Screenshot filenames should indicate the issue (e.g., `admin_spacing_issue.jpeg`, `dark_mode_contrast_bug.png`)
4. **Document Fixes** – When fixing a bug shown in a screenshot, reference the screenshot filename in commit messages
5. **Clean Up After** – Once a bug is fixed and verified, move the screenshot to `/bugs/resolved` or delete it

## 🧭 Documentation & UX Standards

- **Link Accuracy Matters** – Reference primary sources (e.g., FCC consent decrees via `docs.fcc.gov`) instead of news summaries. Broken or redirected links must be updated immediately.
- **Theory of Operation Is Canonical** – Whenever you touch ingestion, SAME generation, or verification logic, review and update [`docs/architecture/THEORY_OF_OPERATION.md`](../architecture/THEORY_OF_OPERATION.md) so diagrams, timelines, and checklists match the code.
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
- **Extract repeated markup** – Move duplicated template fragments into `templates/partials/` and use Flask blueprints or helper modules to share behavior.
- **Stay consistent with existing structure** – Place new Python packages within `app_core/` or `app_utils/` as appropriate, and keep front-end assets organized under `static/` and `templates/` using the same layout patterns as current files.
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
- **Use theme variables** - Reference CSS variables: `var(--primary-color)`, `var(--text-color)`
- **Support dark mode** - Test in both light and dark themes
- **Be responsive** - Use Bootstrap grid classes for mobile support

**Example:**
```html
{% extends "base.html" %}

{% block title %}My Feature - NOAA CAP{% endblock %}

{% block extra_css %}
<style>
    .my-custom-class {
        background-color: var(--bg-color);
        color: var(--text-color);
        border: 1px solid var(--border-color);
    }

    /* Dark mode support */
    [data-theme="dark"] .my-custom-class {
        /* Optional dark mode overrides */
    }
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

- **Use existing global functions** - `showToast()`, `toggleTheme()`, `exportToExcel()`
- **Avoid jQuery** - Use vanilla JavaScript
- **Handle errors gracefully** - Show user-friendly messages

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

1. **Add to `requirements.txt`** - Include version pin
2. **Test in Docker** - Rebuild and verify
3. **Document if needed** - Update README if it affects users
4. **Keep minimal** - Only add if truly necessary

**Example:**
```txt
# requirements.txt
flask==2.3.3
requests==2.31.0
new-library==1.2.3  # Add with version
```

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
