# VS Code Setup - Quick Reference

Quick overview of all VS Code development resources available for EAS Station.

---

## 📁 Files Created

### Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| **Workspace File** | `eas-station.code-workspace` | Pre-configured workspace with all settings, tasks, and debug configs |
| **Code Snippets** | `.vscode/eas-station.code-snippets` | 20+ code snippets for common patterns (type `eas-` to use) |
| **Settings** | `.vscode/settings.json` | Python, linting, formatting, and database configuration |
| **Launch Config** | `.vscode/launch.json` | Debug configurations for all services |
| **Tasks** | `.vscode/tasks.json` | Common tasks (Flask dev server, tests, database, Redis) |
| **Extensions** | `.vscode/extensions.json` | Recommended VS Code extensions |

### Documentation

| Document | Location | Audience |
|----------|----------|----------|
| **Local Setup Guide** | `docs/guides/VSCODE_LOCAL_SETUP.md` | Developers setting up locally |
| **Remote Setup Guide** | `.vscode/VSCODE_SETUP.md` | Developers using SSH |
| **Contributing Guide** | `CONTRIBUTING.md` | Contributors (includes VS Code workflow) |
| **Quick Reference** | `.vscode/QUICK_REFERENCE.md` | Quick command lookup |

---

## 🚀 Getting Started (3 Options)

### Option 1: Local Development (Recommended for Contributors)

**Best for:** Writing code, running tests, debugging locally

```bash
# 1. Clone repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# 2. Open workspace in VS Code
code eas-station.code-workspace

# 3. Install extensions when prompted
# 4. Select Python interpreter: ./venv/bin/python
# 5. Press F5 to debug!
```

**Full Guide:** [docs/guides/VSCODE_LOCAL_SETUP.md](docs/guides/VSCODE_LOCAL_SETUP.md)

### Option 2: Remote Development (Best for Raspberry Pi)

**Best for:** Working on actual hardware, testing GPIO/SDR, remote server development

```bash
# 1. Install Remote-SSH extension in VS Code
# 2. Connect to server: F1 → Remote-SSH: Connect to Host
# 3. Enter: eas-station@your-server-ip
# 4. Open folder: /opt/eas-station
# 5. Select interpreter: /opt/eas-station/venv/bin/python
```

**Full Guide:** [.vscode/VSCODE_SETUP.md](.vscode/VSCODE_SETUP.md)

### Option 3: Quick File Editing

**Best for:** Quick fixes, viewing code without full setup

```bash
# Just open the folder
code .
```

---

## 🎯 What You Get

### Pre-Configured Workspace

✅ Python interpreter automatically detected  
✅ All paths configured (PYTHONPATH, imports work correctly)  
✅ Database connection ready (SQLTools)  
✅ Debug configurations for all services  
✅ Tasks for common operations  
✅ Linting and formatting configured  
✅ Git integration enabled  
✅ Extension recommendations  

### Code Snippets (Type `eas-` to trigger)

**Python Snippets:**
- `eas-route` - Flask route with database query
- `eas-route-form` - Flask route with form handling
- `eas-model` - SQLAlchemy database model
- `eas-settings-model` - Settings model for database-backed config
- `eas-try-db` - Try-except with database rollback
- `eas-redis` - Redis get/set operations
- `eas-logger` - Logging configuration
- `eas-blueprint` - Flask Blueprint
- `eas-test` - Pytest test function
- `eas-migration` - Alembic migration

**Template Snippets:**
- `eas-admin-form` - Admin settings form template
- `eas-jinja-block` - Jinja2 block
- `eas-jinja-for` - Jinja2 for loop
- `eas-jinja-if` - Jinja2 if statement
- `eas-card` - Bootstrap card
- `eas-alert` - Bootstrap alert

### Debug Configurations (Press F5)

- **Flask Web App (Development)** - Debug Flask with auto-reload
- **FastAPI App (Development)** - Debug FastAPI/Uvicorn
- **EAS Monitoring Service** - Debug audio monitoring
- **Hardware Service** - Debug GPIO/hardware
- **Python: Current File** - Debug any Python script
- **Pytest: Current File** - Debug tests
- **Pytest: All Tests** - Debug entire test suite

### Tasks (Ctrl+Shift+P → Tasks: Run Task)

**Development:**
- Flask: Run Development Server
- Run Pytest
- Run Flake8
- Install Python Dependencies
- Run Alembic Migrations

**Database:**
- Database: Show Alert Count
- Database: Show Recent Alerts

**Redis:**
- Redis: Check Status
- Redis: List All Keys

---

## 📖 Documentation Structure

```
eas-station/
├── eas-station.code-workspace      # Open this in VS Code!
├── CONTRIBUTING.md                 # How to contribute (includes VS Code workflow)
│
├── .vscode/
│   ├── settings.json               # Workspace settings
│   ├── launch.json                 # Debug configurations
│   ├── tasks.json                  # Common tasks
│   ├── extensions.json             # Extension recommendations
│   ├── eas-station.code-snippets   # Code snippets
│   ├── VSCODE_SETUP.md            # Remote development guide
│   ├── QUICK_REFERENCE.md          # Quick command lookup
│   └── README.md                   # .vscode directory overview
│
└── docs/
    └── guides/
        ├── VSCODE_LOCAL_SETUP.md   # Local development guide (comprehensive)
        └── COPILOT_DEBUGGING_VSCODE.md  # AI-assisted debugging
```

---

## ⌨️ Essential Shortcuts

| Action | Windows/Linux | macOS |
|--------|---------------|-------|
| Command Palette | `Ctrl+Shift+P` | `Cmd+Shift+P` |
| Quick Open | `Ctrl+P` | `Cmd+P` |
| Terminal | `Ctrl+~` | `Cmd+~` |
| Run Task | `Ctrl+Shift+B` | `Cmd+Shift+B` |
| Start Debug | `F5` | `F5` |
| Toggle Breakpoint | `F9` | `F9` |
| Go to Definition | `F12` | `F12` |
| Find References | `Shift+F12` | `Shift+F12` |

---

## 🔍 Quick Start Workflows

### Workflow 1: Make a Code Change

```bash
1. Open workspace: code eas-station.code-workspace
2. Edit file: webapp/admin/alerts.py
3. Set breakpoint: Click line number margin (F9)
4. Debug: Press F5 → "Flask Web App (Development)"
5. Test: Open http://localhost:5000 in browser
6. Code pauses at breakpoint!
```

### Workflow 2: Run Tests

```bash
1. Open test file: tests/test_alerts.py
2. Press F5 → "Pytest: Current File"
3. Or: Ctrl+Shift+P → Tasks: Run Task → Run Pytest
```

### Workflow 3: Database Query

```bash
1. Click SQLTools icon (left sidebar)
2. Connect to "EAS Station Database (Local)"
3. Right-click cap_alerts table → Show Table Records
4. Or: New SQL File → Write query → Ctrl+E Ctrl+E
```

### Workflow 4: Check Redis

```bash
1. Ctrl+Shift+P → Tasks: Run Task
2. Select: Redis: List All Keys
3. Or: Redis: Monitor Commands (Live)
```

---

## 🆘 Troubleshooting

### Common Issues

**Problem:** VS Code doesn't recognize imports  
**Solution:** Select Python interpreter (`Ctrl+Shift+P` → Python: Select Interpreter)

**Problem:** Debugger not working  
**Solution:** Reload window (`Ctrl+Shift+P` → Developer: Reload Window)

**Problem:** Database connection fails  
**Solution:** Check PostgreSQL is running, verify `.env` has correct DATABASE_URL

**Problem:** Code snippets not appearing  
**Solution:** Type `eas-` and wait for autocomplete (may take 1-2 seconds)

---

## 📚 Additional Resources

- **[Full Local Setup Guide](docs/guides/VSCODE_LOCAL_SETUP.md)** - Complete installation and configuration
- **[Remote Setup Guide](.vscode/VSCODE_SETUP.md)** - SSH remote development
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute with VS Code
- **[Developer Guidelines](docs/development/AGENTS.md)** - Coding standards and patterns
- **[System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)** - Understanding the codebase

---

## ✅ Setup Checklist

After setup, verify:

- [ ] Workspace opens without errors
- [ ] Python interpreter is `./venv/bin/python`
- [ ] Extensions installed (12+ recommended extensions)
- [ ] IntelliSense works (hover shows types)
- [ ] Can start debugger with F5
- [ ] Code snippets work (type `eas-route`)
- [ ] Tasks accessible (Ctrl+Shift+P → Tasks)
- [ ] Database connection works (SQLTools)
- [ ] Git integration works (Source Control panel)

**All checked?** 🎉 **You're ready to code!**

---

**Questions?** 
- 📖 Check [VSCODE_LOCAL_SETUP.md](docs/guides/VSCODE_LOCAL_SETUP.md) for detailed help
- 💬 Ask in [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
- 🐛 Report issues in [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
