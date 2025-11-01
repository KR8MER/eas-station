# One-Button Upgrade Powered by the Docker Build Pipeline

The GitHub Actions workflow at [`.github/workflows/build.yml`](../../.github/workflows/build.yml) builds and publishes a fresh
`kr8mer/eas-station:latest` image whenever commits reach the `main` branch. You can treat the passing run as the guardrail that
unlocks a **one-button upgrade** experience for operators who maintain on-premises stations.

## 1. Make sure the pipeline stays green

1. Confirm the CI status badge at the top of the [README](../../README.md) is green before promoting a change.
2. If the workflow fails, inspect the run logs for container build issues, dependency errors, or Docker Hub authentication
   problems and fix them before shipping an upgrade.

## 2. Provide a wrapped `docker compose pull` + restart command

The default `docker-compose.yml` runs every service from the `eas-station:latest` tag for both the application and poller
workers. A single command can refresh the containers to the newest image that Actions just pushed:

```bash
docker compose pull app poller ipaws-poller
COMPOSE_PROFILES=embedded-db docker compose up -d --force-recreate app poller ipaws-poller
```

Wrap those commands in a shell script or a systemd service unit so field operators can execute it with a single click, a kiosk
button, or a physical GPIO trigger. The script should surface the Git hash and timestamp reported by `docker compose images`
after the upgrade so operators can confirm the version change.

## 3. Gate upgrades on a passing workflow run

Pair the upgrade button with the status badge link. Before allowing an operator to execute the upgrade script, check the latest
workflow run using the GitHub REST API or the badge URL:

- Green badge → latest image built successfully and is safe to pull.
- Red badge → block the upgrade and direct the operator to contact the development team.

## 4. Optional: Publish versioned tags for rollback

The workflow currently ships only the `latest` tag. If you want the button to support rollbacks, extend the
`docker/build-push-action` step with semantic version tags or short Git hashes. Update the upgrade script to accept a target tag:

```bash
TARGET_TAG=${1:-latest}
docker compose pull --quiet "kr8mer/eas-station:${TARGET_TAG}"
COMPOSE_PROFILES=embedded-db docker compose up -d --force-recreate \
  --build app poller ipaws-poller
```

Exposing the tag as a parameter lets operators downgrade to the previous known-good build in one step while keeping the default
experience to pull the `latest` image.
