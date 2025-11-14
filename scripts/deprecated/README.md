# Deprecated Scripts

This directory contains scripts that are no longer needed or maintained but are preserved for reference.

## Scripts in this Directory

### `init-env.sh` (Deprecated)

**Status:** No longer needed as of repository restructure

**Original Purpose:** Initialize environment by creating an empty `.env` file

**Why Deprecated:** The `.env` file is now included in the repository by default. The setup wizard handles all configuration through the web UI.

**Modern Alternative:** Use the setup wizard at `/setup` when you first start the application

---

### `update-stack.sh` (Deprecated)

**Status:** Outdated with hardcoded paths

**Original Purpose:** Pull latest changes and rebuild Docker containers

**Why Deprecated:** 
- Contains hardcoded paths specific to one installation (`/home/user/eas-station`)
- References a specific branch that no longer exists
- Generic Docker Compose commands work better for all deployments

**Modern Alternative:**
```bash
# Pull latest changes
git pull

# Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

### `validate_portainer_compose.py` (Deprecated)

**Status:** One-time validation tool

**Original Purpose:** Validate docker-compose files for Portainer compatibility by checking for `.env` file references

**Why Deprecated:** 
- The issue it was designed to catch (env_file references) has been resolved in the compose files
- No longer needed for current deployment workflows
- Portainer deployment is well-documented in guides

**Modern Alternative:** Follow the [Portainer Quick Start Guide](../../docs/deployment/portainer/PORTAINER_QUICK_START.md)

---

## Why Keep Deprecated Scripts?

These scripts are preserved for:
1. **Historical Reference** - Understanding past issues and solutions
2. **Migration Support** - Users upgrading from older versions may have references to these scripts
3. **Code Examples** - Some logic may be useful for future tools

## Migration Guidance

If you have documentation or scripts referencing these deprecated tools:

| Old Path | New Approach |
|----------|-------------|
| `./init-env.sh` | Use the web-based setup wizard at `/setup` |
| `./update-stack.sh` | Use standard `docker compose` commands |
| `./validate_portainer_compose.py` | Follow the Portainer deployment guide |

## Questions?

If you were using any of these scripts and need help migrating to the modern approach, please open an issue on GitHub.
