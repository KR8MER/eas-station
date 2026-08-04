#!/bin/bash
# EAS Station — SessionStart hook for Claude Code on the web.
#
# Brings a fresh remote container to the point where the full test suite, the
# linter and the browser harness all work, without anyone having to rediscover
# the setup each session.
#
# What it provisions:
#   * apt: PostGIS, Redis, ffmpeg, libsndfile  (system deps the tests touch)
#   * pip: requirements.txt + pytest / ruff / playwright
#   * a running PostgreSQL cluster with the PostGIS extension enabled
#   * a running Redis server
#   * DATABASE_URL / SECRET_KEY / REDIS_* exported for the session
#
# Design notes:
#   * Idempotent — safe to re-run; every step checks before acting.
#   * Non-interactive — DEBIAN_FRONTEND=noninteractive, no prompts.
#   * Degrades gracefully — if PostgreSQL cannot be provisioned the hook does
#     NOT export DATABASE_URL, so tests/conftest.py falls back to its
#     sqlite:///:memory: default and the bulk of the suite still runs. A broken
#     database must not take the whole session down.
#   * `set -u`/`-o pipefail` but NOT `-e`: a failed optional step should be
#     reported and skipped, not abort the session.

set -uo pipefail

log() { echo "[eas-setup] $*"; }
warn() { echo "[eas-setup] WARNING: $*" >&2; }

# Only provision remote (Claude Code on the web) containers. A developer's own
# machine already has its environment and must not be modified.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  log "not a remote session; skipping provisioning"
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$PROJECT_DIR" || { warn "cannot cd to $PROJECT_DIR"; exit 0; }

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
# ffmpeg backs the audio-source tests; libsndfile1 is needed by soundfile;
# PostGIS because CAPAlert carries a geometry column; Redis because several
# audio/coordination tests talk to a real server rather than a mock.
PG_MAJOR="$(ls -1 /usr/lib/postgresql 2>/dev/null | sort -V | tail -1)"
PG_MAJOR="${PG_MAJOR:-16}"

# Split into two tiers so a slow optional download can never hang a session.
# Essential: without these the database- and Redis-backed tests cannot run.
APT_ESSENTIAL=(
  "postgresql-${PG_MAJOR}"
  "postgresql-${PG_MAJOR}-postgis-3"
  "postgresql-${PG_MAJOR}-postgis-3-scripts"
  redis-server
  libsndfile1
)
# Optional: ffmpeg pulls ~100 MB of codec dependencies. Tests that need it are
# already listed in tests/known_failures.txt, so its absence costs coverage but
# does not break the run.
APT_OPTIONAL=(ffmpeg)

apt_install() {
  local budget="$1"; shift
  local missing=()
  for pkg in "$@"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  [ ${#missing[@]} -eq 0 ] && return 0

  log "installing: ${missing[*]}"
  timeout "$budget" apt-get install -y -qq "${missing[@]}" >/dev/null 2>&1
  local rc=$?
  # 124 is timeout(1)'s signal that the budget was exhausted. Reconcile any
  # half-configured packages so a later apt call is not blocked by them.
  if [ $rc -eq 124 ]; then
    warn "timed out installing: ${missing[*]}"
    dpkg --configure -a >/dev/null 2>&1
  elif [ $rc -ne 0 ]; then
    warn "failed to install: ${missing[*]}"
    dpkg --configure -a >/dev/null 2>&1
  fi
  return $rc
}

if ! dpkg -s "postgresql-${PG_MAJOR}-postgis-3" >/dev/null 2>&1 \
   || ! dpkg -s redis-server >/dev/null 2>&1 \
   || ! dpkg -s ffmpeg >/dev/null 2>&1; then
  log "refreshing apt index"
  timeout 240 apt-get update -qq >/dev/null 2>&1 || warn "apt-get update timed out; using cached index"
fi

apt_install 600 "${APT_ESSENTIAL[@]}"
apt_install 300 "${APT_OPTIONAL[@]}"

export PATH="$PATH:/usr/lib/postgresql/${PG_MAJOR}/bin"

# ---------------------------------------------------------------------------
# 2. Python dependencies
# ---------------------------------------------------------------------------
# setuptools/wheel go first: feedparser pulls in sgmllib3k, whose legacy
# setup.py fails to build against the distro's older setuptools.
log "installing Python dependencies"
python3 -m pip install --quiet --upgrade --ignore-installed setuptools wheel >/dev/null 2>&1 \
  || warn "setuptools/wheel upgrade failed"

if ! python3 -m pip install --quiet --ignore-installed -r requirements.txt >/dev/null 2>&1; then
  warn "requirements.txt install reported errors; retrying verbosely"
  python3 -m pip install --ignore-installed -r requirements.txt 2>&1 | tail -20
fi

# Test/lint/browser tooling is not in requirements.txt (it is runtime-only).
python3 -m pip install --quiet pytest pytest-asyncio ruff playwright >/dev/null 2>&1 \
  || warn "dev tooling install failed"

# ---------------------------------------------------------------------------
# 3. PostgreSQL + PostGIS
# ---------------------------------------------------------------------------
PGPORT_WANTED=5432
PGDATA_DIR=/var/lib/postgresql/claude-session
PG_DB=eas_test
PG_READY=0

if command -v initdb >/dev/null 2>&1; then
  id postgres >/dev/null 2>&1 || useradd -m postgres >/dev/null 2>&1
  mkdir -p /var/lib/postgresql
  chown postgres:postgres /var/lib/postgresql

  if [ ! -s "$PGDATA_DIR/PG_VERSION" ]; then
    log "creating PostgreSQL cluster at $PGDATA_DIR"
    rm -rf "$PGDATA_DIR"
    mkdir -p "$PGDATA_DIR"
    chown postgres:postgres "$PGDATA_DIR"
    # --auth=trust: this cluster is local to an ephemeral container and is
    # never reachable from outside it.
    su postgres -c "PATH=\$PATH:/usr/lib/postgresql/${PG_MAJOR}/bin initdb -D '$PGDATA_DIR' -U postgres --auth=trust" \
      >/dev/null 2>&1 || warn "initdb failed"
  fi

  if [ -s "$PGDATA_DIR/PG_VERSION" ]; then
    if ! su postgres -c "PATH=\$PATH:/usr/lib/postgresql/${PG_MAJOR}/bin pg_ctl -D '$PGDATA_DIR' status" >/dev/null 2>&1; then
      log "starting PostgreSQL on port $PGPORT_WANTED"
      su postgres -c "PATH=\$PATH:/usr/lib/postgresql/${PG_MAJOR}/bin pg_ctl -D '$PGDATA_DIR' -l '$PGDATA_DIR/server.log' -o '-p $PGPORT_WANTED' -w start" \
        >/dev/null 2>&1 || warn "pg_ctl start failed; see $PGDATA_DIR/server.log"
    else
      log "PostgreSQL already running"
    fi

    for _ in $(seq 1 20); do
      psql -h localhost -p "$PGPORT_WANTED" -U postgres -tc 'SELECT 1' >/dev/null 2>&1 && { PG_READY=1; break; }
      sleep 1
    done
  fi
fi

if [ "$PG_READY" = "1" ]; then
  psql -h localhost -p "$PGPORT_WANTED" -U postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname='${PG_DB}'" 2>/dev/null | grep -q 1 \
    || psql -h localhost -p "$PGPORT_WANTED" -U postgres -c "CREATE DATABASE ${PG_DB}" >/dev/null 2>&1
  if psql -h localhost -p "$PGPORT_WANTED" -U postgres -d "$PG_DB" \
       -c "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null 2>&1; then
    log "PostgreSQL ready with PostGIS (database: ${PG_DB})"
  else
    warn "PostGIS extension unavailable; geometry-backed tests will skip"
  fi

  # Schema bootstrap — deliberately mirrors what install.sh does on a real
  # deployment (see its "creating schema with db.create_all()" path):
  #
  #   1. db.create_all()     build the current schema from the models
  #   2. alembic stamp head  record that the database is at the current head
  #
  # A plain `alembic upgrade head` CANNOT bootstrap an empty database: no
  # migration in app_core/migrations/versions/ creates the base tables, so the
  # first migration that references cap_alerts dies with UndefinedTable. The
  # migration chain is incremental-only and assumes the model-built schema is
  # already present.
  #
  # Stamping matters: without it the database carries no alembic_version row,
  # and the next `alembic upgrade head` — say, after someone adds a migration
  # during a session — would try to replay the entire history and fail. With
  # the stamp, new migrations apply cleanly on top.
  export SKIP_DB_INIT=1  # suppress background workers during schema work
  SESSION_DB_URL="postgresql://postgres@localhost:${PGPORT_WANTED}/${PG_DB}"

  TABLE_COUNT="$(psql -h localhost -p "$PGPORT_WANTED" -U postgres -d "$PG_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo 0)"
  if [ "${TABLE_COUNT:-0}" -lt 10 ]; then
    log "creating database schema (db.create_all)"
    DATABASE_URL="$SESSION_DB_URL" \
    SECRET_KEY="claude-session-secret-key-not-for-production-0123456789" \
    LOG_LEVEL=ERROR \
    python3 -c "
from app import app
from app_core.extensions import db
with app.app_context():
    db.create_all()
" >/dev/null 2>&1 || warn "schema creation reported errors"
    TABLE_COUNT="$(psql -h localhost -p "$PGPORT_WANTED" -U postgres -d "$PG_DB" -tAc \
      "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo 0)"
  fi

  # Stamp (or, if already stamped, apply anything newer than the recorded
  # revision — which is what makes a session pick up migrations added on the
  # branch since the container was last built).
  STAMPED="$(psql -h localhost -p "$PGPORT_WANTED" -U postgres -d "$PG_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='alembic_version'" 2>/dev/null || echo 0)"
  if [ "${STAMPED:-0}" = "0" ]; then
    log "stamping alembic at head"
    DATABASE_URL="$SESSION_DB_URL" SECRET_KEY="claude-session-secret-key-not-for-production-0123456789" \
      python3 -m alembic stamp head >/dev/null 2>&1 || warn "alembic stamp failed"
  else
    log "applying any pending migrations"
    DATABASE_URL="$SESSION_DB_URL" SECRET_KEY="claude-session-secret-key-not-for-production-0123456789" \
      python3 -m alembic upgrade head >/dev/null 2>&1 || warn "alembic upgrade reported errors"
  fi

  ALEMBIC_REV="$(psql -h localhost -p "$PGPORT_WANTED" -U postgres -d "$PG_DB" -tAc \
    "SELECT version_num FROM alembic_version LIMIT 1" 2>/dev/null | tr -d ' ')"
  log "schema has ${TABLE_COUNT} tables, alembic at ${ALEMBIC_REV:-<unstamped>}"
  unset SKIP_DB_INIT
else
  warn "PostgreSQL not available; tests will fall back to in-memory SQLite"
fi

# ---------------------------------------------------------------------------
# 4. Redis
# ---------------------------------------------------------------------------
if command -v redis-server >/dev/null 2>&1; then
  if redis-cli ping >/dev/null 2>&1; then
    log "Redis already running"
  else
    log "starting Redis"
    # --save '': no RDB snapshots wanted for throwaway session state.
    redis-server --daemonize yes --port 6379 --save '' >/dev/null 2>&1 || warn "redis start failed"
    for _ in $(seq 1 10); do redis-cli ping >/dev/null 2>&1 && break; sleep 1; done
  fi
fi

# ---------------------------------------------------------------------------
# 5. Session environment
# ---------------------------------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    # conftest.py only applies its sqlite:///:memory: default when
    # DATABASE_URL is unset, so exporting this is what lets the
    # PostGIS-backed tests actually run instead of skipping.
    if [ "$PG_READY" = "1" ]; then
      echo "export DATABASE_URL='postgresql://postgres@localhost:${PGPORT_WANTED}/${PG_DB}'"
    fi
    echo "export SECRET_KEY='claude-session-secret-key-not-for-production-0123456789'"
    echo "export REDIS_HOST='localhost'"
    echo "export REDIS_PORT='6379'"
    echo "export LOG_LEVEL='WARNING'"
    # Playwright ships its Chromium under a versioned directory; pin the exact
    # binary so browser scripts do not have to go looking for it.
    CHROME_BIN="$(ls -1d /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)"
    [ -n "$CHROME_BIN" ] && echo "export CHROMIUM_BIN='$CHROME_BIN'"
  } >> "$CLAUDE_ENV_FILE"
  log "session environment written to CLAUDE_ENV_FILE"
fi

log "setup complete"
exit 0
