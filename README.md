# NOAA Alerts System Container Usage

This project ships with a production-oriented Dockerfile so you can run the
Flask application in a container. The commands below assume you are in the
repository root (`noaa_alerts_systems/`) on a machine with Docker installed.

## Check in the container resources

After copying these container files into your local checkout, stage and commit
them so they are tracked in Git:

```bash
git add Dockerfile .dockerignore docker-compose.yml requirements.txt README.md
git commit -m "Add container tooling for NOAA Alerts"
```

If you renamed or moved any files, update the `git add` list accordingly before
committing. Push the commit to your remote repository when you are ready to
share it:

```bash
git push origin <your-branch-name>
```

Replace `<your-branch-name>` with the branch that should contain the container
changes (for example, `main` or a feature branch).

## Option A: Docker Compose (recommended for local development)

The repository now includes a `docker-compose.yml` that provisions both the
application and a PostgreSQL database. To build the container image and start
everything with sane defaults:

```bash
docker compose build
docker compose up -d
```

The API will be available at http://localhost:5000 and PostgreSQL is exposed on
localhost:5432. Edit the environment variables in `docker-compose.yml` to match
your hardware (for example the LED sign IP/port) or to point at an existing
database instead of the bundled container.

To inspect logs or shut the stack down:

```bash
docker compose logs -f app
docker compose down
```

## Option B: Manual Docker commands

If you prefer to manage dependencies yourself, you can still work with the
image directly.

### 1. Build the image

```bash
docker build -t noaa-alerts:latest .
```

### 2. Run database (if needed)

The application expects a PostgreSQL database exposed via the `DATABASE_URL`
environment variable. If you do not already have a database running, you can
start a disposable PostgreSQL container for local testing:

```bash
docker run --name noaa-db -e POSTGRES_DB=noaa_alerts \
    -e POSTGRES_USER=noaa_user -e POSTGRES_PASSWORD=change_me \
    -p 5432:5432 -d postgres:15
```

Update the credentials and port as needed for your environment.

### 3. Start the NOAA Alerts container

Run the application container and link it to your database by providing the
connection string and any other configuration you require:

```bash
docker run --name noaa-alerts --rm -p 5000:5000 \
    -e DATABASE_URL=postgresql://noaa_user:change_me@host.docker.internal:5432/noaa_alerts \
    -e SECRET_KEY=replace-this-with-a-secret-value \
    -e LED_SIGN_IP=192.168.1.100 \
    -e LED_SIGN_PORT=10001 \
    noaa-alerts:latest
```

* Use `host.docker.internal` if the PostgreSQL instance is running on your host
  machine. Replace it with the appropriate hostname/IP when running in other
  environments.
* Remove or adjust the `LED_SIGN_*` variables if you do not have the hardware
  attached.

The application will now be available at http://localhost:5000.

### 4. View logs / stop containers

```bash
docker logs -f noaa-alerts
```

When you are done, stop the containers:

```bash
docker stop noaa-alerts
# (Optional) stop and remove the database container as well
docker stop noaa-db && docker rm noaa-db
```

These steps should let you reproduce the deployment locally. Adapt the
configuration for production as needed.
