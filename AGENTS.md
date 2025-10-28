# AI Agent Development Guidelines

This document provides coding standards and guidelines for AI agents (including Claude, GitHub Copilot, Cursor, and other AI assistants) when working on the NOAA CAP Emergency Alert System codebase.

---

## 🎯 Core Principles

1. **Safety First**: Never commit secrets, API keys, or sensitive data
2. **Preserve Existing Patterns**: Follow the established code style and architecture
3. **Test Before Commit**: Always verify changes work in Docker before committing
4. **Focused Changes**: Keep fixes targeted to the specific issue
5. **Document Changes**: Update relevant documentation when adding features
   - Always record user-facing updates in `CHANGELOG.md` as part of each pull request

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
docker compose build
docker compose up -d
docker compose logs -f app

# Check for errors
docker compose ps
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
- [ ] Docker build succeeds: `docker compose build`
- [ ] Application starts without errors: `docker compose up -d`
- [ ] Health check passes: `curl http://localhost:5000/health`
- [ ] Logs show no errors: `docker compose logs -f app`
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

### Environment Variable Hygiene

- **Update `.env.example`** whenever you add a new configuration flag so operators know how to enable it.
- **Document usage** in the README or module docstring if the variable changes runtime behaviour.
- **Keep secrets out of the repo** – only placeholders or instructions belong in `.env.example`.

---

## 🔄 Git Workflow

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

- [ ] Follows Python PEP 8 style (4-space indentation)
- [ ] Uses existing logger, not new logger instance
- [ ] Includes proper error handling with specific exceptions
- [ ] No secrets or credentials in code
- [ ] No `.env` file committed (check git status)
- [ ] Templates extend `base.html` with theme support
- [ ] Database transactions properly handled (commit/rollback)
- [ ] Tested in Docker locally
- [ ] Documentation updated if needed
- [ ] `CHANGELOG.md` updated with user-facing changes (or explicitly confirmed not needed)
- [ ] Commit message follows format guidelines

---

**Remember:** When in doubt, look at existing code patterns and follow them. Consistency is more important than perfection.
