# Disk Space Cleanup Guide

This guide covers reclaiming disk space on a bare-metal EAS Station™ install. The system runs as a set of systemd services (`eas-station-*`), backed by PostgreSQL/PostGIS, Redis, and a local audio cache. The biggest consumers of disk over time are journal logs, the alert database, the Redis append-only file, and the optional audio archive.

> ⚠️ Read each section before you run the commands. Several of them remove data and have no undo.

---

## 1. See where the space is going

```bash
# Overall disk usage
df -h /

# Largest directories on the root volume (top 20)
sudo du -h -x -d 1 / 2>/dev/null | sort -h | tail -20

# EAS-specific hot spots
sudo du -sh \
  /var/lib/postgresql \
  /var/lib/redis \
  /var/log/eas-station \
  /var/log/journal \
  /tmp/eas-audio \
  /opt/eas-station 2>/dev/null
```

Anything in the multi-GB range below is normal candidate for cleanup; the application itself in `/opt/eas-station` should be in the low hundreds of MB.

---

## 2. Trim the systemd journal

`journalctl` keeps service logs (including all `eas-station-*` units) and can grow to several GB on a long-running node.

```bash
# Current journal size
journalctl --disk-usage

# Drop anything older than 14 days
sudo journalctl --vacuum-time=14d

# Or cap total journal size at 500 MB
sudo journalctl --vacuum-size=500M
```

To make the cap permanent, edit `/etc/systemd/journald.conf`:

```ini
SystemMaxUse=500M
MaxRetentionSec=14day
```

Then restart `systemd-journald`:

```bash
sudo systemctl restart systemd-journald
```

---

## 3. Rotate the EAS Station™ application logs

The web/poller/SDR services write into `/var/log/eas-station/`. Log rotation is handled by `logrotate` (config installed by `install.sh`), but if rotation has stalled you can prune by hand:

```bash
# Inspect
sudo ls -lh /var/log/eas-station/

# Compress files older than 7 days
sudo find /var/log/eas-station -type f -name '*.log' -mtime +7 -exec gzip {} \;

# Delete compressed files older than 30 days
sudo find /var/log/eas-station -type f -name '*.gz' -mtime +30 -delete

# Force logrotate to run now
sudo logrotate -f /etc/logrotate.d/eas-station
```

---

## 4. Audio archive (`/tmp/eas-audio`)

When `EAS_SAVE_AUDIO_FILES=true` (see `.env.example`) every captured EAS message and TTS render is written to `/tmp/eas-audio`. On Pi-class hardware this directory can grow to a few hundred MB during testing.

```bash
# How much space the audio cache is using
sudo du -sh /tmp/eas-audio

# Remove files older than 7 days
sudo find /tmp/eas-audio -type f -mtime +7 -delete

# Wipe the entire cache (services will recreate it on next write)
sudo rm -rf /tmp/eas-audio/*
```

Long-term, unless you are actively debugging a decode failure, keep `EAS_SAVE_AUDIO_FILES=false`. The Audio Archive page in the web UI surfaces the same recordings through the database without retaining raw WAVs on disk.

---

## 5. Redis append-only file

Redis stores its working state in `/var/lib/redis/appendonly.aof` (or `dump.rdb`). EAS Station™ uses Redis primarily as a pub/sub bus and for short-lived caches, so the AOF should normally stay under 100 MB. If it has grown, ask Redis to rewrite it:

```bash
# Trigger a background rewrite (compacts the AOF in place)
redis-cli BGREWRITEAOF

# Watch progress
redis-cli INFO persistence | grep -E 'aof_rewrite_in_progress|aof_current_size'
```

You should never need to delete `appendonly.aof` by hand on a running system — losing it means losing in-flight pub/sub state.

---

## 6. PostgreSQL maintenance

The alerts/audit/audio-archive tables grow with traffic. PostgreSQL's auto-vacuum keeps them healthy, but if you have ingested a backlog or imported large CAP archives you can reclaim space manually:

```bash
# Database disk usage by table (top 20)
sudo -u postgres psql eas_station -c "
  SELECT relname AS table,
         pg_size_pretty(pg_total_relation_size(relid)) AS total_size
  FROM pg_catalog.pg_statio_user_tables
  ORDER BY pg_total_relation_size(relid) DESC
  LIMIT 20;"

# Full vacuum + reindex (takes a brief lock — schedule for low-traffic window)
sudo -u postgres psql eas_station -c "VACUUM (VERBOSE, ANALYZE);"
sudo -u postgres psql eas_station -c "REINDEX DATABASE eas_station;"
```

For pruning very old data, prefer the in-app **Settings → Backups → Retention** controls or the `scripts/maintenance/` helpers — they understand FK relationships across the alerts/audit/audio tables. Do not `DELETE` from `alerts` or `audit_logs` directly.

---

## 7. Cleaning Up Duplicate Alerts

If the poller has ingested the same CAP alert more than once (typically after feed hiccups or re-imports), duplicate rows inflate the `alerts` table and its boundary-intersection records. The bundled utility `poller/duplicate_cleanup_utility.py` finds alerts that share the same CAP **identifier** and removes the extras, always **keeping the most recently created copy** of each.

Run it interactively from the install directory using the application's virtualenv (it needs the app's database configuration):

```bash
cd /opt/eas-station
sudo -u eas-station venv/bin/python poller/duplicate_cleanup_utility.py
```

The utility walks through these steps:

1. **Duplicate scan** — groups alerts by identifier and lists every identifier with more than one row, including event type, creation timestamps, and the database ID of each copy. It also exercises the poller's own duplicate detection as a cross-check.
2. **Pattern analysis** — summarizes which event types are duplicated most and the time gaps between duplicate inserts (useful for diagnosing *why* duplicates appeared).
3. **Interactive menu** — choose:
   - **1 — Dry run**: prints exactly which alert IDs would be kept and which would be removed. No changes are made.
   - **2 — Actually clean up (destructive)**: prompts you to type `DELETE DUPLICATES` to confirm, then deletes the older copies and commits.
   - **3 — Exit** without changes.

What it deletes and keeps:

| | Behaviour |
|---|---|
| **Kept** | The newest row (latest `created_at`) for each duplicate identifier |
| **Deleted** | All older rows with the same identifier |
| **Side effect** | Boundary-intersection records attached to a deleted alert are deleted with it (the tool warns per alert before removal) |

> ⚠️ Always run the dry run first and review the output. Deletion is permanent and removes the associated intersection records — there is no undo short of restoring a database backup.

If the database is clean, the utility reports "No duplicates found" and exits without prompting.

---

## 8. Optional: Postfix mail spool

If `eas-station-postal.service` is enabled (see [Local Mail Server guide](../guides/local_mail_server.md)), the deferred mail queue lives under `/var/spool/postfix/`. Check and flush it occasionally:

```bash
# How many deferred messages?
sudo postqueue -p | tail -1

# Flush the queue
sudo postqueue -f
```

---

## 9. Preventing future growth

1. **Cap the journal** — set `SystemMaxUse=` in `/etc/systemd/journald.conf` (see §2).
2. **Keep audio archiving off** — only set `EAS_SAVE_AUDIO_FILES=true` while debugging.
3. **Enable scheduled backups with retention** — `/admin/backups` rotates compressed dumps automatically.
4. **Alert on disk usage** — the System Health page (`/system_health`) reports root-volume usage; wire it into your monitoring (`/api/health/resources`) and notify above 80% utilisation.

---

## 10. Where else to look if the disk is still full

```bash
# Find every file > 100 MB on the root volume
sudo find / -xdev -type f -size +100M -exec ls -lh {} \; 2>/dev/null

# Anything growing inside the install directory
sudo du -h /opt/eas-station 2>/dev/null | sort -h | tail -20

# Stuck downloads, .pyc caches, abandoned tarballs
sudo find /tmp /var/tmp -type f -mtime +1 -size +50M 2>/dev/null
```

If none of the above explain the usage, check `lsof | grep deleted` — a service that still holds a handle to a deleted log can keep gigabytes pinned until restarted. `sudo systemctl restart eas-station-web.service` (or the relevant unit) frees the handle.
