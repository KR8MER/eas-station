# Contributing to EAS Station

Thank you for your interest in contributing to EAS Station! This document provides guidelines for contributing to the project.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [Making Changes](#making-changes)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Submitting Changes](#submitting-changes)
- [Review Process](#review-process)

---

## 🤝 Code of Conduct

This project adheres to a code of conduct that we expect all contributors to follow:

- **Be respectful**: Treat everyone with respect. No harassment, discrimination, or personal attacks.
- **Be constructive**: Provide constructive feedback and be open to receiving it.
- **Be collaborative**: Work together to achieve the best outcome for the project.
- **Be professional**: Keep discussions focused on technical matters.

---

## 🚀 Getting Started

### Prerequisites

Before contributing, ensure you have:

- **Git** installed and configured
- **GitHub account** with SSH keys set up
- **Python 3.11+** installed
- **VS Code** (recommended) or another IDE
- **PostgreSQL 15+** with PostGIS extension
- **Redis 6.2+** for caching and state management

### Fork and Clone

1. **Fork the repository** on GitHub (click "Fork" button)

2. **Clone your fork:**
   ```bash
   git clone git@github.com:YOUR_USERNAME/eas-station.git
   cd eas-station
   ```

3. **Add upstream remote:**
   ```bash
   git remote add upstream git@github.com:KR8MER/eas-station.git
   ```

4. **Verify remotes:**
   ```bash
   git remote -v
   # origin    git@github.com:YOUR_USERNAME/eas-station.git (fetch)
   # origin    git@github.com:YOUR_USERNAME/eas-station.git (push)
   # upstream  git@github.com:KR8MER/eas-station.git (fetch)
   # upstream  git@github.com:KR8MER/eas-station.git (push)
   ```

---

## 💻 Development Environment

### Option 1: VS Code Local Setup (Recommended)

Follow our comprehensive guide: **[VS Code Local Setup Guide](docs/guides/VSCODE_LOCAL_SETUP.md)**

**Quick start:**
```bash
# Open the pre-configured workspace
code eas-station.code-workspace

# Install recommended extensions when prompted
# Select Python interpreter: ./venv/bin/python
```

### Option 2: VS Code Remote Development

For working on a remote server via SSH: **[VS Code Remote Setup](.vscode/VSCODE_SETUP.md)**

### Option 3: Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your configuration

# Set up database
# See docs/guides/VSCODE_LOCAL_SETUP.md for PostgreSQL setup

# Run migrations
alembic upgrade head

# Start development server
FLASK_ENV=development FLASK_DEBUG=true python app.py
```

---

## 🔧 Making Changes

### Creating a Branch

Always create a new branch for your changes:

```bash
# Update your main branch
git checkout main
git pull upstream main

# Create a new branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

**Branch naming conventions:**
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions/improvements

### Making Commits

**Commit message format:**
```
Brief summary (50 characters or less)

More detailed explanation if needed (wrap at 72 characters).
Explain what changed, why, and any relevant context.

Fixes #123
```

**Commit message guidelines:**
- Use imperative mood ("Add feature" not "Added feature")
- First line is a brief summary (50 chars max)
- Separate summary from body with blank line
- Body wraps at 72 characters
- Reference related issues (e.g., "Fixes #123")

**Examples:**
```bash
# Good commit messages
git commit -m "Add spatial filtering for CAP alerts"
git commit -m "Fix Redis connection timeout in audio service"
git commit -m "Update documentation for SAME encoding"

# Bad commit messages (avoid these)
git commit -m "Fixed stuff"
git commit -m "WIP"
git commit -m "asdfasdf"
```

### Versioning

Update the `VERSION` file before committing:

- **Bug fixes**: Increment patch version (e.g., `2.43.4` → `2.43.5`)
- **New features**: Increment minor version (e.g., `2.43.4` → `2.44.0`)
- **Breaking changes**: Increment major version (e.g., `2.43.4` → `3.0.0`)

Also update `docs/reference/CHANGELOG.md` under the `[Unreleased]` section.

---

## 📝 Coding Standards

### Python Style

**Follow PEP 8** with these specific guidelines:

- **Indentation**: 4 spaces (no tabs)
- **Line length**: 120 characters maximum
- **Naming conventions**:
  - Functions and variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
- **Imports**: Group by standard library, third-party, local
- **Docstrings**: Use triple quotes for all functions and classes

**Example:**
```python
from datetime import datetime
from flask import Blueprint, jsonify
from app_core.models import CAPAlert

logger = logging.getLogger('eas_station')

@bp.route('/api/alerts')
def get_alerts():
    """
    Retrieve recent CAP alerts from database.
    
    Returns:
        JSON response with alert data
    """
    try:
        alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(50).all()
        return jsonify({'success': True, 'alerts': [a.to_dict() for a in alerts]}), 200
    except Exception as e:
        logger.error(f'Error retrieving alerts: {str(e)}')
        return jsonify({'error': str(e)}), 500
```

### Logging

**Always use the existing logger:**
```python
# Good
logger = logging.getLogger('eas_station')
logger.info('Processing alert')

# Bad - DO NOT create new loggers
logger = logging.getLogger(__name__)  # ❌ WRONG
```

### Error Handling

**Always handle database transactions properly:**
```python
try:
    # Database operations
    db.session.add(alert)
    db.session.commit()
    logger.info('Alert saved successfully')
except SQLAlchemyError as e:
    db.session.rollback()
    logger.error(f'Database error: {str(e)}')
    raise
```

### Configuration

**ALL configuration must be database-based:**
- NO hardcoded credentials
- NO environment variables for user settings
- Use settings models in `app_core/models.py`
- Create admin UI for all settings

**Example:**
```python
# Good - Database-backed configuration
from app_core.models import LocationSettings

settings = LocationSettings.query.first()
if settings.enabled:
    process_alerts()

# Bad - Hardcoded or environment variables
ENABLED = True  # ❌ WRONG
ENABLED = os.getenv('ENABLED')  # ❌ WRONG (for user settings)
```

### Frontend Requirements

**CRITICAL**: Every backend feature MUST have a frontend UI.

**When adding a feature:**
1. Create API endpoint
2. Create web UI page
3. Add to navigation menu in `templates/base.html`
4. Use dropdowns/radio buttons for binary choices (never text inputs)
5. Test end-to-end through the web interface

**Example:**
```html
<!-- Good - Dropdown for binary choice -->
<select class="form-select" name="enabled">
    <option value="true">Enabled</option>
    <option value="false">Disabled</option>
</select>

<!-- Bad - Text input for binary choice -->
<input type="text" name="enabled" placeholder="true or false">  ❌ WRONG
```

---

## 🧪 Testing

### Running Tests

**Run all tests:**
```bash
pytest tests/ -v
```

**Run specific test file:**
```bash
pytest tests/test_alerts.py -v
```

**Run with coverage:**
```bash
pytest tests/ --cov=app_core --cov-report=html
# View coverage report: open htmlcov/index.html
```

### Writing Tests

Place tests in the `tests/` directory:

```python
# tests/test_example.py
import pytest
from app_core.models import CAPAlert

def test_alert_creation():
    """Test creating a CAP alert."""
    alert = CAPAlert(
        identifier="test-001",
        event="Tornado Warning",
        headline="Test alert"
    )
    assert alert.identifier == "test-001"
    assert alert.event == "Tornado Warning"

@pytest.fixture
def sample_alert():
    """Provide a sample alert for tests."""
    return CAPAlert(
        identifier="test-002",
        event="Flash Flood Warning",
        headline="Test flood alert"
    )
```

### Test Coverage Requirements

- New features should have tests
- Bug fixes should include regression tests
- Aim for >80% code coverage on new code

---

## 📚 Documentation

### When to Update Documentation

Update documentation when:
- Adding new features
- Changing existing behavior
- Fixing bugs that affect user workflows
- Adding/removing dependencies

### Files to Update

- **`docs/guides/`** - User guides and tutorials
- **`docs/reference/CHANGELOG.md`** - Add entry under `[Unreleased]`
- **`templates/help.html`** - User-facing help
- **`templates/about.html`** - Feature descriptions
- **`README.md`** - If major features change

### Documentation Style

- Use Markdown format
- Include code examples
- Add screenshots for UI features
- Keep it concise and clear

**Example:**
````markdown
## New Feature: Alert Filtering

You can now filter alerts by event type:

```python
from app_core.models import CAPAlert

# Filter by event type
alerts = CAPAlert.query.filter_by(event='Tornado Warning').all()
```

**Web UI**: Navigate to **Analytics** → **Alert Filters** to configure.
````

---

## 📤 Submitting Changes

### Before Submitting

**Pre-submission checklist:**

- [ ] Code follows style guidelines
- [ ] All tests pass (`pytest tests/`)
- [ ] New features have tests
- [ ] Documentation is updated
- [ ] `VERSION` file is updated
- [ ] `CHANGELOG.md` is updated
- [ ] No secrets or credentials in code
- [ ] Commit messages are clear
- [ ] Branch is up to date with `main`

### Creating a Pull Request

1. **Push your branch:**
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create Pull Request on GitHub:**
   - Go to your fork on GitHub
   - Click "Compare & pull request"
   - Fill out the PR template
   - Provide clear description of changes
   - Link related issues

3. **PR Title Format:**
   ```
   [Feature] Add spatial alert filtering
   [Fix] Resolve Redis connection timeout
   [Docs] Update installation guide
   ```

4. **PR Description Template:**
   ```markdown
   ## Description
   Brief description of what this PR does.

   ## Changes Made
   - Added feature X
   - Fixed bug Y
   - Updated documentation Z

   ## Testing
   - [ ] All tests pass
   - [ ] New tests added
   - [ ] Tested manually on [OS/Platform]

   ## Related Issues
   Fixes #123
   Related to #456

   ## Screenshots (if applicable)
   [Add screenshots here]
   ```

---

## 🔍 Review Process

### What to Expect

1. **Automated Checks**: GitHub Actions will run tests automatically
2. **Code Review**: Maintainers will review your code
3. **Feedback**: You may receive requests for changes
4. **Approval**: Once approved, your PR will be merged

### Responding to Feedback

- Address all review comments
- Push additional commits to your branch
- **Don't force-push** after submitting PR (makes review harder)
- Be patient and respectful

### After Merge

- Your changes will be included in the next release
- Delete your branch locally and on GitHub
- Update your local main:
  ```bash
  git checkout main
  git pull upstream main
  ```

---

## 🎯 Good First Issues

Looking for a place to start? Check out issues labeled:
- `good first issue` - Good for newcomers
- `help wanted` - Contributions welcome
- `documentation` - Documentation improvements

---

## 💡 Tips for Contributors

### Development Best Practices

1. **Keep PRs focused**: One feature or fix per PR
2. **Test locally**: Always test before pushing
3. **Use VS Code**: Leverage the pre-configured workspace
4. **Read existing code**: Learn from the codebase
5. **Ask questions**: Use GitHub Discussions if unsure

### Using VS Code Effectively

- **Snippets**: Type `eas-` to see available code snippets
- **Tasks**: Press `Ctrl+Shift+P` → "Tasks: Run Task"
- **Debugging**: Press `F5` to start debugger
- **Extensions**: Install all recommended extensions

### Database Migrations

When changing models, create a migration:

```bash
# Create migration
alembic revision --autogenerate -m "Add new field to CAPAlert"

# Review the migration file in alembic/versions/

# Apply migration
alembic upgrade head
```

### Working with Git

**Keep your fork up to date:**
```bash
# Fetch upstream changes
git fetch upstream

# Update your main branch
git checkout main
git merge upstream/main
git push origin main

# Update your feature branch
git checkout feature/your-feature
git merge main
```

**Resolving merge conflicts:**
```bash
# If you have conflicts after merging main
git status  # See conflicted files
# Edit files to resolve conflicts
git add <resolved-files>
git commit
```

---

## 📞 Getting Help

### Communication Channels

- **GitHub Issues**: Report bugs and request features
- **GitHub Discussions**: Ask questions and share ideas
- **Documentation**: Check `docs/` directory first

### Questions?

If you have questions about contributing:

1. Check existing documentation
2. Search GitHub Issues and Discussions
3. Open a new Discussion with the "Q&A" category
4. Be specific and provide context

---

## 📄 License

By contributing to EAS Station, you agree that your contributions will be licensed under:
- **AGPL v3** for open source use
- **Commercial License** available separately

See [LICENSE](LICENSE) and [LICENSE-COMMERCIAL](LICENSE-COMMERCIAL) for details.

### Developer Certificate of Origin (DCO)

This project uses a Developer Certificate of Origin workflow. Each commit must contain a `Signed-off-by` line, which you can add automatically with `git commit -s`.

**Example commit message:**
```
Add new alert visualization panel

Improve the admin dashboard by adding visualization.

Signed-off-by: Your Name <you@example.com>
```

The signature certifies that you wrote the code or have the rights to pass it on under the project license. See [developercertificate.org](https://developercertificate.org/) for details.

---

## 🙏 Thank You!

Thank you for contributing to EAS Station! Your efforts help make emergency alerting more accessible and reliable.

**Questions or suggestions about this guide?** Open an issue or discussion on GitHub.

---

**Quick Links:**
- [VS Code Local Setup](docs/guides/VSCODE_LOCAL_SETUP.md)
- [VS Code Remote Setup](.vscode/VSCODE_SETUP.md)
- [Developer Guidelines](docs/development/AGENTS.md)
- [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
