# EAS Station - Portainer Quick Start

## 🚀 Deploy in 5 Minutes

### Step 1: Generate Credentials (2 minutes)

**On any computer with Python:**
```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate database password
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

**Save these values!** You'll need them in Step 3.

---

### Step 2: Create Stack in Portainer (1 minute)

1. Log into Portainer
2. Go to **Stacks** → **+ Add stack**
3. **Name:** `eas-station`
4. **Build method:** Git Repository
5. **Repository URL:** `https://github.com/KR8MER/eas-station`
6. **Repository reference:** `refs/heads/main` (or your branch)
7. **Compose path:** `docker-compose.embedded-db.yml`

---

### Step 3: Configure Environment Variables (2 minutes)

Click **Advanced mode** and paste:

```ini
# === REQUIRED ===
SECRET_KEY=paste-your-generated-secret-key-here
POSTGRES_PASSWORD=paste-your-generated-password-here

# === RECOMMENDED ===
DEFAULT_COUNTY_NAME=Your County Name
DEFAULT_STATE_CODE=OH
DEFAULT_TIMEZONE=America/New_York
```

**That's it!** Click **Deploy the stack**

---

## ✅ Verify It's Working

### 1. Check Containers (30 seconds after deploy)

Go to **Containers** - you should see all running:
- ✅ `eas-station-app-1` - Running
- ✅ `eas-station-poller-1` - Running
- ✅ `eas-station-ipaws-poller-1` - Running
- ✅ `eas-station-alerts-db-1` - Running

### 2. Check Logs

Click on `eas-station-app-1` → **Logs**

**Look for:**
```
INFO:app:Database connection successful
INFO:app:Listening at: http://0.0.0.0:5000
```

### 3. Access the Application

Open your browser:
```
http://YOUR_SERVER_IP
```

You should see the EAS Station dashboard!

---

## 🔧 If Something's Wrong

### Container Shows "Exited" or "Restarting"

**Check logs:**
1. **Containers** → Click the container → **Logs**
2. Look for error messages

**Common issues:**
- ❌ `SECRET_KEY is missing` → Add SECRET_KEY to environment variables
- ❌ `connection to server failed` → Database not ready yet (wait 30 seconds)
- ❌ `Authentication failed` → Password mismatch (see troubleshooting below)

### Can't Access via Browser (Connection Refused)

**Check firewall:**
```bash
# SSH into your server
sudo ufw allow 80/tcp
sudo ufw reload
```

**Check port mapping:**
- **Containers** → `eas-station-app-1` → Look at **Ports**
- Should show: `80:5000/tcp`

### Database Connection Errors

**Verify environment variables are set:**
1. **Stacks** → Your stack → **Editor**
2. Check `POSTGRES_PASSWORD` is set
3. Make sure you're using `docker-compose.embedded-db.yml` (not `docker-compose.yml`)

---

## 📚 More Information

- **Full Deployment Guide:** `docs/guides/PORTAINER_DEPLOYMENT.md`
- **Database Security:** `PORTAINER_DATABASE_SETUP.md`
- **Network Troubleshooting:** `PORTAINER_NETWORK_SETUP.md`

---

## 🔐 Security Checklist

Before going to production:

- ✅ Changed SECRET_KEY from default
- ✅ Changed POSTGRES_PASSWORD from default
- ✅ Firewall configured (port 80 only)
- ✅ Regular backups scheduled
- ✅ Admin account created with strong password

---

## 💡 Pro Tips

### Enable Automatic Backups

Once deployed:
1. Access the app at `http://YOUR_SERVER_IP`
2. Log in as admin
3. Go to **Admin** → **System Operations**
4. Click **Run Backup**
5. Schedule regular backups (weekly recommended)

### Update to Latest Version

1. **Stacks** → Your stack
2. Click **Pull and redeploy**
3. Wait for rebuild and restart
4. Verify in logs

### Monitor Health

Access health endpoint:
```
http://YOUR_SERVER_IP/system_health
```

---

**Need help?** Check the troubleshooting scripts:
```bash
# SSH into your server
cd /path/to/repo
bash troubleshoot_connection.sh
```

---

*Happy Alerting! 📻*

**73 de KR8MER**
