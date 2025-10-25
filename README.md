# NOAA Alerts System Container Usage

This project ships with a production-oriented Dockerfile so you can run the
Flask application in a container. Instead of copying the source code from your
workstation into the image, the Dockerfile clones the repository directly from
GitHub (or any other Git server you choose). The commands below assume Docker is
installed on the machine where you are building or running the container.

Set two build arguments whenever you build the image:

* `REPO_URL` – the HTTPS or SSH URL to the Git repository that contains the
  application.
* `REPO_REF` – the branch, tag, or commit SHA to check out. Defaults to `main`.

If you use Docker Compose, you can export these values into a `.env` file so you
do not need to pass them on every command. See the examples in the next
sections.

Replace `https://github.com/your-org/noaa_alerts_systems.git` in the examples
with the actual location of your repository before running the commands.

## Option A: Docker Compose (recommended for local development)

The repository now includes a `docker-compose.yml` that provisions both the
application and a PostgreSQL database. To build the container image and start
everything with sane defaults:

```bash
REPO_URL=https://github.com/your-org/noaa_alerts_systems.git \
REPO_REF=main \
  docker compose build
docker compose up -d
```

> **Tip:** Save the build arguments in a `.env` file next to the
> `docker-compose.yml` so future `docker compose` commands pick them up
> automatically:
>
> ```bash
> cat <<'EOF' > .env
> REPO_URL=https://github.com/your-org/noaa_alerts_systems.git
> REPO_REF=main
> EOF
> ```

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
docker build -t noaa-alerts:latest \
    --build-arg REPO_URL=https://github.com/your-org/noaa_alerts_systems.git \
    --build-arg REPO_REF=main \
    .
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
