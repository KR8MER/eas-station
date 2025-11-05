# Keeping Your Local Build on the Latest Branch

Follow these steps to ensure your local `eas-station` environment tracks the latest code:

1. **Switch to the branch you expect to run.**
   ```bash
   git checkout main  # or the feature/fix branch you need
   ```
2. **Fetch the latest commits from the remote.**
   ```bash
   git fetch origin
   ```
3. **Update your local branch to match the remote tracking branch.**
   ```bash
   git pull --ff-only
   ```
   * Use `--ff-only` to guarantee you fast-forward to the remote history without creating a merge commit.
4. **Rebuild and restart your containers.**
   ```bash
   sudo docker compose down
   sudo docker compose up -d --build
   ```
   * Running `sudo docker compose down` first ensures the old containers are removed before rebuilding.
5. **Verify the running code version.**
   ```bash
   sudo docker compose exec web git rev-parse --short HEAD
   ```
   * The hash shown should match the latest commit from `git log origin/<branch> -1`.

**Note:** Docker commands require root privileges when running as a non-root user. Apply `sudo` consistently to all Docker commands to avoid permission issues.
