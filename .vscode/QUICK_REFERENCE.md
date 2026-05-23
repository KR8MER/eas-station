# VSCode Quick Reference - EAS Station™

**Quick access to common tasks and commands**

---

## 🚀 Getting Started (First Time)

```bash
# 1. Install VSCode + Remote-SSH extension
# 2. Add to ~/.ssh/config:
Host easstation-dev
    HostName easstation-dev.local
    User eas-station

# 3. Connect: F1 → Remote-SSH: Connect to Host → easstation-dev
# 4. Open folder: /opt/eas-station
# 5. Select Python: /opt/eas-station/venv/bin/python
```

---

## ⌨️ Essential Shortcuts

| Action | Shortcut |
|--------|----------|
| Command Palette | `Ctrl+Shift+P` |
| Quick Open | `Ctrl+P` |
| Terminal | `Ctrl+~` |
| New Terminal | `Ctrl+Shift+~` |
| Run Task | `Ctrl+Shift+B` |
| Start Debug | `F5` |
| Toggle Breakpoint | `F9` |
| Search Files | `Ctrl+Shift+F` |

---

## 🔧 Quick Tasks (Ctrl+Shift+P → Tasks: Run Task)

### Development
- `Flask: Run Development Server` - Auto-reload dev mode
- `Flask: Stop Development Server` - Stop dev server

### Services
- `Service: Restart Web` - Restart Flask/Gunicorn
- `Service: Restart All` - Restart all EAS services
- `Check All Services Status` - Show status

### Logs
- `Logs: Web Service (Live)` - Follow web logs
- `Logs: All EAS Services (Live)` - Follow all logs
- `Logs: Web Service (Last 100)` - Last 100 lines

### Database
- `Database: Show Alert Count` - Count alerts
- `Database: Show Recent Alerts` - Last 10 alerts
- `Database: Connect with psql` - Interactive SQL

### Redis
- `Redis: Check Status` - Test connection
- `Redis: Monitor Commands (Live)` - Watch commands
- `Redis: List All Keys` - Show all keys

---

## 🐛 Debugging

```python
# 1. Set breakpoint: Click left margin (red dot)
# 2. Press F5 → Choose config
# 3. Code pauses at breakpoint

# Controls:
F5      - Continue
F10     - Step Over
F11     - Step Into
Shift+F11 - Step Out
Shift+F5  - Stop
```

---

## 📟 Terminal Commands

### Services
```bash
# Restart web service
sudo systemctl restart eas-station-web.service

# Restart all services
sudo systemctl restart eas-station.target

# Check status
sudo systemctl status eas-station.target
```

### Logs
```bash
# Follow logs
sudo journalctl -u eas-station-web.service -f

# All services
sudo journalctl -u 'eas-station*' -f

# Last 100 lines
sudo journalctl -u eas-station-web.service -n 100
```

### Database
```bash
# Connect
sudo -u postgres psql -d alerts

# Get password
grep DATABASE_URL /opt/eas-station/.env

# Quick query
sudo -u postgres psql -d alerts -c "SELECT COUNT(*) FROM cap_alerts;"
```

### Redis
```bash
# Test
redis-cli ping

# Monitor
redis-cli monitor

# List keys
redis-cli KEYS '*'

# Get value
redis-cli GET key-name
```

---

## 🔄 Typical Workflow

**Quick iteration (Flask dev mode)**:
```bash
1. Task: Flask: Run Development Server
2. Edit files → Auto-reloads
3. Test in browser: http://easstation-dev.local:5000
4. Task: Flask: Stop Development Server
```

**Production testing**:
```bash
1. Edit files
2. Task: Service: Restart Web
3. Test in browser: https://easstation-dev.local
4. Task: Logs: Web Service (Live) - check for errors
```

**Debugging**:
```bash
1. Set breakpoint (click margin)
2. F5 → Select "Flask Web App (Development)"
3. Trigger code (make request)
4. Inspect variables
5. F10 to step through
```

---

## 🗄️ Database Access

**GUI (SQLTools)**:
```
1. Click Database icon (left)
2. Connect → Enter password
3. Browse tables
4. Right-click → Show Records
```

**Terminal**:
```bash
sudo -u postgres psql -d alerts
```

**Get Password**:
```bash
grep DATABASE_URL /opt/eas-station/.env
# Format: postgresql://user:PASSWORD@host/db
```

---

## 🔍 Common Issues

**Can't connect via SSH**:
```bash
# Check hostname
ping easstation-dev.local

# Or use IP directly in ~/.ssh/config
```

**Python not found**:
```
Ctrl+Shift+P → Python: Select Interpreter
→ /opt/eas-station/venv/bin/python
```

**Changes don't appear**:
```bash
# Restart service
sudo systemctl restart eas-station-web.service
```

**Permission denied**:
```bash
# Check you're connected as eas-station user
whoami  # Should output: eas-station
```

---

## 📁 Important Paths

| Path | Description |
|------|-------------|
| `/opt/eas-station` | Application root |
| `/opt/eas-station/venv` | Python virtual environment |
| `/opt/eas-station/.env` | Configuration (secrets) |
| `/opt/eas-station/app.py` | Main Flask app |
| `/opt/eas-station/app_core` | Business logic |
| `/opt/eas-station/webapp` | Web routes |
| `/opt/eas-station/templates` | HTML templates |
| `/opt/eas-station/static` | CSS/JS/images |

---

## 🌐 Access URLs

| Service | URL |
|---------|-----|
| Web (Dev) | http://easstation-dev.local:5000 |
| Web (Prod) | https://easstation-dev.local |
| Icecast | http://easstation-dev.local:8001 |

---

## 🆘 Help

- Full guide: `.vscode/VSCODE_SETUP.md`
- GitHub: https://github.com/KR8MER/eas-station
- Issues: https://github.com/KR8MER/eas-station/issues
