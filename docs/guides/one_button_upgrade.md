# One-Click System Upgrade

**Admin → Operations** (`/admin/operations`, requires the `system.configure`
permission) has a **System Upgrade** card that runs the same upgrade
[`update.sh`](https://github.com/KR8MER/eas-station/blob/main/update.sh)
would perform from a terminal (`sudo bash update.sh`), without needing shell
access to the station. This page documents what the button actually does —
it previously described a Docker-based container pipeline this project does
not use; EAS Station is deployed bare-metal via `install.sh`/`update.sh`,
not containers.

## What it does

Clicking **Start Upgrade** launches `update.sh --non-interactive` as its own
transient systemd unit (`eas-station-update.service`, via
[`bin/eas-station-run-update`](https://github.com/KR8MER/eas-station/blob/main/bin/eas-station-run-update))
rather than as a direct child of the web process. That indirection matters:
`update.sh`'s own "Restarting Services" step restarts
`eas-station-web.service` itself, and if the upgrade ran as a subprocess of
that service it would be killed mid-run by its own restart before ever
reaching its summary. Running it as an independent unit lets it survive that
restart and keep writing to the journal the whole time, which is what the
page polls to show live progress.

Concretely, the same script performs:

1. Pulls the target ref (see "Choosing what to install" below).
2. Updates Python dependencies in the venv.
3. Applies pending Alembic database migrations.
4. Refreshes systemd unit files and reloads the daemon.
5. Restarts every EAS Station service.

## Using the page

- **Update check.** On page load the card checks whether the selected
  target has anything new to offer, via a read-only `git fetch` (it updates
  only this checkout's remote-tracking ref — never the working tree) —
  showing **Up to date** or **Update available** with a version and
  commit-count comparison. This is informational only; it doesn't gate the
  button, since a custom ref (a specific commit, for example) can't always
  be compared this way. Use **Check again** to re-run it after changing the
  version picker.
- **Choosing what to install.** The **Version to install** dropdown offers:
  - **Track main (latest)** — the default. Runs a plain `git pull` on
    whatever branch is currently checked out (`main` on a standard
    install) — identical to the upgrade button's original behavior.
  - One of the most recent **release tags** (`vX.Y.Z`), fetched live from
    the repository — see [Releasing EAS Station](../process/RELEASING.md)
    for how those tags get cut. Picking one pins the upgrade to that exact
    published version instead of whatever `main` currently looks like.
  - **Custom branch, tag, or commit…**, which reveals a free-text field for
    anything else — a feature branch, a specific commit SHA, etc.
- **Skip pre-upgrade backup.** `update.sh` takes a full `tar.gz` backup of
  the install before upgrading by default; check this box to skip it (not
  recommended — see [Database Backups](DATABASE_BACKUPS.md) if you need to
  browse, restore, or schedule backups instead of the quick one-off this
  page also offers).
- **Start Upgrade** asks for confirmation, then streams the same
  step-by-step output the CLI would print to a terminal into the log box
  below, with a progress bar driven by `update.sh`'s own `--- Step N/M ---`
  markers. Expect a brief disconnect partway through, when the "Restarting
  Services" step restarts the very page you're looking at — progress
  resumes automatically once the web service is back, and reloading the
  page later picks the log up from where it left off (it's read from the
  systemd journal, not in-memory state).

## Notes for operators

- Take the default backup unless you have a specific reason not to — an
  upgrade that fails partway through a migration is exactly what it's for.
- Pinning to a release tag is the right choice for a station that shouldn't
  ride whatever landed on `main` this week; track main if you want the
  latest fixes as soon as they merge.
- If the upgrade fails, the log box shows exactly where — check
  `sudo journalctl -u eas-station-update.service` for the full output, or
  restore the pre-upgrade backup from **Admin → Backups**.
