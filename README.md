# NOAA Alerts System Container Usage

This project ships with a production-oriented Dockerfile so you can run the
Flask application in a container. Now that the repository is public you no
longer need to provide build arguments or copy the source from another machine.
Docker can fetch the repository directly from GitHub when you build the image.

The commands below assume Docker is installed on the machine where you are
building or running the container. Substitute a different branch name if you do
not want to build `main`.

## Quick command reference (public GitHub repository)

You can hand Docker the HTTPS URL of the repository and let it download the
source automatically. The optional `#main` suffix selects the branch to build;
change it if you want a different ref.

```bash
# Build the application image straight from GitHub
docker build -t noaa-alerts:latest \
  https://github.com/KR8MER/noaa_alerts_systems.git#main

# Start the stack with Docker Compose (uses the freshly built image)
docker compose up -d

# Follow application logs
docker compose logs -f app

# Shut everything down when finished
docker compose down
```

If you prefer to keep a local checkout instead of relying on the remote build
context, clone the repository and run the same commands from the project root.

If you want Docker Compose to fetch everything without keeping a working copy
of the repository on disk, you can point Compose directly at the file hosted in
GitHub. Because the compose file now references the repository URL as its build
context, Docker downloads the application source as part of the build step.

```bash
docker compose -f https://raw.githubusercontent.com/KR8MER/noaa_alerts_systems/main/docker-compose.yml up -d
```

When you are finished, stop the stack in the same way:

```bash
docker compose -f https://raw.githubusercontent.com/KR8MER/noaa_alerts_systems/main/docker-compose.yml down
```

> **Tip:** When invoking Compose with a remote file, Docker stores the build
> context in a temporary directory under `~/.docker`. If you need to rebuild
> after pulling new commits, run `docker builder prune` or remove the cached
> directory so Docker downloads the latest revision.

## Option A: Docker Compose (recommended for local development)

The repository includes a `docker-compose.yml` that provisions both the
application and a PostgreSQL database. Build the container image and start the
stack from a local checkout:

```bash
git clone https://github.com/KR8MER/noaa_alerts_systems.git
cd noaa_alerts_systems
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
docker build -t noaa-alerts:latest \
    https://github.com/KR8MER/noaa_alerts_systems.git#main
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

## Applying this pull request to your repository

If you want to take the changes from the **Enable Compose builds from GitHub
source** pull request and land them in your own fork, you can do it entirely
from the command line. Replace `PR_NUMBER` with the pull request number on
GitHub (for example, `42`).

### Option 1: GitHub CLI (easiest)

```bash
gh repo clone KR8MER/noaa_alerts_systems
cd noaa_alerts_systems
gh pr checkout PR_NUMBER             # downloads the PR branch locally
# review / test the changes
gh pr merge PR_NUMBER --merge        # or --squash / --rebase as you prefer
```

### Option 2: Plain git commands

```bash
git clone https://github.com/KR8MER/noaa_alerts_systems.git
cd noaa_alerts_systems
git fetch origin pull/PR_NUMBER/head:pr-worktree
git checkout pr-worktree            # look around, run tests, etc.

# When you are ready to integrate the code:
git checkout main
git merge pr-worktree               # or `git cherry-pick` if you prefer
git push origin main
```

This workflow keeps the pull request branch separate while you review and test
the changes. Once you are satisfied, merge or cherry-pick the commits into your
main branch and push them back to GitHub.
