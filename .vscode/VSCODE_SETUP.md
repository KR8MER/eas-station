# VSCode Remote Development Setup for EAS Station™

**Quick and easy VSCode setup for working with EAS Station™ on `easstation-dev.local`**

> **TL;DR**: Install VSCode + Remote-SSH extension → Connect to server → Open `/opt/eas-station` → Start coding!

---

## 📋 Prerequisites

**On your local computer:**
- VSCode installed ([download here](https://code.visualstudio.com/))
- SSH access to your EAS Station™ server
- The server hostname: `easstation-dev.local` (or IP address)

**On the server (already done by install.sh):**
- ✅ EAS Station™ installed at `/opt/eas-station`
- ✅ Python virtual environment at `/opt/eas-station/venv`
- ✅ Services running via systemd
- ✅ User account: `eas-station`

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Install VSCode Extensions

Open VSCode and install these extensions:

1. Press `Ctrl+Shift+X` (or `Cmd+Shift+X` on Mac)
2. Search for and install:
   - **Remote - SSH** (by Microsoft) ← **REQUIRED**
   - **Python** (by Microsoft) ← **REQUIRED**
   - **Pylance** (by Microsoft) ← **REQUIRED**

VSCode will also suggest installing other recommended extensions when you open the workspace.

### Step 2: Configure SSH Connection

1. Press `F1` to open the command palette
2. Type: `Remote-SSH: Open SSH Configuration File`
3. Select your SSH config file (usually `~/.ssh/config`)
4. Add this configuration:

```ssh-config
Host easstation-dev
    HostName easstation-dev.local
    User eas-station
    ForwardAgent yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

**Save the file** (`Ctrl+S` or `Cmd+S`)

### Step 3: Connect to the Server

1. Press `F1` again
2. Type: `Remote-SSH: Connect to Host`
3. Select `easstation-dev` from the list
4. A new VSCode window will open
5. **Enter your password** when prompted
6. Wait 30-60 seconds for the connection to establish

You'll see **"SSH: easstation-dev"** in the bottom-left corner when connected.

### Step 4: Open the EAS Station™ Folder

1. Click **File → Open Folder**
2. Type or navigate to: `/opt/eas-station`
3. Click **OK**
4. Enter your password again if prompted

### Step 5: Select Python Interpreter

1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P`)
2. Type: `Python: Select Interpreter`
3. Choose: `/opt/eas-station/venv/bin/python`

**✅ You're all set!** VSCode is now connected to your EAS Station™ server.

---

## 💡 What You Can Do Now

### Run Flask Development Server (Auto-Reload)

For rapid development, run Flask in development mode with auto-reload:

**Using Task** (Recommended):
- `Ctrl+Shift+P` → `Tasks: Run Task` → `Flask: Run Development Server`
- Flask will auto-reload when you save files
- Access at: `http://localhost:5000` or `http://easstation-dev.local:5000`
- Press `Ctrl+C` in terminal to stop

**Manual**:
```bash
source /opt/eas-station/venv/bin/activate
FLASK_ENV=development FLASK_DEBUG=true python app.py
```

**When to use**:
- ✅ Rapid iteration - auto-reloads on file save
- ✅ Better error messages with stack traces
- ✅ Interactive debugger in browser
- ❌ **Don't use in production** - only for development

**When finished**: Stop the dev server and restart the systemd service:
- Task: `Flask: Stop Development Server`
- Task: `Service: Restart Web`

### View and Edit Code
- Browse files in the Explorer panel (left sidebar)
- Edit any Python file - changes are saved directly on the server
- Use IntelliSense (auto-complete) - works with the remote Python environment

### Manage Services (All EAS Station™ Services)

**Available services**:
- `eas-station-web.service` - Flask web application (Gunicorn)
- `eas-station-audio.service` - Audio processing and monitoring
- `eas-station-poller.service` - Alert polling (NOAA + IPAWS)
- `eas-station-eas.service` - EAS encoding and broadcast
- `eas-station-hardware.service` - GPIO and hardware control
- `eas-station-sdr.service` - SDR hardware interface
- `eas-station.target` - All services together

**Quick Tasks** (`Ctrl+Shift+P` → `Tasks: Run Task`):
- `Service: Restart Web` - restart web service
- `Service: Restart Audio` - restart audio service
- `Service: Restart Poller` - restart poller service
- `Service: Restart All` - restart all services
- `Check All Services Status` - see what's running

**Manual control**:
```bash
# Restart individual service
sudo systemctl restart eas-station-web.service

# Restart all services
sudo systemctl restart eas-station.target

# Stop all services
sudo systemctl stop eas-station.target

# Start all services
sudo systemctl start eas-station.target

# Check status
sudo systemctl status eas-station.target
```

### Run Services
Press `Ctrl+Shift+P` → Type `Tasks: Run Task` → Choose:
- **Restart Web Service** - restart after code changes
- **View Web Service Logs** - watch real-time logs
- **Check All Services Status** - see what's running

### Debug Code
1. Open a Python file (e.g., `app.py`)
2. Click in the left margin to set a breakpoint (red dot)
3. Press `F5` to start debugging
4. Choose a debug configuration (e.g., "Flask Web App (Development)")

### View Logs (All Services)

**Live logs** (follow in real-time):
- `Logs: Web Service (Live)` - Flask/Gunicorn logs
- `Logs: Audio Service (Live)` - audio processing logs
- `Logs: Poller Service (Live)` - alert polling logs
- `Logs: All EAS Services (Live)` - all services combined

**Historical logs**:
- `Logs: Web Service (Last 100)` - last 100 lines

**Manual**:
```bash
# Follow web service logs
sudo journalctl -u eas-station-web.service -f

# Follow all EAS services
sudo journalctl -u 'eas-station*' -f

# Last 100 lines
sudo journalctl -u eas-station-web.service -n 100

# Since specific time
sudo journalctl -u eas-station-web.service --since "1 hour ago"

# With errors only
sudo journalctl -u eas-station-web.service -p err
```

### Monitor Redis

Redis is used for inter-service communication and caching.

**Quick Tasks**:
- `Redis: Check Status` - verify Redis is running
- `Redis: Monitor Commands (Live)` - watch all Redis commands in real-time
- `Redis: List All Keys` - see what's stored
- `Redis: Show Info` - Redis server statistics

**Manual**:
```bash
# Test connection
redis-cli ping
# Returns: PONG

# List all keys
redis-cli KEYS '*'

# Get a value
redis-cli GET key-name

# Monitor all commands (live)
redis-cli monitor

# Get server info
redis-cli INFO

# Count keys
redis-cli DBSIZE
```

**Common Redis keys in EAS Station™**:
- `eas:audio:*` - Audio service metrics
- `eas:sdr:*` - SDR status
- `eas:alert:*` - Current alert state
- `eas:broadcast:*` - Broadcast status

### View Logs
- Press `Ctrl+~` to open the terminal
- Run: `sudo journalctl -u eas-station-web.service -f`
- Or use the **View Web Service Logs** task

### Test Your Changes
1. Make a code change
2. Run task: **Restart Web Service**
3. Open browser: `https://easstation-dev.local`
4. See your changes!

---

## 🗄️ Database Access (PostgreSQL)

### Option 1: Using SQLTools Extension (GUI - Recommended)

The SQLTools extension provides a graphical interface for database queries.

**Setup**:
1. Install extensions (VSCode will prompt you):
   - **SQLTools** (by Matheus Teixeira)
   - **SQLTools PostgreSQL/Cockroach Driver**

2. Click the **SQLTools** icon in the left sidebar (database icon)

3. You'll see: **EAS Station™ Database** connection

4. Click the connection → **Connect**

5. **Enter password** when prompted:
   ```bash
   # Get password from terminal:
   grep DATABASE_URL /opt/eas-station/.env
   # Look for the password in: postgresql://eas_station:PASSWORD@...
   ```

6. Now you can browse tables, run queries, and view data!

**Using SQLTools**:
- Browse tables in the sidebar
- Right-click table → **Show Table Records**
- Click **New SQL File** to write queries
- Select text and press `Ctrl+E Ctrl+E` to run query

### Option 2: Using Terminal (Command Line)

```bash
# Quick connection (no password needed when using postgres user)
sudo -u postgres psql -d alerts

# Or with eas_station user (requires password)
psql -h localhost -U eas_station -d alerts
```

**Get the password**:
```bash
grep DATABASE_URL /opt/eas-station/.env
# Format: postgresql://username:PASSWORD@host:port/database
```

**Common queries**:
```sql
-- Count all alerts
SELECT COUNT(*) FROM cap_alerts;

-- Show recent alerts
SELECT id, event, headline, sent 
FROM cap_alerts 
ORDER BY sent DESC 
LIMIT 10;

-- Show all tables
\dt

-- Describe a table
\d cap_alerts

-- Exit
\q
```

### Option 3: Using VSCode Tasks (Quick Queries)

Press `Ctrl+Shift+P` → `Tasks: Run Task` → Choose:
- **Database: Show Alert Count** - count alerts
- **Database: Show Recent Alerts** - last 10 alerts
- **Database: Show Tables** - list all tables
- **Database: Connect with psql** - open interactive session
- **Database: Show Connection Info** - get connection details (password hidden)

### Security Note

**Database password is stored in `.env` file only** - it's never committed to Git!

The SQLTools connection is configured to **ask for password each time** - it won't save it in VSCode settings.

---

## 🔧 Common Tasks

### Restart a Service After Code Changes
```bash
# In VSCode terminal (Ctrl+~):
sudo systemctl restart eas-station-web.service
```

Or use the built-in task:
- `Ctrl+Shift+P` → `Tasks: Run Task` → `Restart Web Service`

### View Service Logs
```bash
# Web service
sudo journalctl -u eas-station-web.service -f

# All EAS services
sudo journalctl -u 'eas-station*' -f
```

Or use tasks:
- `View Web Service Logs`
- `View All EAS Station™ Logs`

### Check Database
```bash
# Connect to PostgreSQL
sudo -u postgres psql -d alerts

# Count alerts
sudo -u postgres psql -d alerts -c "SELECT COUNT(*) FROM cap_alerts;"
```

Or use the task: `Database: Show Alert Count`

### Check Redis
```bash
# Test connection
redis-cli ping
# Should return: PONG

# Monitor commands
redis-cli monitor
```

Or use tasks: `Redis: Check Status` or `Redis: Monitor Commands`

---

## 🐛 Debugging

### Start Debugging
1. Open the file you want to debug
2. Set breakpoints (click left margin)
3. Press `F5`
4. Choose configuration:
   - **Flask Web App (Development)** - for web server
   - **EAS Monitoring Service** - for audio/monitoring
   - **Python: Current File** - for any script

### Debug Controls
- `F5` - Continue
- `F10` - Step Over
- `F11` - Step Into
- `Shift+F11` - Step Out
- `Shift+F5` - Stop

### View Variables
When paused at a breakpoint:
- **Variables panel** (left side) - see all variable values
- **Watch panel** - add expressions to watch
- **Call Stack** - see how you got here
- **Debug Console** - type Python expressions

---

## 📁 Workspace Layout

```
/opt/eas-station/
├── .vscode/              # VSCode configuration (auto-configured)
│   ├── settings.json     # Workspace settings
│   ├── launch.json       # Debug configurations
│   ├── tasks.json        # Common tasks
│   └── extensions.json   # Recommended extensions
├── app.py                # Main Flask application
├── eas_service.py        # EAS monitoring service
├── hardware_service.py   # GPIO/hardware control
├── app_core/             # Core business logic
├── app_utils/            # Utility modules
├── webapp/               # Web routes and templates
├── tests/                # Test suite
├── venv/                 # Python virtual environment
├── .env                  # Configuration (DO NOT COMMIT)
└── requirements.txt      # Python dependencies
```

---

## ⚡ Keyboard Shortcuts

| Action | Shortcut | Description |
|--------|----------|-------------|
| Command Palette | `Ctrl+Shift+P` | Access all commands |
| Quick Open File | `Ctrl+P` | Quickly open any file |
| Terminal | `Ctrl+~` | Show/hide terminal |
| Run Task | `Ctrl+Shift+B` | Run default task |
| Start Debugging | `F5` | Start debugger |
| Toggle Breakpoint | `F9` | Add/remove breakpoint |
| Search in Files | `Ctrl+Shift+F` | Search across all files |
| Git View | `Ctrl+Shift+G` | View Git changes |
| Extensions | `Ctrl+Shift+X` | Manage extensions |

---

## 🔒 Security Notes

**sudoers Configuration (Already Done)**

The install script configured `/etc/sudoers` to allow password-less access to:
- Service management: `systemctl restart/stop/start/status eas-station*`
- Log viewing: `journalctl -u eas-station*`
- Database access: `psql`
- Redis access: `redis-cli`

This lets you run these commands without typing your password every time.

**SSH Configuration**

Your SSH connection is encrypted. Files you edit in VSCode are saved directly on the server - no upload/download needed.

**DO NOT COMMIT `.env`**

The `.env` file contains secrets and passwords. It's already in `.gitignore` - never commit it!

---

## 🆘 Troubleshooting

### Can't Connect via SSH

**Problem**: "Connection refused" or "Host not found"

**Solutions**:
1. **Check hostname**: Can you ping the server?
   ```bash
   ping easstation-dev.local
   # Or use IP address directly
   ```

2. **Check SSH service**:
   ```bash
   # On the server:
   sudo systemctl status ssh
   ```

3. **Use IP address instead**:
   - Find server IP: `hostname -I` (on server)
   - Update SSH config to use IP instead of hostname

### Python Interpreter Not Found

**Problem**: VSCode can't find `/opt/eas-station/venv/bin/python`

**Solution**:
1. Press `Ctrl+Shift+P`
2. Type: `Python: Select Interpreter`
3. Click **Enter interpreter path**
4. Type: `/opt/eas-station/venv/bin/python`

### Code Changes Don't Take Effect

**Problem**: Changed code but web app still shows old behavior

**Solution**: Restart the service!
```bash
sudo systemctl restart eas-station-web.service
```

Or use the task: **Restart Web Service**

### Permission Denied

**Problem**: Can't edit files or run commands

**Solution**: Make sure you're connected as the `eas-station` user:
1. Check bottom-left corner of VSCode
2. Should say "SSH: easstation-dev"
3. Open terminal (`Ctrl+~`) and run: `whoami`
4. Should output: `eas-station`

If you're connected as the wrong user, disconnect and reconnect with the correct user.

### Services Won't Start

**Problem**: Service fails to start after changes

**Solution**: Check the logs for errors
```bash
sudo journalctl -u eas-station-web.service -n 50
```

Common issues:
- **Syntax error in Python code** - fix the error
- **Missing dependency** - install with pip
- **Database migration needed** - run migration
- **Port already in use** - stop conflicting service

---

## 🔄 Complete Development Workflow

### Typical Development Session

**1. Connect to Server**
```bash
# VSCode will auto-connect if you saved the workspace
# Or: F1 → Remote-SSH: Connect to Host → easstation-dev
```

**2. Start Development Mode**

Choose your workflow:

**Option A: Flask Development Server** (Best for web development)
```bash
# Task: Flask: Run Development Server
# - Auto-reloads on file changes
# - Better error messages
# - Interactive debugger
# Access: http://easstation-dev.local:5000
```

**Option B: Production Services** (Best for testing full system)
```bash
# Task: Service: Restart All
# - Tests with real systemd services
# - Tests inter-service communication
# - Access: https://easstation-dev.local (nginx)
```

**3. Monitor Logs**
```bash
# Open multiple terminals (Ctrl+Shift+~)
# Terminal 1: Flask dev server (if using Option A)
# Terminal 2: Task → Logs: All EAS Services (Live)
# Terminal 3: Task → Redis: Monitor Commands (Live)
```

**4. Make Changes**
- Edit Python files in VSCode
- Changes save automatically to server
- Flask dev server auto-reloads (Option A)
- Or restart service manually (Option B)

**5. Test Changes**
```bash
# Open browser to test
https://easstation-dev.local

# Or run automated tests
pytest tests/ -v

# Or debug with breakpoints (F5)
```

**6. Check Database**
```bash
# Task: Database: Show Recent Alerts
# Or: Click SQLTools → Run query
```

**7. Commit Changes**
```bash
git status
git add <files>
git commit -m "Description"
git push
```

### Service-Specific Workflows

**Working on Web Interface (Flask)**:
1. Task: `Flask: Run Development Server`
2. Edit files in `app.py`, `webapp/`, `templates/`
3. Browser auto-refresh (or Ctrl+R)
4. See changes immediately
5. When done: `Flask: Stop Development Server`

**Working on Audio Processing**:
1. Task: `Service: Restart Audio`
2. Task: `Logs: Audio Service (Live)`
3. Edit `eas_monitoring_service.py` or `app_core/audio/`
4. Restart service after changes
5. Check logs for errors

**Working on Alert Polling**:
1. Task: `Service: Restart Poller`
2. Task: `Logs: Poller Service (Live)`
3. Edit `poller/cap_poller.py` or `app_core/noaa_poller.py`
4. Restart service after changes
5. Check database for new alerts

**Working on Database Models**:
1. Edit models in `app_core/models.py`
2. Create migration: `alembic revision --autogenerate -m "Description"`
3. Review migration in `alembic/versions/`
4. Apply: `alembic upgrade head`
5. Restart services: `Task: Restart All EAS Services`

**Working on Hardware/GPIO**:
1. Task: `Service: Restart Hardware`
2. Task: `Logs: Hardware Service (Live)`
3. Edit `hardware_service.py` or `app_core/hardware/`
4. Test with actual GPIO pins
5. Monitor Redis: `redis-cli monitor` (see GPIO state changes)

### Debugging Workflow

**Set Breakpoints and Debug**:
1. Open Python file (e.g., `app.py`)
2. Click left margin to set breakpoint (red dot)
3. Press `F5` → Choose debug config
4. Code runs and pauses at breakpoint
5. Inspect variables in left panel
6. Step through code:
   - `F10` - Step Over
   - `F11` - Step Into
   - `F5` - Continue

**Debug a Live Service**:
1. Stop the service: `sudo systemctl stop eas-station-web.service`
2. Run manually with debugger: Press `F5` → Select service
3. Trigger the code path (make web request, etc.)
4. Debug as normal
5. When done: Restart service with `Task: Service: Restart Web`

**Debug with Print Statements** (Quick & Dirty):
1. Add `print()` or `logger.debug()` statements
2. Restart service
3. Watch logs: `Task: Logs: Web Service (Live)`
4. See output in real-time

### Testing Workflow

**Run All Tests**:
```bash
pytest tests/ -v
```

**Run Specific Test**:
```bash
pytest tests/test_alerts.py -v
```

**Run Tests with Coverage**:
```bash
pytest tests/ --cov=app_core --cov-report=html
# Open htmlcov/index.html to see coverage report
```

**Debug a Failing Test**:
1. Press `F5` → `Pytest: Current File`
2. Or set breakpoint in test, press `F5`

### Redis Debugging Workflow

**Monitor Service Communication**:
```bash
# Terminal 1: Watch Redis commands
redis-cli monitor

# Terminal 2: Restart a service
sudo systemctl restart eas-station-audio.service

# Watch Redis output to see what the service writes
```

**Check Service Status in Redis**:
```bash
# List all keys
redis-cli KEYS '*'

# Get specific value
redis-cli GET eas:audio:status

# Watch for changes
redis-cli --csv PSUBSCRIBE 'eas:*'
```

### Database Debugging Workflow

**Check Alert Processing**:
```bash
# Count total alerts
sudo -u postgres psql -d alerts -c "SELECT COUNT(*) FROM cap_alerts;"

# Recent alerts
sudo -u postgres psql -d alerts -c "SELECT id, event, headline, sent FROM cap_alerts ORDER BY sent DESC LIMIT 10;"

# Find errors
sudo -u postgres psql -d alerts -c "SELECT * FROM cap_alerts WHERE status = 'Error' LIMIT 5;"
```

**Using SQLTools Extension**:
1. Click SQLTools icon (left sidebar)
2. Connect to database
3. Browse tables visually
4. Write SQL queries
5. Press `Ctrl+E Ctrl+E` to run

---

## 💻 Advanced: Development Workflow

### Make a Change and Test

1. **Edit code** in VSCode
2. **Set breakpoint** if debugging
3. **Restart service**: Task → `Restart Web Service`
4. **Watch logs**: Task → `View Web Service Logs`
5. **Test**: Open browser to `https://easstation-dev.local`
6. **Debug**: Press `F5` if you need to step through code
7. **Iterate**: Make more changes and repeat

### Run Tests

```bash
# In terminal:
cd /opt/eas-station
source venv/bin/activate
pytest tests/ -v
```

Or use the debug configuration: **Pytest: All Tests**

### Database Queries

```bash
# Connect to database
sudo -u postgres psql -d alerts

# Run queries
SELECT * FROM cap_alerts ORDER BY sent DESC LIMIT 5;

# Exit
\q
```

Or use the VSCode SQL extensions to run queries with IntelliSense!

### View Git Changes

1. Click Source Control icon (left sidebar) or press `Ctrl+Shift+G`
2. See changed files
3. Click a file to see diff
4. Stage changes by clicking `+`
5. Commit with message
6. Push to GitHub

---

## 📚 Next Steps

**Learn More**:
- [VSCode Remote Development Docs](https://code.visualstudio.com/docs/remote/ssh)
- [Python in VSCode](https://code.visualstudio.com/docs/languages/python)
- [Debugging in VSCode](https://code.visualstudio.com/docs/editor/debugging)

**EAS Station™ Docs**:
- [User Guide](../docs/guides/HELP.md)
- [Developer Guide](../docs/development/AGENTS.md)
- [Architecture Overview](../docs/architecture/SYSTEM_ARCHITECTURE.md)

**Get Help**:
- [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
- [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)

---

## ✅ Configuration Checklist

After setup, verify:

- [ ] VSCode connected to server (bottom-left shows "SSH: easstation-dev")
- [ ] Folder `/opt/eas-station` opened
- [ ] Python interpreter selected: `/opt/eas-station/venv/bin/python`
- [ ] Can see files in Explorer panel
- [ ] Can open terminal with `Ctrl+~`
- [ ] Can run `whoami` → outputs `eas-station`
- [ ] Can run `sudo systemctl status eas-station.target` → no password prompt
- [ ] Recommended extensions installed (VSCode prompts automatically)
- [ ] Can set breakpoint and start debugger with `F5`

**All checked?** 🎉 **You're ready to develop!**

---

**Happy Coding!** 🚀

*If you encounter issues not covered in the Troubleshooting section, check [GitHub Issues](https://github.com/KR8MER/eas-station/issues) or [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions).*


