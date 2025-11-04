# Installation Guide

This guide provides detailed installation instructions for EAS Station using Docker.

## Prerequisites

### Required Software

| Component | Minimum Version | Recommended |
|-----------|----------------|-------------|
| Docker Engine | 24.0+ | Latest stable |
| Docker Compose | 2.0+ (V2) | Latest stable |
| PostgreSQL | 14+ with PostGIS 3+ | PostgreSQL 17 + PostGIS 3.4 |
| Git | 2.0+ | Latest stable |

### System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 2GB | 4-8GB |
| Storage | 10GB | 50GB+ (for logs and audio) |
| Network | Broadband internet | Stable, low-latency |

### Hardware Support (Optional)

- **SDR Receivers**: RTL-SDR (RTL2832U), Airspy, HackRF
- **GPIO Control**: Raspberry Pi GPIO (for transmitter keying)
- **LED Signs**: Alpha Protocol compatible displays
- **Audio**: ALSA-compatible sound cards

## Installation Methods

Choose the installation method that fits your environment:

=== "Docker (Recommended)"

    ### Docker Installation

    #### 1. Install Docker

    === "Ubuntu/Debian"

        ```bash
        # Update package index
        sudo apt update

        # Install prerequisites
        sudo apt install -y ca-certificates curl gnupg

        # Add Docker GPG key
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
          sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg

        # Add Docker repository
        echo \
          "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] \
          https://download.docker.com/linux/ubuntu \
          "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

        # Install Docker
        sudo apt update
        sudo apt install -y docker-ce docker-ce-cli containerd.io \
          docker-buildx-plugin docker-compose-plugin

        # Add user to docker group
        sudo usermod -aG docker $USER
        ```

    === "Raspberry Pi OS"

        ```bash
        # Convenience script (recommended for Pi)
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh

        # Add user to docker group
        sudo usermod -aG docker $USER

        # Reboot required
        sudo reboot
        ```

    === "macOS"

        Download and install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)

    === "Windows"

        Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)

    #### 2. Verify Docker Installation

    ```bash
    docker --version
    docker compose version
    ```

    Expected output:

    ```
    Docker version 24.0.7, build afdd53b
    Docker Compose version v2.23.0
    ```

=== "Portainer"

    ### Portainer Installation

    For containerized management, see the [Portainer Deployment Guide](../admin-guide/deployment/portainer.md).

## Database Setup

EAS Station requires PostgreSQL with the PostGIS extension.

=== "Embedded Database (Easy)"

    Use the included PostgreSQL container:

    **In `docker-compose.yml`, ensure:**

    ```yaml
    services:
      alerts-db:
        image: postgis/postgis:17-3.4
        environment:
          POSTGRES_DB: alerts
          POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ```

    **In `.env`, set:**

    ```bash
    POSTGRES_HOST=alerts-db
    POSTGRES_PASSWORD=your-secure-password
    ```

=== "External Database"

    Use an existing PostgreSQL server:

    #### 1. Create Database

    ```sql
    CREATE DATABASE alerts;
    \c alerts
    CREATE EXTENSION postgis;
    ```

    #### 2. Configure Connection

    In `.env`:

    ```bash
    POSTGRES_HOST=your-db-host.example.com
    POSTGRES_PORT=5432
    POSTGRES_DB=alerts
    POSTGRES_USER=postgres
    POSTGRES_PASSWORD=your-secure-password
    ```

=== "Managed Database"

    Use cloud PostgreSQL (AWS RDS, Azure, etc.):

    #### Requirements

    - PostgreSQL 14+ with PostGIS extension enabled
    - Network access from EAS Station container
    - SSL/TLS recommended for production

    #### Configuration

    ```bash
    POSTGRES_HOST=your-instance.region.rds.amazonaws.com
    POSTGRES_PORT=5432
    POSTGRES_DB=alerts
    POSTGRES_USER=easadmin
    POSTGRES_PASSWORD=your-secure-password
    ```

## Application Installation

### 1. Clone Repository

```bash
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
```

### 2. Create Configuration

```bash
cp .env.example .env
```

### 3. Configure Environment

Edit `.env` with your settings. See [Configuration Guide](configuration.md) for details.

**Minimum required changes:**

```bash
# Generate secure key
SECRET_KEY=your-64-character-hex-key-here

# Database
POSTGRES_HOST=alerts-db  # or your external host
POSTGRES_PASSWORD=change-this-password

# Location
DEFAULT_COUNTY_NAME="Your County"
DEFAULT_STATE_CODE=XX
```

### 4. Review docker-compose.yml

The default `docker-compose.yml` includes:

```yaml
services:
  eas-station:
    build: .
    ports:
      - "5000:5000"
    environment:
      - POSTGRES_HOST=${POSTGRES_HOST}
    volumes:
      - ./static/eas_messages:/app/static/eas_messages
      - ./logs:/app/logs

  alerts-db:
    image: postgis/postgis:17-3.4
    environment:
      POSTGRES_DB: alerts
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

### 5. Build and Start

```bash
docker compose up -d --build
```

Build output:

```
[+] Building 45.2s (18/18) FINISHED
 => [internal] load build definition
 => => transferring dockerfile
 => [internal] load .dockerignore
 => [1/12] FROM docker.io/library/python:3.11-slim
 ...
 => exporting to image
 => => naming to docker.io/library/eas-station

[+] Running 3/3
 ✔ Network eas-station_default    Created
 ✔ Container alerts-db             Started
 ✔ Container eas-station           Started
```

### 6. Verify Deployment

```bash
# Check container status
docker compose ps

# View logs
docker compose logs

# Follow logs in real-time
docker compose logs -f
```

### 7. Access Application

Open browser to:

- **Dashboard**: http://localhost:5000
- **Admin**: http://localhost:5000/admin
- **Health Check**: http://localhost:5000/system_health

## Post-Installation

### Initial Database Setup

On first launch, EAS Station automatically:

1. Creates database tables
2. Initializes PostGIS spatial extensions
3. Loads event codes and FIPS codes
4. Sets up initial admin user (if applicable)

### Verify Installation

1. **Check system health**: Navigate to `/system_health`
2. **Verify database**: Should show "Connected" status
3. **Test alert poller**: Watch logs for polling activity
4. **Access admin panel**: Configure first alert source

## Troubleshooting Installation

### Container Won't Start

```bash
# Check logs for errors
docker compose logs eas-station

# Verify environment file
cat .env | grep -v "^#" | grep -v "^$"

# Check Docker resources
docker system df
```

### Database Connection Failed

```bash
# Test database connectivity
docker compose exec eas-station python -c "
from sqlalchemy import create_engine
import os
engine = create_engine(f\"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}/{os.getenv('POSTGRES_DB')}\")
print(engine.connect())
"
```

### Permission Errors

```bash
# Fix volume permissions
sudo chown -R $USER:$USER ./static/eas_messages ./logs

# Restart containers
docker compose restart
```

### Port Conflicts

If port 5000 is in use:

```yaml
# In docker-compose.yml
ports:
  - "8080:5000"  # Use different port
```

## Upgrading

### Standard Upgrade

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose up -d --build

# Check for database migrations
docker compose logs | grep "migration"
```

See [Upgrade Guide](../admin-guide/upgrades.md) for detailed instructions.

## Uninstallation

### Remove Containers

```bash
# Stop and remove containers
docker compose down

# Remove volumes (WARNING: deletes database)
docker compose down -v
```

### Clean Up

```bash
# Remove images
docker rmi eas-station

# Remove cloned repository
cd .. && rm -rf eas-station
```

## Next Steps

After installation:

- [Configure System](configuration.md)
- [Set Up First Alert](first-alert.md)
- [Configure Hardware](../user-guide/hardware/index.md)
- [Learn the Interface](../user-guide/dashboard.md)

---

For deployment in production environments, see the [Administrator Guide](../admin-guide/index.md).
