# EAS Station Deployment Guide

**Modern, Separated Service Architecture**

## Architecture Overview

EAS Station now uses a clean, **separated service architecture** that's simpler, more reliable, and easier to maintain.

### Services

```
┌─────────────────────┐         ┌──────────────────┐
│  Audio Service      │         │   Web Service    │
│  (Standalone)       │         │   (Flask)        │
├─────────────────────┤         ├──────────────────┤
│ • Audio Ingestion   │         │ • REST API       │
│ • EAS Monitoring    │         │ • WebSocket      │
│ • SAME Decoding     │         │ • UI Serving     │
│ • Icecast Streaming │         │ • Configuration  │
│ • Metrics Publishing│         │ • Metrics Display│
└─────────┬───────────┘         └────────┬─────────┘
          │                              │
          └──────► Redis ◄───────────────┘
                 (State Storage)
```

### Benefits

| Feature | Before | After |
|---------|--------|-------|
| **Fault Isolation** | Web crash = Audio crash | Independent services |
| **Complexity** | Master/slave coordination | Simple pub/sub |
| **Debugging** | Mixed logs | Separate logs per service |
| **Restart** | Both restart together | Restart independently |
| **Performance** | Shared resources | Dedicated resources |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- PostgreSQL database (or use embedded with `docker-compose.embedded-db.yml`)
- SDR hardware (optional, can use Icecast streams)

### 1. Clone Repository

```bash
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
```

### 2. Configure Environment

Copy and edit configuration:

```bash
cp .env.example .env
nano .env
```

**Critical settings:**
```env
# Database
POSTGRES_HOST=your-database-host
POSTGRES_PASSWORD=secure-password

# Icecast (if using)
ICECAST_SOURCE_PASSWORD=secure-source-password
ICECAST_ADMIN_PASSWORD=secure-admin-password

# Domain (for SSL)
DOMAIN_NAME=eas.example.com
SSL_EMAIL=admin@example.com
```

### 3. Deploy

```bash
# Build images
docker-compose build

# Start all services
docker-compose up -d

# Check status
docker-compose ps
```

**Expected output:**
```
NAME                  STATUS
eas-redis             Up (healthy)
eas-audio-service     Up
eas-station-app       Up
eas-icecast           Up (healthy)
eas-nginx             Up
```

### 4. Verify Operation

**Check audio service:**
```bash
docker-compose logs -f audio-service
```

Look for:
```
✅ Audio controller initialized
✅ EAS monitor started successfully
✅ Audio service started successfully
   - Audio ingestion: ACTIVE
   - EAS monitoring: ACTIVE
   - Metrics publishing: ACTIVE
```

**Check web service:**
```bash
docker-compose logs -f app
```

Look for:
```
🌐 Running in WEB_ONLY mode - audio processing handled by separate audio service
✅ Database connected
✅ Flask app started
```

**Check Redis metrics:**
```bash
docker-compose exec redis redis-cli
> HGETALL eas:metrics
> SUBSCRIBE eas:metrics:update
```

### 5. Access UI

- **Web UI:** `https://your-domain.com` or `http://localhost`
- **Audio Monitoring:** `/audio-monitor`
- **Icecast Streams:** `http://localhost:8001`

---

## Service Details

### Audio Service (`audio_service.py`)

**Responsibilities:**
- Audio source ingestion (SDR, Icecast)
- EAS monitoring and SAME decoding
- Alert processing and forwarding
- Metrics collection and publishing

**Configuration:**
- Environment: Same as web app
- Database: Read-only access for configuration
- Redis: Write metrics every 5 seconds

**Logs:**
```bash
docker-compose logs -f audio-service

# Follow specific messages
docker-compose logs -f audio-service | grep "samples_processed"
```

**Restart:**
```bash
# Restart audio service only (web keeps running)
docker-compose restart audio-service
```

### Web Service (`app`)

**Responsibilities:**
- REST API endpoints
- WebSocket real-time updates
- UI serving
- Configuration management
- Metrics display (reads from Redis)

**Configuration:**
- `AUDIO_SERVICE_MODE=web_only` (automatic in docker-compose)
- No audio processing
- Reads metrics from Redis

**Logs:**
```bash
docker-compose logs -f app
```

**Restart:**
```bash
# Restart web service only (audio keeps running)
docker-compose restart app
```

### Redis Service

**Purpose:**
- Metrics storage
- Pub/sub notifications
- Worker coordination (if needed)

**Configuration:**
- 256MB memory limit
- AOF persistence
- LRU eviction policy

**Monitor:**
```bash
# Redis stats
docker-compose exec redis redis-cli INFO stats

# Watch metrics updates
docker-compose exec redis redis-cli SUBSCRIBE eas:metrics:update
```

---

## Maintenance

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f audio-service
docker-compose logs -f app
docker-compose logs -f redis

# Filter by error
docker-compose logs | grep ERROR
```

### Restart Services

```bash
# All services
docker-compose restart

# Audio processing only
docker-compose restart audio-service

# Web application only
docker-compose restart app

# Specific service
docker-compose restart icecast
```

### Update Deployment

```bash
# Pull latest changes
git pull

# Rebuild images
docker-compose build

# Restart with new images
docker-compose up -d
```

### Backup & Restore

**Database:**
```bash
# Backup
docker-compose exec postgres pg_dump -U postgres alerts > backup.sql

# Restore
docker-compose exec -T postgres psql -U postgres alerts < backup.sql
```

**Configuration:**
```bash
# Backup
docker-compose exec app cat /app-config/.env > backup.env

# Restore
docker-compose cp backup.env app:/app-config/.env
docker-compose restart app audio-service
```

---

## Troubleshooting

### Audio Service Not Starting

**Check logs:**
```bash
docker-compose logs audio-service
```

**Common issues:**
1. **Database connection failed**
   - Verify `POSTGRES_HOST` and credentials
   - Check database is running: `docker-compose ps postgres`

2. **Redis connection failed**
   - Check Redis is healthy: `docker-compose ps redis`
   - Verify `REDIS_HOST=redis`

3. **SDR device not found**
   - Check device is plugged in: `lsusb`
   - Verify device passthrough in docker-compose.yml
   - Try privileged mode

**Manual test:**
```bash
# Run audio service manually
docker-compose run --rm audio-service python audio_service.py
```

### Web Service Shows "No Metrics"

**Symptoms:**
- UI shows "Waiting for data"
- Samples processed = 0

**Solutions:**

1. **Check audio service is running:**
   ```bash
   docker-compose ps audio-service
   # Should show "Up"
   ```

2. **Check Redis has metrics:**
   ```bash
   docker-compose exec redis redis-cli HGETALL eas:metrics
   # Should show JSON data
   ```

3. **Check web service environment:**
   ```bash
   docker-compose exec app env | grep AUDIO_SERVICE_MODE
   # Should show: AUDIO_SERVICE_MODE=web_only
   ```

4. **Restart audio service:**
   ```bash
   docker-compose restart audio-service
   # Wait 10 seconds, check UI
   ```

### VU Meters Not Updating

**Check WebSocket connection:**
1. Open browser console (F12)
2. Look for WebSocket connection
3. Should see: `WebSocket connected - real-time updates active`

**If not connected:**
- Check Gunicorn is using gevent: `docker-compose logs app | grep gevent`
- Verify gevent is installed: `docker-compose exec app pip list | grep gevent`

### Audio Stuttering After 50 Seconds

**This should be FIXED with separated architecture.**

**If still occurs:**
1. Check audio service logs for underruns
2. Increase broadcast queue size (if needed)
3. Check system resources: `docker stats`

---

## Performance Tuning

### Audio Service

**Increase worker threads (if needed):**
```yaml
# docker-compose.yml
environment:
  AUDIO_THREADS: 4  # Default: 2
```

**Adjust metrics interval:**
```python
# audio_service.py line ~370
metrics_interval = 2.0  # Default: 5.0
```

### Web Service

**Increase Gunicorn workers:**
```yaml
# docker-compose.yml
command: >
  gunicorn --workers 4 ...  # Default: 2
```

**Tune Redis:**
```yaml
# docker-compose.yml redis command
--maxmemory 512mb  # Default: 256mb
```

---

## Advanced Configuration

### Multiple Audio Services (Future)

For high availability:
```yaml
audio-service-1:
  # Primary audio service

audio-service-2:
  # Backup audio service (failover)
```

### Custom Metrics Export

Add Prometheus exporter:
```python
# In audio_service.py
from prometheus_client import start_http_server, Gauge

samples_gauge = Gauge('eas_samples_processed', 'Total samples processed')
samples_gauge.set(metrics["eas_monitor"]["samples_processed"])
```

### Monitoring & Alerting

Recommended tools:
- **Grafana** - Metrics visualization
- **Prometheus** - Metrics collection
- **AlertManager** - Alert notifications
- **Loki** - Log aggregation

---

## Security

### Production Checklist

- [ ] Change all default passwords
- [ ] Enable SSL/TLS (Let's Encrypt)
- [ ] Restrict database access
- [ ] Use strong SECRET_KEY
- [ ] Enable MFA for admin accounts
- [ ] Configure firewall rules
- [ ] Regular security updates
- [ ] Monitor logs for suspicious activity

### Network Security

```yaml
# docker-compose.yml
networks:
  eas-network:
    internal: true  # Isolate from external network

    # Expose only necessary services
```

---

## Support

- **Documentation:** `https://github.com/KR8MER/eas-station`
- **Issues:** `https://github.com/KR8MER/eas-station/issues`
- **Discussions:** `https://github.com/KR8MER/eas-station/discussions`

---

## Summary

**New Architecture Benefits:**
✅ **Simpler** - No complex worker coordination
✅ **Reliable** - Services isolated, independent restart
✅ **Performant** - Dedicated resources per service
✅ **Maintainable** - Clear separation of concerns
✅ **Bulletproof** - Production-grade design

**Deployment:**
```bash
docker-compose up -d
```

**That's it!** 🚀

The separated service architecture gives you an **out-of-the-box solution** that just works.
