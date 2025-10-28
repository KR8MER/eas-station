# NOAA CAP Alerts System

A Docker-based Flask application that polls NOAA Common Alerting Protocol (CAP) alerts for Putnam County, OH, displays them on an interactive map, and optionally integrates with LED signage.

## Quick Start

### Single-Line Installation
```bash
git clone https://github.com/KR8MER/noaa_alerts_systems.git && cd noaa_alerts_systems && docker compose up -d --build
```

This command will:
- Clone the repository from GitHub
- Change into the project directory
- Build the Docker images
- Launch the Flask web application on port 5000
- Start the continuous CAP alert poller

**Note:** PostgreSQL with PostGIS must be running separately. See [Database Setup](#database-setup) below.

Access the application at **http://localhost:5000**

### Single-Line Update
```bash
git pull && docker compose build --pull && docker compose up -d --force-recreate
```

This command will:
- Pull the latest code from GitHub
- Rebuild Docker images with updated base images
- Recreate and restart all containers with the new code

---

## Prerequisites

- **Docker Engine 24+** (with Docker Compose V2)
- **Git** (for cloning and updates)
- **PostgreSQL 15+ with PostGIS** (running in a separate container or host)

---

## Configuration

The application uses a `.env` file for all runtime configuration. Copy and customize it before first run:
```bash
cp .env .env.local  # Optional: keep a backup
nano .env           # Edit with your preferred editor
```

### Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `host.docker.internal` | Database hostname (use `host.docker.internal` to access host or another container) |
| `POSTGRES_PORT` | `5432` | Database port |
| `POSTGRES_DB` | `casaos` | Database name |
| `POSTGRES_USER` | `casaos` | Database user |
| `POSTGRES_PASSWORD` | `casaos` | Database password |
| `POLL_INTERVAL_SEC` | `180` | Seconds between CAP poller runs |
| `LED_SIGN_IP` | - | Optional LED sign IP address |
| `LED_SIGN_PORT` | - | Optional LED sign port |
| `UPLOAD_FOLDER` | `/app/uploads` | GeoJSON upload directory |
| `SECRET_KEY` | (random) | Flask secret key (change in production!) |

**Important:** PostgreSQL runs in a separate container (not managed by this docker-compose.yml). Use `host.docker.internal` to connect from Docker containers to a database on the host or in another container.

---

## Architecture

The Docker Compose stack includes two services:

### 1. **app** - Web Application
- Flask-based web UI and REST API
- Served by Gunicorn on port 5000
- Handles alert display, admin interface, and GIS boundary management
- Connects to external PostgreSQL database

### 2. **poller** - Background Alert Poller
- Continuously fetches CAP alerts from NOAA
- Runs every `POLL_INTERVAL_SEC` seconds
- Auto-restarts on failure or system reboot
- Stores alerts in PostgreSQL with PostGIS geometries

### External Dependency: **PostgreSQL Database**
- PostgreSQL 15+ with PostGIS support (managed separately)
- Runs in its own container or on the host system
- Provides persistent data storage independent of app/poller lifecycle
- Allows rapid app redeployment without data loss
- Accessed via `host.docker.internal` from Docker containers

---

## Usage

### Starting and Stopping
```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# View logs
docker compose logs -f app       # Web app logs
docker compose logs -f poller    # Poller logs

# Restart a specific service
docker compose restart app
```

### Running the CAP Poller

The poller runs automatically in its own container. To run manual commands:
```bash
# Run poller once (manual fetch)
docker compose run --rm poller python poller/cap_poller.py

# Fix geometry issues
docker compose run --rm poller python poller/cap_poller.py --fix-geometry

# Run with custom interval
docker compose run --rm poller python poller/cap_poller.py --continuous --interval 300
```

### Uploading GIS Boundary Files

1. Navigate to **http://localhost:5000/admin**
2. Use the upload form to add GeoJSON boundary files
3. Ensure files are valid UTF-8 with a `features` array

**Troubleshooting uploads:**
- Verify `UPLOAD_FOLDER` is writable by the container
- Check that PostGIS extension is installed: `CREATE EXTENSION postgis;`
- Validate GeoJSON format at [geojson.io](https://geojson.io)

---

## Database Setup

### Setting Up PostgreSQL

PostgreSQL must be running separately before starting the application. You can run it:

**Option 1: Separate Docker Container**
```bash
docker run -d \
  --name noaa-postgres \
  -e POSTGRES_DB=casaos \
  -e POSTGRES_USER=casaos \
  -e POSTGRES_PASSWORD=casaos \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  postgis/postgis:15-3.3
```

**Option 2: Docker Compose (separate file)**
Create a separate `docker-compose.postgres.yml`:
```yaml
version: "3.9"
services:
  postgresql:
    image: postgis/postgis:15-3.3
    environment:
      POSTGRES_DB: casaos
      POSTGRES_USER: casaos
      POSTGRES_PASSWORD: casaos
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Run with: `docker compose -f docker-compose.postgres.yml up -d`

### Accessing PostgreSQL
```bash
# Access PostgreSQL from your host
psql -h localhost -p 5432 -U casaos -d casaos

# Or from within the postgres container
docker exec -it noaa-postgres psql -U casaos -d casaos
```

### Database Backups
```bash
# Backup
docker exec noaa-postgres pg_dump -U casaos casaos > backup_$(date +%Y%m%d).sql

# Restore
cat backup_20241026.sql | docker exec -i noaa-postgres psql -U casaos -d casaos
```

### Enable PostGIS (if needed)
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
```

---

## Development

### Local Development without Docker

1. Create a virtual environment:
```bash
   python3 -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
```

2. Install dependencies:
```bash
   pip install -r requirements.txt
```

3. Set up local PostgreSQL and configure `.env`

4. Run the Flask app:
```bash
   flask run
```

5. Run the poller manually:
```bash
   python poller/cap_poller.py
```

### Debugging

The `debug_apis.sh` script can test API endpoints:
```bash
# Inside Docker
docker compose exec app bash
./debug_apis.sh

# From host (if API_BASE_URL is set)
API_BASE_URL=http://localhost:5000 ./debug_apis.sh
```

---

## Production Deployment

### Security Checklist

- [ ] Change `SECRET_KEY` to a strong random value
- [ ] Update `POSTGRES_PASSWORD` to a secure password
- [ ] Use a reverse proxy (nginx/Caddy) with SSL/TLS
- [ ] Restrict PostgreSQL port access (firewall or bind to localhost only)
- [ ] Configure SMTP settings for email alerts (if used)
- [ ] Enable Docker logging with rotation
- [ ] Set up monitoring and alerting

### Persistent Storage

Map Docker volumes for important data:
```yaml
services:
  app:
    volumes:
      - ./logs:/app/logs
      - ./uploads:/app/uploads
```

### SMTP Configuration

Add to `.env` for email notifications:
```bash
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=alerts@example.com
MAIL_PASSWORD=yourpassword
MAIL_DEFAULT_SENDER=NOAA Alerts <alerts@example.com>
```

---

## Monitoring

### Health Checks
```bash
# Check if services are running
docker compose ps

# Check application health
curl http://localhost:5000/health

# View resource usage
docker stats
```

### Log Files

Logs are stored in the `logs/` directory (if mounted):
- `logs/app.log` - Flask application logs
- `logs/poller.log` - CAP poller logs

View logs in real-time:
```bash
docker compose logs -f --tail=100 app poller
```

---

## Troubleshooting

### Common Issues

**Problem:** Database connection refused
**Solution:**
- Ensure PostgreSQL is running: `docker ps | grep postgres`
- Verify `POSTGRES_HOST=host.docker.internal` in `.env`
- Check PostgreSQL is accessible: `psql -h localhost -p 5432 -U casaos -d casaos`

**Problem:** Poller not fetching alerts  
**Solution:** Check logs with `docker compose logs -f poller` and verify network connectivity

**Problem:** Upload failures  
**Solution:** Verify `UPLOAD_FOLDER` permissions and PostGIS is installed

**Problem:** Port 5000 already in use  
**Solution:** Change port mapping in `docker-compose.yml`: `"8080:5000"`

### Container Logs
```bash
# All services
docker compose logs -f

# Specific service with timestamps
docker compose logs -f --timestamps app

# Last 50 lines
docker compose logs --tail=50 poller
```

### Rebuilding from Scratch
```bash
# Stop and remove everything including volumes
docker compose down -v

# Rebuild and start fresh
docker compose up -d --build
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main map interface |
| `/admin` | GET | Admin dashboard |
| `/api/alerts` | GET | List all active alerts (JSON) |
| `/api/alerts/<id>` | GET | Get specific alert (JSON) |
| `/api/stats` | GET | System statistics |
| `/health` | GET | Health check endpoint |
| `/admin/upload_boundaries` | POST | Upload GeoJSON boundaries |

---

## Technology Stack

- **Python 3.11** - Core language
- **Flask 2.3** - Web framework
- **SQLAlchemy 2.0** - ORM and database toolkit
- **PostgreSQL 15** - Relational database
- **PostGIS** - Spatial database extension
- **Gunicorn** - WSGI HTTP server
- **Docker** - Containerization
- **Bootstrap 5** - Frontend UI framework

---

## License

[Specify your license here]

## Contributing

[Add contribution guidelines here]

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs with `docker compose logs -f`
3. Open an issue on the repository

---

## Changelog

### Latest Changes
- Docker-first deployment with single-command install/update
- Environment-based configuration (`.env` file)
- Continuous CAP poller in dedicated container
- PostGIS geometry support for spatial queries
- Admin UI for GeoJSON boundary uploads
- Optional LED sign integration
- Production-ready Gunicorn deployment
