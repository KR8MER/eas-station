# Automatic Deploys and Health Watchdog (Pi)

Every merge to `main` deploys itself to the Raspberry Pi, and an hourly
watchdog opens a GitHub issue when the box looks unwell. Both run from
[`.github/workflows/deploy-pi.yml`](https://github.com/KR8MER/eas-station/blob/main/.github/workflows/deploy-pi.yml)
on a self-hosted GitHub Actions runner installed on the Pi.

## What happens on a merge

The `deploy` job calls `/usr/local/sbin/eas-deploy <commit>`, which:

1. **Refuses anything but `origin/main`'s current tip.** The runner can only
   deploy what is already merged.
2. **Refuses if `/opt/eas-station` has hand edits.** Hand edits there once
   silently reverted deployed fixes, so they now block the deploy instead.
3. Updates `/opt/eas-station`. A docs-, tests- or CI-only merge stops here,
   with no restart.
4. Installs requirements into both venvs if `requirements*.txt` changed.
5. **Runs database migrations before restarting.** New code must never start
   against an old schema.
6. **Waits up to 10 minutes if an alert is on air** (`eas:broadcast_active`),
   so a deploy never cuts off a broadcast.
7. Restarts `eas-station.target`, then waits up to 2 minutes for every
   service to be active and `/health` to return 200.
8. **Rolls back to the previous commit** if that fails. Migrations are not
   reverted. The job fails and GitHub emails you.

Changes to `systemd/` unit files are not installed automatically. The job
warns, and you run `update.sh`.

## What the watchdog checks (hourly)

`scripts/deploy/eas_watchdog.py` runs without root and checks:

| Check | Alarms when |
|---|---|
| Services | Any unit under `eas-station.target` is not active |
| Memory | A service's anonymous memory exceeds 1.5 GB (web: 3 GB) |
| Memory leak | A service grows ≥ 15 MB/h steadily for 6+ hours within one run |
| Swap | More than 50% used |
| Health | `/health` doesn't return 200 |
| Streams | An Icecast mount delivers < 85% of real time (listeners hear dropouts) |

While a problem persists, one issue labelled **watchdog** stays open and gets
a comment each hour. It closes itself with a "Recovered" comment when
everything passes again. To run it on demand: *Actions → Deploy to Pi → Run
workflow → watchdog*.

## Security model

- The runner runs as **`gh-runner`**, a system user with **no general sudo**.
- Its only privilege is one sudoers rule (`config/sudoers-gh-runner`): it may
  run `/usr/local/sbin/eas-deploy` as root, and that script deploys only
  merged `main`.
- The installed script is **root-owned and is not updated by deploys**. A merge
  cannot change what runs as root; you reinstall it after reviewing changes.
  The deploy job warns when the repo copy differs from the installed one.
- `deploy-pi.yml` triggers only on pushes to `main`, the schedule, or a manual
  run, never on pull requests. Outside contributors' workflow runs also need
  maintainer approval (repo setting: *Require approval for all external
  contributors*).

## One-time setup

1. **Install the runner** as user `gh-runner` with the label `eas-pi`
   (*Settings → Actions → Runners → New self-hosted runner*, Linux ARM64), and
   install it as a service with `./svc.sh install gh-runner`.
2. **Install the deploy script and its sudoers rule**, after reading both:

   ```bash
   cd /opt/eas-station
   sudo install -o root -g root -m 0755 scripts/deploy/eas-deploy.sh /usr/local/sbin/eas-deploy
   sudo install -o root -g root -m 0440 config/sudoers-gh-runner /etc/sudoers.d/gh-runner
   sudo visudo -c -f /etc/sudoers.d/gh-runner
   ```

## Updating the deploy script

When `scripts/deploy/eas-deploy.sh` changes on `main`, review the diff, then
re-run the first `install` line above. Until you do, the old script keeps
deploying and each deploy job shows a warning.

## Troubleshooting

- **"has local modifications"**: someone edited `/opt/eas-station` by hand.
  Commit the change through a PR, or discard it with
  `sudo -u eas-station git -C /opt/eas-station checkout -- .`, then re-run the
  deploy (*Actions → Deploy to Pi → Run workflow → deploy*).
- **"is not origin/main's tip"**: a newer merge landed while this job waited.
  The newer merge's own deploy covers it, so nothing needs doing.
- **"sudo: a password is required"**: the sudoers rule isn't installed. See
  *One-time setup*, step 2.
- **Deploy and rollback both unhealthy**: check
  `journalctl -u 'eas-station*' -n 200` on the Pi. The job log shows which
  units were inactive.
