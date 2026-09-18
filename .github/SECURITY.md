# Security Policy

EAS Station™ is emergency-alert broadcast software. A vulnerability here can
affect whether real warnings reach people, so please report security issues
responsibly rather than filing a public issue.

## Reporting a Vulnerability

Use GitHub's [private vulnerability reporting](https://github.com/KR8MER/eas-station/security/advisories/new)
for this repository (Security tab → "Report a vulnerability"). This opens a
private advisory visible only to the maintainer and you, so the issue isn't
public before a fix ships.

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce, or a proof of concept if you have one
- The affected version (`VERSION` file contents, or the release tag)
- Any suggested mitigation, if you have one

You should get an initial response within a few days. Please don't publicly
disclose the issue until a fix has been released.

## Supported Versions

This project releases frequently (see
[CHANGELOG.md](../docs/reference/CHANGELOG.md)) and does not maintain long-term
support branches. Only the latest release is supported — please upgrade
before reporting an issue if you're running an older version, and confirm
the issue still reproduces.

## Scope

This is self-hosted software installed on hardware the operator controls
(typically a Raspberry Pi). Most of its attack surface is local: physical
access, the local network, and the admin web UI. Reports involving any of
the following are especially welcome:

- Authentication/authorization bypass in the web UI or API
- Injection vulnerabilities (SQL, command, template, log)
- Anything that lets an unauthenticated caller trigger a broadcast, alter
  alert content, or disable alerting
- Secrets handling (`.env`, `SECRET_KEY`, stored credentials)

Dependency vulnerabilities are largely handled by Dependabot security
updates, already enabled on this repo — you're still welcome to report one
directly if it's exploitable in how this project actually uses the
dependency.
