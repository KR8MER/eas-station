# VS Code Local Development Setup Guide

Complete guide for setting up VS Code for local development on the EAS Station project.

> **Note**: This guide is for **local development** (cloning the repo to your local machine). For **remote development** (connecting to a server via SSH), see [VS Code Remote Setup](../../.vscode/VSCODE_SETUP.md).

---

## 📋 Prerequisites

Before starting, ensure you have:

- **Operating System**: Linux (Ubuntu 22.04+, Debian 12+), macOS 12+, or Windows 10/11 with WSL2
- **VS Code**: Version 1.80 or later ([download here](https://code.visualstudio.com/))
- **Python**: Version 3.11, 3.12, or 3.13
- **PostgreSQL**: Version 15+ with PostGIS extension
- **Redis**: Version 6.2 or later
- **Git**: Version 2.30 or later

---

## 🚀 Quick Start (10 Minutes)

### Step 1: Clone the Repository

```bash
# Clone the repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
```

### Step 2: Open in VS Code

**Option A: Use Workspace File (Recommended)**
```bash
# Open the pre-configured workspace
code eas-station.code-workspace
```

**Option B: Open Folder**
```bash
# Open the project folder
code .
```

VS Code will automatically:
- Detect the Python project
- Prompt to install recommended extensions
- Configure settings from `.vscode/settings.json`

### Step 3: Install Recommended Extensions

When you open the workspace, VS Code will prompt:

> **"This workspace has extension recommendations. Would you like to install them?"**

Click **"Install All"** to install:
- Python (ms-python.python)
- Pylance (ms-python.vscode-pylance)
- Python Debugger (ms-python.debugpy)
- Black Formatter (ms-python.black-formatter)
- Flake8 (ms-python.flake8)
- SQLTools (mtxr.sqltools)
- SQLTools PostgreSQL Driver (mtxr.sqltools-driver-pg)
- And more... (see `.vscode/extensions.json`)

### Step 4: Set Up Python Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # Linux/macOS
# or
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Select Python Interpreter in VS Code

1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS)
2. Type: **"Python: Select Interpreter"**
3. Choose: `./venv/bin/python` (or `.\venv\Scripts\python.exe` on Windows)

You should see the interpreter in the bottom-right corner of VS Code.

### Step 6: Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your settings
code .env
```

**Minimum required settings:**
```bash
# Database (PostgreSQL with PostGIS)
DATABASE_URL=postgresql://eas_station:your_password@localhost:5432/alerts

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Flask
FLASK_ENV=development
FLASK_DEBUG=true
SECRET_KEY=your-secret-key-here

# Location (your geographic area)
LOCATION_STATE=CA
LOCATION_COUNTY=San Francisco
```

### Step 7: Set Up Database

**Install PostgreSQL with PostGIS** (if not already installed):

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql-15 postgresql-15-postgis-3
```

**macOS (Homebrew):**
```bash
brew install postgresql@15 postgis
brew services start postgresql@15
```

**Windows:**
Download and install from [PostgreSQL Downloads](https://www.postgresql.org/download/windows/)

**Create Database:**
```bash
# Connect to PostgreSQL
sudo -u postgres psql

# In PostgreSQL shell:
CREATE DATABASE alerts;
CREATE USER eas_station WITH ENCRYPTED PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE alerts TO eas_station;

# Connect to the alerts database
\c alerts

# Enable PostGIS extension
CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;

# Grant schema permissions
GRANT ALL ON SCHEMA public TO eas_station;

# Exit
\q
```

**Run Database Migrations:**
```bash
# Activate virtual environment
source venv/bin/activate

# Run Alembic migrations
alembic upgrade head
```

### Step 8: Set Up Redis

**Install Redis:**

**Ubuntu/Debian:**
```bash
sudo apt install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**macOS (Homebrew):**
```bash
brew install redis
brew services start redis
```

**Windows:**
Download from [Redis for Windows](https://github.com/microsoftarchive/redis/releases)

**Test Redis:**
```bash
redis-cli ping
# Should return: PONG
```

### Step 9: Run the Application

> 💡 **Need help connecting to Flask?** See the detailed guide: **[Connecting to Flask](CONNECTING_TO_FLASK.md)**

**Option A: Using VS Code Debugger (Recommended)**
1. Press `F5`
2. Select: **"Flask Web App (Development)"**
3. Flask will start with debugger attached
4. Open browser: `http://localhost:5000`

**Option B: Using Terminal**
```bash
# Activate virtual environment
source venv/bin/activate

# Run Flask development server
FLASK_ENV=development FLASK_DEBUG=true python app.py
```

**Option C: Using VS Code Task**
1. Press `Ctrl+Shift+P`
2. Type: **"Tasks: Run Task"**
3. Select: **"Flask: Run Development Server"**

**Verify Connection:**
```bash
# Test Flask is responding
curl http://localhost:5000
# Should return HTML content

# Or open in browser
# http://localhost:5000
```

📖 **Full Flask Connection Guide:** [docs/guides/CONNECTING_TO_FLASK.md](CONNECTING_TO_FLASK.md)

---

## 🎨 VS Code Features & Shortcuts

### Essential Keyboard Shortcuts

| Action | Shortcut (Windows/Linux) | Shortcut (macOS) |
|--------|--------------------------|------------------|
| Command Palette | `Ctrl+Shift+P` | `Cmd+Shift+P` |
| Quick Open File | `Ctrl+P` | `Cmd+P` |
| Terminal | `Ctrl+~` | `Cmd+~` |
| New Terminal | `Ctrl+Shift+~` | `Cmd+Shift+~` |
| Run Task | `Ctrl+Shift+B` | `Cmd+Shift+B` |
| Start Debugging | `F5` | `F5` |
| Toggle Breakpoint | `F9` | `F9` |
| Step Over | `F10` | `F10` |
| Step Into | `F11` | `F11` |
| Search in Files | `Ctrl+Shift+F` | `Cmd+Shift+F` |
| Go to Definition | `F12` | `F12` |
| Find References | `Shift+F12` | `Shift+F12` |

### IntelliSense & Autocomplete

VS Code provides intelligent code completion thanks to Pylance:

- **Auto-imports**: Type a class name, and it will auto-import
- **Type hints**: Hover over variables to see types
- **Docstrings**: Press `Ctrl+Space` to see function documentation
- **Parameter hints**: Press `Ctrl+Shift+Space` inside function calls

### Code Navigation

- **Go to Definition**: `F12` or `Ctrl+Click`
- **Peek Definition**: `Alt+F12` - view definition inline
- **Find All References**: `Shift+F12` - see where function is used
- **Go to Symbol**: `Ctrl+Shift+O` - jump to function/class in current file
- **Go to Symbol in Workspace**: `Ctrl+T` - search all files

### Debugging

**Set Breakpoints:**
1. Click the left margin (line number area) to add a red dot
2. Or press `F9` on the line you want to break at

**Start Debugging:**
1. Press `F5`
2. Choose debug configuration:
   - **Flask Web App (Development)** - for web server
   - **Python: Current File** - for scripts
   - **Pytest: Current File** - for tests

**Debug Controls:**
- `F5` - Continue
- `F10` - Step Over (execute current line)
- `F11` - Step Into (enter function)
- `Shift+F11` - Step Out (exit function)
- `Ctrl+Shift+F5` - Restart
- `Shift+F5` - Stop

**Debug Panels:**
- **Variables** - see all local/global variables
- **Watch** - monitor specific expressions
- **Call Stack** - see execution path
- **Breakpoints** - manage all breakpoints
- **Debug Console** - execute Python expressions

---

## 🗄️ Database Management in VS Code

### Using SQLTools Extension

The SQLTools extension provides a graphical database client.

**Setup Connection:**
1. Click **SQLTools** icon in left sidebar (database icon)
2. Click **"Add New Connection"**
3. Select **PostgreSQL**
4. Enter connection details:
   - **Connection name**: `EAS Station Local`
   - **Server**: `localhost`
   - **Port**: `5432`
   - **Database**: `alerts`
   - **Username**: `eas_station`
   - **Password**: (from your `.env` file)
   - **Use SSL**: `Disabled` (for local development)
5. Click **"Test Connection"** then **"Save Connection"**

**Using SQLTools:**
- **Browse Tables**: Expand connection → Tables
- **View Data**: Right-click table → **"Show Table Records"**
- **Run Query**: Click **"New SQL File"**, write query, press `Ctrl+E Ctrl+E`
- **Export Results**: Right-click results → **"Save Results"** (CSV, JSON, or Excel)

**Example Queries:**
```sql
-- Count all alerts
SELECT COUNT(*) FROM cap_alerts;

-- Show recent alerts
SELECT id, event, headline, sent 
FROM cap_alerts 
ORDER BY sent DESC 
LIMIT 10;

-- Find alerts for specific county
SELECT event, headline, sent
FROM cap_alerts
WHERE areas @> '[{"geocode": {"SAME": ["006075"]}}]'::jsonb
ORDER BY sent DESC;

-- Show active alerts
SELECT id, event, headline, expires
FROM cap_alerts
WHERE expires > NOW()
  AND status = 'Actual'
ORDER BY expires ASC;
```

### Using Terminal

```bash
# Connect to database
psql -h localhost -U eas_station -d alerts

# Or use environment variable
export DATABASE_URL="postgresql://eas_station:password@localhost:5432/alerts"
psql $DATABASE_URL
```

**Common psql commands:**
```sql
\dt              -- List all tables
\d cap_alerts    -- Describe table structure
\du              -- List users
\l               -- List databases
\q               -- Quit
```

---

## 🧪 Testing

### Running Tests

**Option 1: Using VS Code Test Explorer**
1. Click the **Testing** icon in left sidebar (flask icon)
2. Click **"Configure Python Tests"**
3. Select **"pytest"**
4. Select **"tests"** directory
5. Tests will appear in the sidebar
6. Click the play button to run tests

**Option 2: Using Debug Configuration**
1. Open a test file (e.g., `tests/test_alerts.py`)
2. Press `F5`
3. Select **"Pytest: Current File"**
4. Tests run with debugger attached

**Option 3: Using Terminal**
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_alerts.py -v

# Run specific test function
pytest tests/test_alerts.py::test_cap_parser -v

# Run with coverage
pytest tests/ --cov=app_core --cov-report=html
# Open htmlcov/index.html to see coverage report
```

### Writing Tests

Tests should be placed in the `tests/` directory and follow pytest conventions:

```python
# tests/test_example.py
import pytest
from app_core.models import CAPAlert

def test_alert_creation(app_context):
    """Test creating a CAP alert."""
    alert = CAPAlert(
        identifier="test-alert-001",
        event="Severe Thunderstorm Warning",
        headline="Test alert"
    )
    assert alert.identifier == "test-alert-001"
    assert alert.event == "Severe Thunderstorm Warning"

@pytest.fixture
def app_context():
    """Provide Flask application context for tests."""
    from app import app
    with app.app_context():
        yield app
```

---

## 🔧 Available VS Code Tasks

Press `Ctrl+Shift+P` → **"Tasks: Run Task"** to access these:

### Development Tasks
- **Flask: Run Development Server** - Start Flask with auto-reload
- **Flask: Stop Development Server** - Stop the dev server
- **Run Pytest** - Execute all tests
- **Run Flake8** - Check code style

### Database Tasks
- **Database: Connect with psql** - Open PostgreSQL shell
- **Database: Show Alert Count** - Count alerts in database
- **Database: Show Recent Alerts** - Show last 10 alerts
- **Database: Show Tables** - List all database tables
- **Database: Show Connection Info** - Display connection details

### Redis Tasks
- **Redis: Check Status** - Test Redis connection
- **Redis: Monitor Commands (Live)** - Watch Redis commands in real-time
- **Redis: List All Keys** - Show all Redis keys
- **Redis: Show Info** - Display Redis server info

### Utility Tasks
- **Install Python Dependencies** - Run `pip install -r requirements.txt`
- **Show System Information** - Display Python version, disk usage, etc.

---

## 🎨 Code Formatting & Linting

### Black (Code Formatter)

Black is configured to format Python code automatically.

**Manual Formatting:**
- Press `Shift+Alt+F` (Windows/Linux) or `Shift+Option+F` (macOS)
- Or right-click → **"Format Document"**

**Auto-Format on Save:**
Already configured in `.vscode/settings.json`:
```json
{
  "[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter",
    "editor.formatOnSave": false
  }
}
```

**Note**: Auto-format on save is **disabled** by default to preserve existing code style. Enable it by changing `false` to `true`.

### Flake8 (Linter)

Flake8 checks for code quality issues.

**View Problems:**
- Press `Ctrl+Shift+M` to open **Problems** panel
- Issues appear with squiggly underlines in editor

**Run Manually:**
```bash
# Run Flake8 on entire codebase
flake8 app.py app_core/ app_utils/ webapp/ --max-line-length=120

# Or use the VS Code task:
# Ctrl+Shift+P → Tasks: Run Task → Run Flake8
```

**Flake8 Configuration:**
Settings are in `.vscode/settings.json`:
```json
{
  "flake8.args": [
    "--max-line-length=120",
    "--ignore=E501,W503"
  ]
}
```

---

## 🐛 Debugging Tips

### Debug Flask Routes

1. Open the route file (e.g., `webapp/admin/alerts.py`)
2. Set a breakpoint in the route function
3. Press `F5` → **"Flask Web App (Development)"**
4. Make a request to that route in your browser
5. VS Code will pause at your breakpoint

**Example:**
```python
# webapp/admin/alerts.py
@bp.route('/alerts')
def list_alerts():
    alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(50).all()
    # Set breakpoint here ← Click margin to add breakpoint
    return render_template('admin/alerts.html', alerts=alerts)
```

### Debug Background Services

For non-Flask services (poller, audio, hardware):

1. Open the service file (e.g., `eas_monitoring_service.py`)
2. Set breakpoints
3. Press `F5` → Select appropriate configuration:
   - **EAS Monitoring Service**
   - **Hardware Service**
   - **SDR Hardware Service**

### Debug Database Queries

Use the **Debug Console** to execute SQLAlchemy queries:

```python
# In Debug Console (when paused at breakpoint):
from app_core.models import CAPAlert
CAPAlert.query.count()
# Returns: 42

CAPAlert.query.filter_by(event='Tornado Warning').all()
# Returns: [<CAPAlert id=1>, <CAPAlert id=2>]
```

### Common Debugging Scenarios

**Problem: "Module not found" error**
- **Solution**: Ensure virtual environment is activated
- Check interpreter: `Ctrl+Shift+P` → **"Python: Select Interpreter"**

**Problem: Breakpoint not hit**
- **Solution**: Make sure you're running with debugger (`F5`), not terminal
- Check that the code path is actually executed

**Problem: Database connection error**
- **Solution**: Check `.env` file for correct `DATABASE_URL`
- Test connection: `psql -h localhost -U eas_station -d alerts`

**Problem: Port already in use**
- **Solution**: Find and kill the process using port 5000
  ```bash
  # Linux/macOS
  lsof -ti:5000 | xargs kill -9
  
  # Windows
  netstat -ano | findstr :5000
  taskkill /PID <PID> /F
  ```

---

## 🔄 Git Workflow in VS Code

### Source Control Panel

Click the **Source Control** icon in the left sidebar (or press `Ctrl+Shift+G`).

**Stage Changes:**
- Click `+` next to a file to stage it
- Click `+` in "Changes" header to stage all

**Commit:**
1. Write commit message in the text box
2. Click ✓ **Commit** button
3. Or press `Ctrl+Enter`

**Push/Pull:**
- Click `...` (More Actions) → **Push** or **Pull**
- Or use **Sync Changes** button

**View Diff:**
- Click a file in Source Control panel to see changes
- Use the diff view to review before committing

### GitLens Extension

If you installed GitLens (recommended), you get:

- **Blame annotations** - see who changed each line
- **File history** - view all commits that touched a file
- **Compare branches** - see differences between branches
- **Commit graph** - visual representation of commits

**Usage:**
- Hover over a line to see who last changed it
- Click **GitLens** in the bottom bar for more options

### Recommended Git Commands

```bash
# Create a new branch
git checkout -b feature/my-new-feature

# See current branch and status
git status

# Stage and commit
git add .
git commit -m "Add new feature"

# Push to GitHub
git push origin feature/my-new-feature

# Update from main
git checkout main
git pull origin main
git checkout feature/my-new-feature
git merge main
```

---

## 📦 Dependency Management

### Adding New Dependencies

1. **Add to `requirements.txt`** with version pin:
   ```
   new-package==1.2.3
   ```

2. **Install the package:**
   ```bash
   pip install new-package==1.2.3
   ```

3. **Update requirements** (if using pip-tools):
   ```bash
   pip freeze > requirements.txt
   ```

4. **Document the dependency** in relevant docs

### Updating Dependencies

**Check for outdated packages:**
```bash
pip list --outdated
```

**Update a specific package:**
```bash
pip install --upgrade package-name
pip freeze > requirements.txt
```

**Security Updates:**
```bash
# Check for security vulnerabilities
pip-audit

# Update vulnerable packages
pip install --upgrade vulnerable-package
```

---

## 🔐 Security Best Practices

### Never Commit Secrets

The `.env` file is in `.gitignore` - **never remove it from there!**

**Check before committing:**
```bash
# Make sure .env is not staged
git status

# Search for potential secrets
git diff | grep -i "password\|secret\|key"
```

### Use Environment Variables

**Good:**
```python
import os
DATABASE_URL = os.getenv('DATABASE_URL')
```

**Bad:**
```python
DATABASE_URL = 'postgresql://user:password@localhost/db'  # NEVER DO THIS!
```

### Secure Development Server

The Flask development server is **not secure** for production:
- Only bind to `localhost` (default)
- Don't expose port 5000 to the internet
- Use HTTPS in production (nginx + certbot)

---

## 🎓 Learning Resources

### VS Code Documentation
- [VS Code Python Tutorial](https://code.visualstudio.com/docs/python/python-tutorial)
- [Debugging in VS Code](https://code.visualstudio.com/docs/editor/debugging)
- [Version Control in VS Code](https://code.visualstudio.com/docs/editor/versioncontrol)

### EAS Station Documentation
- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)
- [Theory of Operation](../architecture/THEORY_OF_OPERATION.md)
- [Developer Guidelines](../development/AGENTS.md)
- [Remote Development Setup](../../.vscode/VSCODE_SETUP.md)

### Python & Flask
- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Python Style Guide (PEP 8)](https://pep8.org/)

---

## 🆘 Troubleshooting

### VS Code Won't Start

**Problem**: VS Code crashes or won't open

**Solutions:**
1. **Clear VS Code cache:**
   ```bash
   # Linux/macOS
   rm -rf ~/.config/Code/Cache
   rm -rf ~/.config/Code/CachedData
   
   # Windows
   rmdir /s %APPDATA%\Code\Cache
   rmdir /s %APPDATA%\Code\CachedData
   ```

2. **Reinstall extensions:**
   ```bash
   code --uninstall-extension <extension-id>
   code --install-extension <extension-id>
   ```

### Python Extension Not Working

**Problem**: IntelliSense, debugging, or linting not working

**Solutions:**
1. **Reload window**: `Ctrl+Shift+P` → **"Developer: Reload Window"**
2. **Restart Python language server**: `Ctrl+Shift+P` → **"Python: Restart Language Server"**
3. **Check interpreter**: `Ctrl+Shift+P` → **"Python: Select Interpreter"** → Choose `./venv/bin/python`
4. **Reinstall Pylance**: `Ctrl+Shift+X` → Search "Pylance" → Uninstall → Install

### Database Connection Fails

**Problem**: Cannot connect to PostgreSQL

**Solutions:**
1. **Check PostgreSQL is running:**
   ```bash
   # Linux
   sudo systemctl status postgresql
   
   # macOS
   brew services list | grep postgresql
   
   # Windows
   services.msc  # Check PostgreSQL service
   ```

2. **Test connection manually:**
   ```bash
   psql -h localhost -U eas_station -d alerts
   ```

3. **Check `.env` file** for correct credentials

4. **Check PostgreSQL logs:**
   ```bash
   # Linux
   sudo tail -f /var/log/postgresql/postgresql-15-main.log
   
   # macOS
   tail -f /usr/local/var/log/postgres.log
   ```

### Redis Connection Fails

**Problem**: Cannot connect to Redis

**Solutions:**
1. **Check Redis is running:**
   ```bash
   redis-cli ping
   # Should return: PONG
   ```

2. **Start Redis:**
   ```bash
   # Linux
   sudo systemctl start redis-server
   
   # macOS
   brew services start redis
   
   # Windows
   redis-server
   ```

3. **Check Redis logs:**
   ```bash
   # Linux
   sudo journalctl -u redis-server -f
   
   # macOS
   tail -f /usr/local/var/log/redis.log
   ```

### Flask Won't Start

**Problem**: Flask development server fails to start

**Solutions:**
1. **Check port 5000 is available:**
   ```bash
   # Linux/macOS
   lsof -ti:5000
   
   # Windows
   netstat -ano | findstr :5000
   ```

2. **Check `.env` file exists** and has required variables

3. **Check database migrations are up to date:**
   ```bash
   alembic upgrade head
   ```

4. **View detailed error:**
   ```bash
   FLASK_ENV=development FLASK_DEBUG=true python app.py
   ```

### Slow IntelliSense

**Problem**: Autocomplete is very slow

**Solutions:**
1. **Exclude large directories** from search:
   Add to `.vscode/settings.json`:
   ```json
   {
     "files.watcherExclude": {
       "**/venv/**": true,
       "**/node_modules/**": true,
       "**/__pycache__/**": true,
       "**/logs/**": true
     }
   }
   ```

2. **Disable unused extensions** temporarily

3. **Increase VS Code memory limit:**
   Add to VS Code settings (JSON):
   ```json
   {
     "python.analysis.memory.keepLibraryAst": false
   }
   ```

---

## 📞 Getting Help

### Internal Resources
- **Repository Issues**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
- **Discussions**: [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
- **Documentation**: See `docs/` directory

### External Resources
- **VS Code Support**: [VS Code Issues](https://github.com/microsoft/vscode/issues)
- **Python Extension**: [Python Extension Issues](https://github.com/microsoft/vscode-python/issues)
- **Stack Overflow**: Tag questions with `[vscode] [python] [flask]`

---

## ✅ Setup Verification Checklist

After completing setup, verify everything works:

- [ ] VS Code opens the workspace without errors
- [ ] Python interpreter is set to `./venv/bin/python`
- [ ] All recommended extensions are installed
- [ ] IntelliSense works (hover over code shows types)
- [ ] Can set breakpoints and start debugger with `F5`
- [ ] Database connection works (SQLTools connects successfully)
- [ ] Redis connection works (`redis-cli ping` returns PONG)
- [ ] Flask development server starts successfully
- [ ] Can access application at `http://localhost:5000`
- [ ] Tests run successfully (`pytest tests/`)
- [ ] Git integration works (Source Control panel shows changes)

**All checked?** 🎉 **You're ready to develop!**

---

**Happy Coding!** 🚀

*For questions or issues with this guide, please [open an issue](https://github.com/KR8MER/eas-station/issues) or start a [discussion](https://github.com/KR8MER/eas-station/discussions).*
