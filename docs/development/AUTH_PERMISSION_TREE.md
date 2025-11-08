# Authentication & RBAC Function Tree

This reference lists every Flask route that enforces authentication or role-based permissions. It is organised by module so developers can quickly identify where RBAC rules apply and which default roles (Admin / Operator / Viewer) satisfy each requirement.

## Legend
- **Login required** – endpoint checks for an authenticated `g.current_user`. All standard roles qualify once signed in.
- **Permission required** – endpoint uses `@require_permission(...)`. Default role coverage is derived from `DEFAULT_ROLE_PERMISSIONS`.
- **First-user bypass** – endpoint allows unauthenticated access only while creating the very first admin account.

---

## 1. Login-gated Routes (any authenticated role)

### `webapp/eas/workflow.py`
- `/eas/` → `workflow_home` — Login required via `_auth_redirect()`.【F:webapp/eas/workflow.py†L47-L77】
- `/eas/manual/generate` (POST) → `manual_eas_generate` — Login required (JSON 401 if unauthenticated).【F:webapp/eas/workflow.py†L102-L135】
- `/eas/manual/events` (GET) → `manual_eas_events` — Login required for listing manual activations.【F:webapp/eas/workflow.py†L520-L567】
- `/eas/manual/events/<id>/print` → `manual_eas_print` — Login required before rendering print view.【F:webapp/eas/workflow.py†L594-L640】
- `/eas/manual/events/<id>/export` → `manual_eas_export` — Login required; unauthenticated requests receive 401.【F:webapp/eas/workflow.py†L649-L692】
- `/eas/manual/events/<id>` (DELETE) → `manual_eas_delete` — Login required before deleting records.【F:webapp/eas/workflow.py†L674-L707】
- `/eas/manual/events/purge` (POST) → `manual_eas_purge` — Login required for bulk purge actions.【F:webapp/eas/workflow.py†L708-L756】

### `webapp/eas/messages.py`
- `/eas/messages/purge` (POST) → `purge_eas_messages` — Login required for message purges.【F:webapp/eas/messages.py†L50-L110】

### `webapp/admin/audio.py`
- `/admin/eas_messages/purge` (POST) → `admin_purge_eas_messages` — Login required to bulk-delete generated audio.【F:webapp/admin/audio.py†L538-L618】
- `/admin/eas/manual_generate` (POST) → `admin_manual_eas_generate` — Login required (first-user bypass allowed).【F:webapp/admin/audio.py†L621-L706】
- `/admin/eas/manual_events` (GET) → `admin_manual_eas_events` — Login required to list manual events (first-user bypass).【F:webapp/admin/audio.py†L992-L1038】
- `/admin/eas/manual_events/<id>/print` → `manual_eas_print` — Redirects unauthenticated users to login.【F:webapp/admin/audio.py†L1105-L1150】
- `/admin/eas/manual_events/<id>/export` → `manual_eas_export` — Returns HTTP 401 when unauthenticated.【F:webapp/admin/audio.py†L1154-L1189】

### `webapp/admin/dashboard.py`
- `/admin/users` (POST) → `admin_users` — Login required to create users (first-user bypass).【F:webapp/admin/dashboard.py†L164-L218】

### `webapp/routes_setup.py`
- `/setup` (GET/POST) → `setup_wizard` — Redirects unauthenticated users to login once setup mode is disabled.【F:webapp/routes_setup.py†L45-L96】
- `/setup/generate-secret` (POST) → `setup_generate_secret` — Returns 401 when setup mode is off and user is not logged in.【F:webapp/routes_setup.py†L213-L233】
- `/setup/view-env` (GET) → `setup_view_env` — Requires login outside setup mode.【F:webapp/routes_setup.py†L261-L309】
- `/setup/download-env` (GET) → `setup_download_env` — Requires login outside setup mode.【F:webapp/routes_setup.py†L312-L338】
- `/setup/upload-env` (POST) → `setup_upload_env` — Requires login outside setup mode.【F:webapp/routes_setup.py†L339-L386】
- `/setup/lookup-county-fips` (POST) → `setup_lookup_county_fips` — Requires login outside setup mode.【F:webapp/routes_setup.py†L387-L446】
- `/setup/derive-zone-codes` (POST) → `setup_derive_zone_codes` — Requires login outside setup mode.【F:webapp/routes_setup.py†L447-L502】

### `webapp/routes_security.py`
- `/security/settings` (GET) → `security_settings` — Redirects to `/login` when unauthenticated.【F:webapp/routes_security.py†L505-L520】

---

## 2. Permission-gated Routes

Default role coverage per permission (from `DEFAULT_ROLE_PERMISSIONS`):

| Permission | Roles with access |
|------------|------------------|
| `system.view_config` | Admin, Operator, Viewer |
| `system.configure` | Admin |
| `system.manage_users` | Admin |
| `system.view_users` | Admin, Operator, Viewer |
| `logs.view` | Admin, Operator, Viewer |
| `logs.export` | Admin, Operator, Viewer |
| `alerts.export` | Admin, Operator, Viewer |
| `analytics_manage` | _None by default (must be assigned manually)_ |

### `webapp/admin/environment.py`
- `/api/environment/categories` (GET) → `get_environment_categories` — `system.view_config`.
- `/api/environment/variables` (GET) → `get_environment_variables` — `system.view_config`.
- `/api/environment/variables` (PUT) → `update_environment_variables` — `system.configure` (Admin only).
- `/api/environment/validate` (GET) → `validate_environment` — `system.view_config`.
- `/settings/environment` (GET) → `environment_settings` — `system.view_config` (reveals whether the current user also has `system.configure`).
- `/admin/environment/download-env` (GET) → `admin_download_env` — `system.view_config`.
- `/api/environment/generate-secret` (POST) → `generate_secret_key_api` — `system.configure`.
【F:webapp/admin/environment.py†L780-L1059】

### `webapp/routes_security.py`
- `/security/roles` (GET) → `list_roles` — `system.view_users`.
- `/security/roles/<id>` (GET) → `get_role` — `system.view_users`.
- `/security/roles` (POST) → `create_role` — `system.manage_users`.
- `/security/roles/<id>` (PUT) → `update_role` — `system.manage_users`.
- `/security/permissions` (GET) → `list_permissions` — `system.view_users`.
- `/security/users/<user_id>/role` (PUT) → `assign_user_role` — `system.manage_users`.
- `/security/audit-logs` (GET) → `list_audit_logs` — `logs.view`.
- `/security/audit-logs/export` (GET) → `export_audit_logs` — `logs.export`.
- `/security/init-roles` (POST) → `init_default_roles` — `system.manage_users`.
【F:webapp/routes_security.py†L208-L474】

### `webapp/routes_analytics.py`
- `/api/analytics/metrics/aggregate` (POST) → `aggregate_metrics` — `analytics_manage` (assign to roles as needed).
- `/api/analytics/trends/analyze` (POST) → `analyze_trends` — `analytics_manage`.
- `/api/analytics/anomalies/detect` (POST) → `anomaly_detector` (logged under `anomalies` endpoint) — `analytics_manage`.
- `/api/analytics/anomalies/<id>/acknowledge` (POST) → `acknowledge_anomaly` — `analytics_manage`.
- `/api/analytics/anomalies/<id>/resolve` (POST) → `resolve_anomaly` — `analytics_manage`.
- `/api/analytics/anomalies/<id>/false-positive` (POST) → `mark_anomaly_false_positive` — `analytics_manage`.
【F:webapp/routes_analytics.py†L118-L424】

### `webapp/routes_security.py` (Exports & Tools)
- `/security/permissions/check` (POST) → `check_permission` — used by UI to probe permission state; no decorator so it mirrors current session privileges.【F:webapp/routes_security.py†L484-L504】

---

## 3. Navigation Visibility Alignment

The main navigation template now mirrors these RBAC rules by hiding dropdowns or menu items unless the current session holds the required permission. For example, the “System” menu only appears when `system.view_config`, `gpio.view`, `logs.view`, or `alerts.export` is granted, and the “Admin” menu becomes visible only when at least one admin/security permission is available.【F:templates/components/navbar.html†L1-L344】

---

Keep this document current whenever authentication rules change so UI, backend, and documentation remain in sync.
