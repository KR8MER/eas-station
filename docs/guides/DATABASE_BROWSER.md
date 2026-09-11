# Database Browser (pgweb)

[pgweb](https://github.com/sosedoff/pgweb) is an optional third-party tool for
browsing and querying the EAS Station PostgreSQL database directly from a
browser — useful for ad-hoc troubleshooting that goes beyond what any admin
page exposes. It is **not** installed by `install.sh`; setting it up is a
deliberate, opt-in choice an operator makes on their own box.

> **pgweb has no login of its own.** Anyone who can reach its port gets full,
> unauthenticated read/write SQL access to every table in the database —
> including administrator accounts. Follow the setup below exactly; do not
> expose pgweb's own port directly.

---

## How access is protected

- pgweb's systemd unit (`systemd/eas-station-pgweb.service`) binds it to
  `127.0.0.1` only, on an internal port (`18081`) — it is never reachable
  over the network by itself.
- The `listen 8081` server block in `config/nginx-eas-station.conf` is the
  *only* supported way in. Before proxying a request through to pgweb, nginx
  calls back into the Flask app (`/api/internal/pgweb-auth-check`, an
  `auth_request` subrequest) to confirm the caller has a signed-in session
  with the `system.configure` permission — the same gate this app's other
  highest-sensitivity admin actions (e.g. downloading the TLS private key)
  already use. An unauthenticated or under-privileged request is redirected
  to `/login` instead of reaching pgweb at all.
- **Settings → Data & Storage → Database Browser (pgweb)** in the web UI
  shows whether the service is installed and running, and links to the
  authenticated port — see `webapp/admin/database_browser.py`.

## Installing pgweb

1. Download a pgweb release binary for your platform from the
   [project's releases page](https://github.com/sosedoff/pgweb/releases) and
   place it at `/usr/local/bin/pgweb` (`chmod +x`).
2. Install the service files from this repository:
   ```bash
   sudo cp bin/eas-station-pgweb-launch.sh /opt/eas-station/bin/
   sudo chmod +x /opt/eas-station/bin/eas-station-pgweb-launch.sh
   sudo cp systemd/eas-station-pgweb.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now eas-station-pgweb.service
   ```
3. Re-deploy nginx's config (`update.sh` does this on every run; to apply it
   immediately without a full update, copy `config/nginx-eas-station.conf`
   to `/etc/nginx/sites-available/eas-station`, run `sudo nginx -t`, then
   `sudo systemctl reload nginx`).
4. If the host's firewall is managed by UFW (the default since `install.sh`
   v2.19.7+), allow port 8081 from your LAN, matching the pattern the
   Icecast and NTP Server firewall integrations already use — e.g.:
   ```bash
   sudo ufw allow from 192.168.1.0/24 to any port 8081 proto tcp comment eas-station-pgweb
   ```
   Restricting this to your own subnet, rather than "Anywhere", still
   matters even with the authentication gate above — it's defense in depth,
   not a substitute for it.
5. Open **Settings → Data & Storage → Database Browser (pgweb)** to confirm
   the service shows as *Installed* / *Running*, then use the link there
   (do not bookmark or link the raw `18081` port anywhere — it isn't meant
   to be reached directly).

## Removing pgweb

```bash
sudo systemctl disable --now eas-station-pgweb.service
sudo rm /etc/systemd/system/eas-station-pgweb.service /opt/eas-station/bin/eas-station-pgweb-launch.sh
sudo systemctl daemon-reload
```

The nginx `listen 8081` server block and the Flask auth-check route can stay
in place — they answer with nothing useful once pgweb itself is gone.
