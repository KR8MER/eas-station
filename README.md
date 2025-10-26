# NOAA Alerts System – Container Deployment Guide

This repository contains a Flask web UI, a CAP alert poller, and supporting
scripts for managing NOAA alert and GIS boundary data. The project now ships
with a Docker-first workflow that keeps all runtime configuration in a `.env`
file so you can run everything with a single `docker compose up`.

## Prerequisites

* Docker Engine 24+
* Docker Compose V2 (usually bundled with Docker Engine)

## 1. Configure environment variables

Copy the provided `.env` file and adjust any values that differ in your
environment. The defaults assume everything runs on the same Docker network and
that PostgreSQL listens on the `postgresql` service defined in
`docker-compose.yml`.

```bash
cp .env .env.local  # optional backup before editing
```

Key variables:

| Variable | Purpose |
| --- | --- |
| `POSTGRES_HOST` | Hostname or service name for PostgreSQL (inside Docker use the service name, **not** `localhost`). |
| `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database connection parameters shared by the Flask app and poller. |
| `DATABASE_URL` | SQLAlchemy connection string. Overridden automatically if you change the individual `POSTGRES_*` variables. |
| `POLL_INTERVAL_SEC` | Interval (seconds) between CAP poller runs in continuous mode. |
| `LED_SIGN_IP`, `LED_SIGN_PORT` | Optional LED sign integration. Remove or update if you do not use a sign. |
| `UPLOAD_FOLDER` | Directory inside the container used for temporary GeoJSON uploads. |

Avoid using `localhost` or `127.0.0.1` inside this file when both containers run
on the same Docker network. Use the Docker service name instead (for example,
`postgresql`).

## 2. Build and start the stack

From the project root run a single command that builds the images (if
necessary) and starts every service in the background:

```bash
docker compose up -d --build
```

Need everything in one go, including cloning the correct branch? Run this
single Bash command on any Docker-capable host:

```bash
bash -c 'git clone -b Test https://github.com/KR8MER/noaa_alerts_systems.git \
  && cd noaa_alerts_systems \
  && docker compose up -d --build'
```

The repository’s active branch is `Test`, so the command above ensures you pull
the same branch the project uses in production before launching the stack.

Services started by the compose file:

* **app** – Gunicorn serving the Flask UI and REST API on port 5000.
* **poller** – Background CAP poller that runs continuously using the same
  image as the web app.
* **postgresql** – PostgreSQL 15 with PostGIS-capable extensions (install those
  manually if you need them).

Access the UI at <http://localhost:5000> from the host machine. Inside Docker,
other services reach the web app via the `app` service name.

To tail logs or stop everything:

```bash
docker compose logs -f app
# or poller / postgresql

docker compose down
```

## 3. Running the CAP poller

### 3.1 Continuous polling in its own container

The compose file defines a dedicated **poller** service that launches
`python poller/cap_poller.py --continuous` in its own container. Set the
polling cadence in `.env` before starting the stack:

```bash
POLL_INTERVAL_SEC=180  # 3 minutes between requests to NOAA
```

Bring the poller online alongside the web app:

```bash
docker compose up -d poller
```

The container uses `restart: unless-stopped`, so it will automatically reconnect
to NOAA every three minutes and resume after Docker or host restarts. View the
poller logs at any time with:

```bash
docker compose logs -f poller
```

### 3.2 Running the CAP poller manually

To run the poller once or execute maintenance commands you can use `docker
compose run`:

```bash
docker compose run --rm poller python poller/cap_poller.py --fix-geometry
```

`cap_poller.py` now loads environment variables via `python-dotenv`, so the
poller behaves the same whether it runs inside Docker or from a local checkout.
It builds the database URL from the `POSTGRES_*` variables when `DATABASE_URL`
is not set, ensuring it connects to the `postgresql` service instead of trying
`127.0.0.1`.

## 4. Uploading boundary files

A recent bug in the admin UI pointed the upload form at
`/admin/upload_boundary`, which returned HTTP 404 in containerized deployments.
The JavaScript now calls `/admin/upload_boundaries`, matching the Flask route, so
GeoJSON uploads succeed again. If you still encounter upload failures ensure
that:

* The `UPLOAD_FOLDER` path from `.env` is writable by the container user.
* Your GeoJSON file is valid UTF-8 and contains a `features` array.
* PostgreSQL has the PostGIS extension installed (`CREATE EXTENSION postgis;`).

## 5. Debug utilities

`debug_apis.sh` now reads the base URL from the `API_BASE_URL` environment
variable (defaulting to `http://app:5000`) so you can run the script from inside
or outside Docker without editing it.

## 6. Production deployment notes

* Override `SECRET_KEY` in your `.env` file before exposing the app publicly.
* Map a Docker volume to `logs/` or the upload directory if you need to persist
  data across container restarts.
* Configure an SMTP relay via `MAIL_SERVER`, `MAIL_PORT`, and related settings in
  `.env`. The default no longer points at `localhost` to avoid misconfigured
  containers.

## 7. Updating containers

Pull the latest source and rebuild:

```bash
git pull
docker compose build --pull
docker compose up -d --force-recreate
```

Use `docker compose logs -f poller` to verify the CAP poller is running and
processing alerts.
