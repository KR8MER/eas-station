# Releasing EAS Station

This document describes how EAS Station releases are cut, how the artifacts
are signed, and how anyone can verify a download before trusting it.

## How a release happens

Releases are cut by the
[`release.yml`](https://github.com/KR8MER/eas-station/blob/main/.github/workflows/release.yml) GitHub Actions workflow,
which runs **automatically whenever a merge to `main` changes `VERSION`**.
There is no manual tagging, uploading, or signing step.

1. **Bump the version.** Update the root [`VERSION`](https://github.com/KR8MER/eas-station/blob/main/VERSION) file and
   move the corresponding notes in
   [`CHANGELOG.md`](../reference/CHANGELOG.md) from `[Unreleased]` into a new
   `## [X.Y.Z]` heading. The `tests/test_release_metadata.py` guardrail (run
   on every PR by `tests.yml`, and re-validated by `release.yml` itself
   before it builds anything) enforces that these stay aligned.
2. **Merge to `main`.** Landing the version bump on `main` publishes the
   release: the push changes `VERSION`, which triggers `release.yml`.
3. **Re-running by hand** (*Actions → Release → Run workflow*) is still
   available, e.g. after a failed run. A version that already has a release
   is skipped, so this is always safe.
4. **The workflow then:**
   - re-validates the release metadata (`tests/test_release_metadata.py`);
   - builds two reproducible source tarballs with `git archive` from the
     exact commit being released — a full one (`eas-station-X.Y.Z.tar.gz`)
     and a minimal one (`eas-station-X.Y.Z-minimal.tar.gz`), see below;
   - writes a `SHA256SUMS` checksum manifest covering both;
   - **signs all artifacts** with a GitHub artifact attestation (see below);
   - creates the `vX.Y.Z` tag and publishes a GitHub Release with both
     tarballs, checksums, and the changelog section for that version as the
     release notes.

The workflow is idempotent: if a release for the current `VERSION` already
exists, it exits without doing anything, so re-running it is safe.

## Dependency updates (automated)

Dependabot opens **one weekly PR** for all pip updates (the `python-deps` group
in `.github/dependabot.yml`). `.github/workflows/dependabot-sync.yml` then
commits the follow-up work to that PR, so nothing needs editing by hand:

1. `scripts/sync_dependency_versions.py` rewrites every documented version from
   `requirements.txt`: the README dependency tables, the README and footer
   shields (`templates/partials/tech_stack_badges.html`, alt/title text
   included) and `docs/reference/ABOUT.md`.
2. The same script's `--release` cuts a patch release: `VERSION`, the README
   version badge and a CHANGELOG heading. It is skipped when the PR already
   bumped `VERSION` past `main`, so the bot's own push does not loop.

**One-time setup:** create a fine-grained personal access token scoped to this
repository with *Contents: Read and write*, and save it as a **Dependabot**
secret named `DEPENDABOT_SYNC_TOKEN` (*Settings → Secrets and variables →
Dependabot*). Without it the job fails with instructions instead of pushing.

**Patch-only updates merge themselves.** `.github/workflows/dependabot-automerge.yml`
turns on GitHub auto-merge when the highest change in a Dependabot PR is a
patch release, so the PR merges once every required check passes on its final
commit (after the sync commit) and `release.yml` then publishes the new version.
Minor and major updates wait for review. Auto-merge is enabled with
`DEPENDABOT_SYNC_TOKEN` (a merge done for `GITHUB_TOKEN` would not trigger
`release.yml`), so that token also needs **Pull requests: Read and write**.

**If the PR conflicts** after `main` moves, comment `@dependabot recreate`.
Dependabot does not rebase a PR that someone else has pushed to, and the
workflow re-applies the sync to the recreated branch.

**Changing `requirements.txt` by hand** (outside Dependabot): run
`python scripts/sync_dependency_versions.py` before committing.
`tests/test_tech_stack_badges.py` fails CI on any drift and names the command.

## Deploying to the Pi

Merging to `main` also deploys to the station's Raspberry Pi automatically
(migrations, restart, health check, rollback on failure), and an hourly
watchdog reports problems as a GitHub issue. See
[Automatic Deploys and Health Watchdog](../maintenance/PI_AUTODEPLOY.md).

## Full vs. minimal tarball

Every release publishes two source tarballs:

- **`eas-station-X.Y.Z.tar.gz`** — the complete repository at the released
  commit: application code, the test suite, CI workflow files, and every
  dev-tooling config. Use this if you plan to develop, test, or contribute.
- **`eas-station-X.Y.Z-minimal.tar.gz`** — everything needed to actually
  *run* EAS Station, with dev/CI-only content removed: `tests/`, `.github/`,
  `scripts/diagnostics/`, `.vscode/`, `.claude/`, and repo-root tool config
  that nothing at runtime reads (`mkdocs.yml`, `pyproject.toml`,
  `.coderabbit.yaml`). Use this for an actual deployment.

  `docs/` is **not** trimmed from the minimal tarball even though it isn't
  needed to develop the app — `webapp/documentation.py` and
  `webapp/public/` read it straight off disk at runtime to power the in-app
  `/docs` browser and the `/terms`/`/privacy`/policy pages, so it is a
  runtime dependency of the deployed app, not dev-only content. This is
  unrelated to the GitHub Pages documentation site, which is built by a
  separate workflow (`docs-pages.yml`) directly from the repository, not
  from either release tarball.

Both tarballs are built from the same commit, checksummed together in the
same `SHA256SUMS`, and signed the same way — see below.

## How releases are signed

We use **GitHub artifact attestations**
([`actions/attest-build-provenance`](https://github.com/actions/attest-build-provenance)),
which produce [Sigstore](https://www.sigstore.dev/)-backed
[SLSA build provenance](https://slsa.dev/spec/v1.0/provenance) for each
artifact.

Key properties of this scheme:

- **Keyless.** Signing uses a short-lived certificate bound to the workflow's
  OpenID Connect identity. There is no project GPG key to store, leak, or
  rotate, and no secret that a compromised maintainer laptop could expose.
- **Provenance, not just identity.** The attestation cryptographically binds
  each artifact's SHA-256 digest to the exact repository, commit SHA,
  workflow file, and Actions run that produced it. A tampered tarball — or a
  genuine-looking one built anywhere else — fails verification.
- **Transparency-logged.** Signatures are recorded in Sigstore's public
  transparency log, so signing events are publicly auditable.

## Verifying a download

Anyone with the [GitHub CLI](https://cli.github.com/) (`gh` ≥ 2.49) can verify
that a tarball was built by this repository's release workflow:

```bash
gh attestation verify eas-station-X.Y.Z.tar.gz --repo KR8MER/eas-station
```

A successful verification prints the workflow identity and the commit the
artifact was built from. Then confirm the file contents against the signed
checksum manifest:

```bash
gh attestation verify SHA256SUMS --repo KR8MER/eas-station
sha256sum --check SHA256SUMS
```

Verification without the GitHub CLI is also possible using
[`cosign`](https://docs.sigstore.dev/cosign/system_config/installation/)
against the attestation bundle downloadable from the release's attestation
page (`https://github.com/KR8MER/eas-station/attestations`).

## What is *not* signed

- Individual git commits are signed only when the author signs them (GitHub
  additionally signs merge commits created through the web UI with its
  `web-flow` key). The repository does not currently require signed commits.
- Cloning the repository directly (as `install.sh` does) is authenticated by
  TLS to github.com, not by artifact signatures. For a verifiable supply
  chain, prefer the release tarballs.
