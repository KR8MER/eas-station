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
   docker compose down
   docker compose up -d --build
   ```
   * Running `docker compose down` first ensures the old containers are removed before rebuilding.
5. **Verify the running code version.**
   ```bash
   docker compose exec web git rev-parse --short HEAD
   ```
   * The hash shown should match the latest commit from `git log origin/<branch> -1`.

If you rely on system-wide Git or Docker privileges (e.g., using `sudo`), apply them consistently to each command above. Mixing privileged and non-privileged commands can leave your working tree or containers in a mismatched state.
