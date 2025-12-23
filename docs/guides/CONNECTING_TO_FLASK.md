# Connecting to Flask - Quick Guide

This guide explains how to connect to and work with the Flask web application in EAS Station.

---

## 🌐 Connecting to Flask (3 Methods)

### Method 1: Development Server (Best for Coding)

**Use when:** Actively developing, need auto-reload on file changes

**VS Code:**
```bash
# Option A: Press F5
1. Press F5 in VS Code
2. Select: "Flask Web App (Development)"
3. Flask starts on http://localhost:5000
4. Opens in debug mode with breakpoints enabled

# Option B: Use Task
1. Press Ctrl+Shift+P
2. Type: "Tasks: Run Task"
3. Select: "Flask: Run Development Server"
4. Flask starts with auto-reload enabled
```

**Terminal:**
```bash
# Activate virtual environment
source venv/bin/activate  # Linux/macOS
.\venv\Scripts\activate   # Windows

# Run Flask development server
FLASK_ENV=development FLASK_DEBUG=true python app.py

# Or using flask command
export FLASK_APP=app.py
export FLASK_ENV=development
flask run --debug
```

**Access Flask:**
- **Local:** http://localhost:5000
- **Network:** http://YOUR_IP:5000 (if bound to 0.0.0.0)

**Features:**
- ✅ Auto-reload on code changes
- ✅ Detailed error messages
- ✅ Debug toolbar
- ✅ Hot reload (no need to restart)

### Method 2: Production Server (Testing Full System)

**Use when:** Testing with systemd services, need production-like environment

**On Server (via SSH or local):**
```bash
# Restart Flask web service
sudo systemctl restart eas-station-web.service

# Check status
sudo systemctl status eas-station-web.service

# View logs
sudo journalctl -u eas-station-web.service -f
```

**Access Flask:**
- **HTTPS:** https://localhost or https://your-server-ip
- **HTTP (dev):** http://localhost:5000

**Features:**
- ✅ Production Gunicorn server
- ✅ nginx reverse proxy (HTTPS)
- ✅ All services integrated
- ✅ Real systemd service management

### Method 3: Direct Python Execution

**Use when:** Quick testing, debugging specific issues

```bash
# Activate environment
source venv/bin/activate

# Run directly
python app.py

# Or with custom port
python app.py --port 8080
```

---

## 🔌 Connection URLs

### Local Development

| Service | URL | Description |
|---------|-----|-------------|
| **Flask Web** | http://localhost:5000 | Main web interface |
| **FastAPI** | http://localhost:8000 | FastAPI endpoints (if running) |
| **Icecast** | http://localhost:8001 | Audio streaming server |

### Production (via nginx)

| Service | URL | Description |
|---------|-----|-------------|
| **Web (HTTPS)** | https://localhost | Secure web interface |
| **Web (HTTP)** | http://localhost | Redirects to HTTPS |
| **Icecast** | http://localhost:8001 | Audio streams |

### Network Access

Replace `localhost` with your server's IP or hostname:
- **Development:** http://192.168.1.100:5000
- **Production:** https://easstation-dev.local

---

## 🔧 Configuration

### Environment Variables (.env file)

Flask configuration is controlled by the `.env` file:

```bash
# Flask Settings
FLASK_ENV=development        # development or production
FLASK_DEBUG=true            # Enable debug mode (development only)
SECRET_KEY=your-secret-key  # Flask session encryption key

# Database Connection
DATABASE_URL=postgresql://eas_station:password@localhost:5432/alerts

# Redis Connection
REDIS_HOST=localhost
REDIS_PORT=6379

# Server Binding
FLASK_HOST=0.0.0.0         # 0.0.0.0 for network access, 127.0.0.1 for local only
FLASK_PORT=5000            # Default Flask port
```

### Changing the Port

**Method 1: Environment Variable**
```bash
export FLASK_PORT=8080
python app.py
```

**Method 2: Direct in app.py**
```python
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
```

**Method 3: Flask CLI**
```bash
flask run --port 8080
```

### Network Access

To allow connections from other devices on your network:

```bash
# In .env file
FLASK_HOST=0.0.0.0

# Or when running
python app.py --host 0.0.0.0
```

⚠️ **Security Warning:** Only bind to `0.0.0.0` on trusted networks!

---

## 🐛 Debugging Flask Connection

### Check Flask is Running

```bash
# Check if Flask process exists
ps aux | grep "python.*app.py"

# Check if port 5000 is listening
netstat -tlnp | grep 5000      # Linux
lsof -i :5000                  # macOS
netstat -ano | findstr :5000   # Windows

# Test connection
curl http://localhost:5000
# Should return HTML content
```

### Common Connection Issues

#### Problem 1: "Connection Refused"

**Cause:** Flask is not running

**Solution:**
```bash
# Start Flask
source venv/bin/activate
python app.py

# Or check service status
sudo systemctl status eas-station-web.service
```

#### Problem 2: "Address Already in Use"

**Cause:** Port 5000 is already used by another process

**Solution:**
```bash
# Find process using port 5000
lsof -ti:5000    # macOS/Linux
netstat -ano | findstr :5000  # Windows

# Kill the process
kill -9 $(lsof -ti:5000)      # macOS/Linux
taskkill /PID <PID> /F        # Windows

# Or use a different port
export FLASK_PORT=5001
python app.py
```

#### Problem 3: "Can't connect from another computer"

**Cause:** Flask is bound to localhost only

**Solution:**
```bash
# Bind to all interfaces
FLASK_HOST=0.0.0.0 python app.py

# Or edit .env file
echo "FLASK_HOST=0.0.0.0" >> .env
```

#### Problem 4: "Internal Server Error"

**Cause:** Application error (database, Redis, missing dependency)

**Solution:**
```bash
# Check logs for error details
# If using development server:
# Error will be shown in terminal

# If using systemd service:
sudo journalctl -u eas-station-web.service -n 50

# Check database connection
psql -h localhost -U eas_station -d alerts

# Check Redis connection
redis-cli ping
# Should return: PONG

# Check environment file exists
cat .env
```

#### Problem 5: "Template Not Found"

**Cause:** Wrong working directory

**Solution:**
```bash
# Always run from project root
cd /path/to/eas-station
python app.py

# Or set PYTHONPATH
export PYTHONPATH=/path/to/eas-station
```

---

## 🔍 Testing the Connection

### Quick Connection Test

```bash
# Test Flask is responding
curl -I http://localhost:5000
# Should return: HTTP/1.1 200 OK

# Test specific endpoint
curl http://localhost:5000/api/alerts
# Should return JSON

# Test with authentication
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5000/api/protected
```

### Browser Test

1. Open browser
2. Navigate to: http://localhost:5000
3. Should see EAS Station login page
4. Log in with admin credentials

### Python Test Script

```python
import requests

# Test connection
try:
    response = requests.get('http://localhost:5000')
    if response.status_code == 200:
        print("✅ Flask is running!")
        print(f"Response length: {len(response.text)} bytes")
    else:
        print(f"⚠️ Got status code: {response.status_code}")
except requests.exceptions.ConnectionError:
    print("❌ Cannot connect to Flask")
```

---

## 🎯 VS Code Integration

### Start Flask from VS Code

**Method 1: Debug Mode (F5)**
1. Open `app.py` in VS Code
2. Press `F5`
3. Select: "Flask Web App (Development)"
4. Flask starts with debugger attached
5. Set breakpoints by clicking line numbers

**Method 2: Task Menu**
1. Press `Ctrl+Shift+P`
2. Type: "Tasks: Run Task"
3. Select: "Flask: Run Development Server"
4. Terminal opens with Flask running

**Method 3: Terminal**
1. Press `` Ctrl+` `` to open terminal
2. Run commands:
```bash
source venv/bin/activate
python app.py
```

### Stop Flask in VS Code

**If started with F5:**
- Press `Shift+F5` (Stop Debugging)

**If started with Task:**
- Press `Ctrl+Shift+P`
- Select: "Flask: Stop Development Server"

**If started in terminal:**
- Press `Ctrl+C` in the terminal

### View Flask Logs in VS Code

**Development Server:**
- Logs appear in the terminal where Flask is running
- Or in the Debug Console (if started with F5)

**Production Service:**
1. Press `Ctrl+Shift+P`
2. Select: "Tasks: Run Task"
3. Choose: "Logs: Web Service (Live)"
4. Or in terminal:
```bash
sudo journalctl -u eas-station-web.service -f
```

---

## 📡 API Connection Examples

### JavaScript (from Browser)

```javascript
// GET request
fetch('http://localhost:5000/api/alerts')
  .then(response => response.json())
  .then(data => console.log(data))
  .catch(error => console.error('Error:', error));

// POST request
fetch('http://localhost:5000/api/alerts', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ event: 'Test Alert' })
})
  .then(response => response.json())
  .then(data => console.log(data));
```

### Python (requests)

```python
import requests

# GET request
response = requests.get('http://localhost:5000/api/alerts')
alerts = response.json()
print(f"Found {len(alerts)} alerts")

# POST request
data = {'event': 'Test Alert', 'severity': 'Severe'}
response = requests.post('http://localhost:5000/api/alerts', json=data)
print(response.json())
```

### cURL (Terminal)

```bash
# GET request
curl http://localhost:5000/api/alerts

# POST request
curl -X POST http://localhost:5000/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"event": "Test Alert"}'

# With authentication
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5000/api/protected
```

---

## 🔐 Authentication

### Web Browser Login

1. Navigate to: http://localhost:5000
2. Enter username and password
3. Session cookie is stored automatically

### API Authentication

**Using Session Cookie:**
```python
import requests

# Login
session = requests.Session()
response = session.post('http://localhost:5000/login', data={
    'username': 'admin',
    'password': 'your_password'
})

# Now make authenticated requests
alerts = session.get('http://localhost:5000/api/alerts')
```

**Using API Key:**
```python
import requests

headers = {'X-API-Key': 'your-api-key-here'}
response = requests.get('http://localhost:5000/api/alerts', headers=headers)
```

---

## 📊 Monitoring Flask

### Check Flask Status

```bash
# Using systemd (production)
sudo systemctl status eas-station-web.service

# Check if Flask is responding
curl -I http://localhost:5000

# Check Flask process
ps aux | grep "gunicorn\|flask"
```

### Flask Performance

```bash
# Monitor Flask requests (in development mode)
# Logs show in terminal

# Production: Monitor Gunicorn workers
sudo journalctl -u eas-station-web.service -f

# Check resource usage
top -p $(pgrep -f gunicorn)
```

### Flask Metrics

Access built-in metrics:
- **Dashboard:** http://localhost:5000/admin/dashboard
- **System Status:** http://localhost:5000/admin/system-status
- **API Metrics:** http://localhost:5000/api/metrics

---

## 🆘 Getting Help

### Flask Won't Start

1. **Check the logs:**
   ```bash
   # Development mode: Check terminal output
   # Production: Check journalctl
   sudo journalctl -u eas-station-web.service -n 50
   ```

2. **Verify dependencies:**
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Check database:**
   ```bash
   psql -h localhost -U eas_station -d alerts
   ```

4. **Check Redis:**
   ```bash
   redis-cli ping
   ```

### Can't Access Flask

1. **Verify Flask is running:**
   ```bash
   curl http://localhost:5000
   ```

2. **Check firewall:**
   ```bash
   # Linux
   sudo ufw status
   sudo ufw allow 5000
   
   # macOS
   # System Preferences → Security & Privacy → Firewall
   ```

3. **Check network binding:**
   ```bash
   netstat -tlnp | grep 5000
   # Should show 0.0.0.0:5000 for network access
   # Or 127.0.0.1:5000 for localhost only
   ```

---

## 📚 Additional Resources

- **[VS Code Local Setup](VSCODE_LOCAL_SETUP.md)** - Complete development setup
- **[VS Code Remote Setup](VSCODE_SETUP.md)** - Remote development via SSH
- **[Flask Documentation](https://flask.palletsprojects.com/)** - Official Flask docs
- **[System Architecture](../docs/architecture/SYSTEM_ARCHITECTURE.md)** - Understanding the system

---

**Quick Summary:**

```bash
# Start Flask (Development)
source venv/bin/activate
python app.py

# Connect in browser
http://localhost:5000

# Connect from Python
import requests
requests.get('http://localhost:5000/api/alerts')

# Stop Flask
Ctrl+C
```

**Need more help?** Check the [troubleshooting section](#-debugging-flask-connection) above or ask in [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions).
