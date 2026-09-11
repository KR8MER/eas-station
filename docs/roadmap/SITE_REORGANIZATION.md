# Site Reorganization (v3.0.0+)

## Why, and how this relates to the Large File Refactor Plan

`docs/development/LARGE_FILE_REFACTOR_PLAN.md` already tracks this repository's oversized
files — Phase 3 splits monolithic Flask modules into topic packages (same routes, same
templates), Phase 5 extracts giant inline `<script>` blocks out of otherwise-cohesive templates
into `static/js/` (same page, same route, same nav entry). **This document does not duplicate
that work.** It covers a different, narrower problem that plain line-count doesn't capture:
pages where **several genuinely unrelated features share one route and one nav entry**, and the
fix is a real information-architecture change — a new page, a new route, a new `NavItem` —
not a code-organization refactor. Judge every candidate against this test before adding it
here: if splitting the file wouldn't also split the *feature* as the user experiences it, it
belongs in the Large File Refactor Plan instead, not here.

This came up because `templates/admin/notifications.html` (email + SMS + SNMP + Postfix status,
plus SMS's own consent-records and message-log audit trails) grew to 1,029 lines through
feature accretion, and an operator asked for the whole site to be reorganized, not just that one
page.

## Rules every phase follows

- **Never rename an existing URL.** No redirect/deprecated-route convention exists in this
  codebase beyond a small hand-written dict in `webapp/documentation.py`. Sidestep the problem:
  add new routes, keep old ones working.
- **Reuse one of the two patterns already proven in this codebase:**
  - *New page* (precedent: Database Browser / pgweb, PR #2608, and Phase 0 below): new blueprint
    module or new routes on an existing blueprint, one new template extending `base.html`, one
    new `NavItem`, a docs page if the feature needs operator explanation, a dedicated test file.
  - *Grow a section on an existing page* (precedent: Consent Records / SMS Message Log on
    `notifications.html`, before Phase 0 split them out again into their own page once SMS
    outgrew "a section"): no new route/blueprint/nav entry, just another card in the existing
    template. Use this when content genuinely belongs with the parent feature — most content
    should default here; only promote something to its own page when it's truly independent.
- **Every phase keeps `tests/test_navigation_registry.py` and `tests/test_rbac_route_coverage.py`
  green** — both are generic and pass automatically against a well-formed new `NavItem` and a
  properly-decorated new route.
- **Every phase follows the normal `CLAUDE.md` pre-commit checklist**: VERSION bump, CHANGELOG
  entry, template Jinja balance/block-name check.
- **Versioning**: the phase that starts this initiative (Phase 0) is `3.0.0`. Each later phase
  is its own PR that adds a new page/route/nav entry, bumping minor (`3.x.0`).

## Phases

| # | Page | Why it qualifies (not just "it's long") | Target shape | Status |
|---|---|---|---|---|
| 0 | `templates/admin/notifications.html` | SMS config, its own opt-in QR/link callout, Consent Records, and the SMS Message Log are a fully separate feature (own model, own routes, own compliance audience) from Email/SNMP/Postfix — they only shared a page because "notifications" was the closest existing bucket. | New page `Settings → SMS Notifications` (`/admin/notifications/sms`); `/admin/notifications/` keeps Email + SNMP + Postfix only. | **Done, this PR.** |
| 1 | `templates/admin/application_settings.html` | Bad Actor Blocklist is already its own backend module (`webapp/admin/bad_actors.py`) with its own AJAX endpoints (`/status`, `/toggle`, `/update`, `/allowlist`) and none of its inputs are part of the settings `<form>` — an independent abuse-defense subsystem that only visually lived on the same page as logging/storage/branding/password-policy config. (Project Honeypot stays put: unlike Bad Actor Blocklist it's just two fields — `httpbl_enabled`/`httpbl_api_key` — saved through the same `update_application_settings()` form as everything else, not an independent subsystem with its own API.) | New page `Settings → Bad Actor Blocklist` (`/admin/security/bad-actors/`, already-existing blueprint gets a page route); `application_settings.html` keeps core settings + Honeypot + Data Retention, with a link out. | **Done.** |
| 2 | `templates/admin/operations.html` | Turned out to be two different problems, not one split: (a) its "Alert Boundary Coverage" card was a pure duplicate of functionality already on the existing, already-linked `/admin/intersections` page (same two endpoints, `/admin/fix_county_intersections` and `/admin/recalculate_intersections` — that page has more besides); (b) System Upgrade — same `maintenance_bp` blueprint as DB Health/Backup, but a much bigger, riskier operation with its own live progress/log-streaming UI, confusing enough to deserve full-page attention rather than one card among four. | Boundary Coverage card removed entirely (linked out to the pre-existing `/admin/intersections` instead — no new page needed); System Upgrade got a genuine new page (`/admin/system-upgrade`). `operations.html` keeps DB Health + the quick Backup trigger, each linking to `/admin/intersections` / `/admin/system-upgrade` respectively where relevant. (The Backup trigger card is itself a near-duplicate of `/admin/backups`' own "Create New Backup" section, using a different API — flagged here as a possible future consolidation, not fixed in this phase.) | **Done.** |
| 3 | `templates/screens.html` | The embedded "Documentation" tab (template variables, data sources, LED/VFD examples) is reference material for a different audience than the operational screen-management UI it's bolted to -- and it linked to `/static/docs/guides/CUSTOM_DISPLAY_SCREENS.md`, a file that doesn't exist anywhere in the repo. | Content merged into help.html's existing "Custom Display Screens" accordion section (which already covered the feature at a higher level and had the *same* dead link); `screens.html` keeps only the management UI (Screens/Rotations tabs) with a "Documentation" button linking to `/help`. No new page/route -- a content move plus a dead-link fix, not an IA change. (Screens.html's own JS-extraction is still Large File Refactor Plan territory, untouched here.) | **Done.** |

## Explicitly not in scope here

Everything else flagged as oversized during this initiative's research — `gps_dashboard.html`,
`system_health.html`, `led_control.html`, `templates/admin/radio.html`,
`templates/admin/radio_diagnostics.html`, `templates/admin/network.html`,
`templates/admin/certbot.html`, `templates/admin/hardware_settings.html`,
`templates/admin/environment.html`, `templates/audio_monitoring.html`, `templates/index.html`,
`alert_detail.html`, `templates/admin/rbac_management.html`, `webapp/routes_security.py`,
`webapp/routes_led.py`, `webapp/admin/hardware.py`, `webapp/admin/dashboard.py`,
`webapp/routes_backups.py` — is either already tracked in
`docs/development/LARGE_FILE_REFACTOR_PLAN.md` (Phase 3 for backend module splits, Phase 5 for
frontend JS-extraction) or, on inspection, is one cohesive feature that's simply detailed
(`templates/admin/tailscale.html`, `templates/admin/icecast.html`,
`templates/admin/county_boundaries.html`, `templates/admin/backups.html`, `help.html`,
`logs.html`) and not a candidate for either plan.

## Progress

- **Phase 0** — done (`v3.0.0`).
- **Phase 1** — done.
- **Phase 2** — done.
- **Phase 3** — done. All phases in this document's original scope are complete; new candidates would need their own phase entries.
