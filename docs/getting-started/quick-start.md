# Quick Start Guide

Get EAS Station running in 5 minutes! This guide will have you monitoring alerts in no time.

!!! warning "Experimental Software"
    EAS Station is for laboratory use only. Do not use for production emergency alerting.

## Prerequisites

Before starting, ensure you have:

- ✅ Docker Engine 24+ with Compose V2
- ✅ 4GB RAM available
- ✅ Internet connection
- ✅ PostgreSQL database (can use embedded container)

## One-Command Installation

For the fastest setup, run this command:

```bash
git clone https://github.com/KR8MER/eas-station.git && \
cd eas-station && \
cp .env.example .env && \
docker compose up -d --build
```

This will:

1. Clone the repository
2. Create configuration file
3. Build and start all services

!!! tip "First Launch"
    The first build takes 3-5 minutes as Docker downloads and builds images. Subsequent starts are much faster.

## Step-by-Step Setup

If you prefer a guided approach:

### 1. Clone the Repository

```bash
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
```

### 2. Create Configuration

Copy the example configuration:

```bash
cp .env.example .env
```

### 3. Edit Configuration (Important!)

Open `.env` in your text editor and update:

=== "Minimal Configuration"

    For testing, update these **required** settings:

    ```bash
    # Generate a secure key
    SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

    # Database (use embedded PostgreSQL for testing)
    POSTGRES_HOST=alerts-db
    POSTGRES_PASSWORD=a-secure-password-here

    # Your location
    DEFAULT_COUNTY_NAME="Your County"
    DEFAULT_STATE_CODE=XX
    DEFAULT_ZONE_CODES=XXZ001
    ```

=== "External Database"

    If using an existing PostgreSQL server:

    ```bash
    # Database connection
    POSTGRES_HOST=your-database-host.example.com
    POSTGRES_PORT=5432
    POSTGRES_DB=alerts
    POSTGRES_USER=postgres
    POSTGRES_PASSWORD=your-secure-password
    ```

!!! danger "Security Alert"
    **Never use default passwords in production!** Generate a secure `SECRET_KEY`:

    ```bash
    python3 -c 'import secrets; print(secrets.token_hex(32))'
    ```

### 4. Start Services

Start EAS Station with Docker Compose:

```bash
docker compose up -d --build
```

Expected output:

```plaintext
[+] Building 45.2s (18/18) FINISHED
[+] Running 2/2
 ✔ Container alerts-db     Started
 ✔ Container eas-station   Started
```

### 5. Verify Installation

Check that services are running:

```bash
docker compose ps
```

You should see:

```plaintext
NAME            STATE     PORTS
alerts-db       running   5432/tcp
eas-station     running   0.0.0.0:5000->5000/tcp
```

### 6. Access the Interface

Open your browser to:

- **Main Dashboard**: [http://localhost:5000](http://localhost:5000)
- **Admin Panel**: [http://localhost:5000/admin](http://localhost:5000/admin)
- **System Health**: [http://localhost:5000/system_health](http://localhost:5000/system_health)

!!! success "Installation Complete!"
    You should see the EAS Station dashboard with a map and alert statistics.

## Initial Setup Wizard

On first launch, you'll see a setup wizard that helps you:

1. ✅ Verify database connection
2. ✅ Set up geographic location
3. ✅ Configure first alert source
4. ✅ Test system components

Follow the on-screen prompts to complete setup.

## Add Your First Alert Source

To start monitoring alerts:

1. Navigate to **Admin** → **Alert Sources**
2. Click **Add Source**
3. Choose **NOAA Weather Alerts**
4. Select your state(s)
5. Click **Save**

Alerts will begin polling automatically within 3 minutes.

## Verify It's Working

### Check System Health

Visit the [System Health](http://localhost:5000/system_health) page to verify:

- ✅ Database connection
- ✅ Alert polling active
- ✅ No error messages

### Monitor Logs

Watch real-time logs:

```bash
docker compose logs -f
```

You should see:

```plaintext
eas-station | INFO: Alert poller started
eas-station | INFO: Polling NOAA Weather Service...
eas-station | INFO: Retrieved 15 alerts
```

### View Alerts

Check the main dashboard. Within 3-5 minutes you should see:

- Active alerts on the map
- Alert statistics
- Recent alerts list

## Common Quick Start Issues

### Port 5000 Already in Use

If port 5000 is busy, change it in `docker-compose.yml`:

```yaml
ports:
  - "8080:5000"  # Use port 8080 instead
```

Then access via `http://localhost:8080`

### Database Connection Failed

If using external PostgreSQL:

1. Verify database exists: `psql -h <host> -U postgres -l`
2. Enable PostGIS: `CREATE EXTENSION postgis;`
3. Check firewall allows port 5432
4. Use `host.docker.internal` for localhost

### No Alerts Appearing

1. Check alert sources are configured
2. Verify internet connectivity
3. Wait 3-5 minutes for first poll
4. Check logs for errors: `docker compose logs`

## Next Steps

Now that EAS Station is running:

<div class="grid cards" markdown>

-   :material-map:{ .lg .middle } **Configure Location**

    ---

    Set up geographic boundaries for alert filtering

    [:octicons-arrow-right-24: Boundaries Guide](../user-guide/boundaries.md)

-   :material-radio:{ .lg .middle } **Add Hardware**

    ---

    Connect SDR receivers, GPIO relays, LED signs

    [:octicons-arrow-right-24: Hardware Setup](../user-guide/hardware/index.md)

-   :material-volume-high:{ .lg .middle } **Enable Broadcasting**

    ---

    Configure SAME encoding and audio output

    [:octicons-arrow-right-24: Configuration Guide](configuration.md)

-   :material-book-open-variant:{ .lg .middle } **Learn More**

    ---

    Explore all features in the user guide

    [:octicons-arrow-right-24: User Guide](../user-guide/index.md)

</div>

## Getting Help

Need assistance?

- 📖 **Documentation**: Continue to [Installation Guide](installation.md) for detailed setup
- 🐛 **Issues**: [Report a bug](https://github.com/KR8MER/eas-station/issues)
- 💬 **Community**: [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
- ⚙️ **Troubleshooting**: [Common Problems](../user-guide/troubleshooting.md)

---

**Congratulations!** 🎉 You've successfully installed EAS Station. Continue to the [Configuration Guide](configuration.md) to customize your setup.
