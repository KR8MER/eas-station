<!-- Copy this content to create a new GitHub issue -->

**Title:** Environment Settings page not showing editable input fields

---

## Description

The Environment Settings page (`/settings/environment`) is not displaying editable input fields on the frontend. Users cannot see or interact with forms to modify environment variables.

## Steps to Reproduce

1. Log in as an administrator
2. Navigate to Settings → Environment Settings (`/settings/environment`)
3. Observe the page content

## Expected Behavior

For users with `system.configure` permission (e.g., admin role):
- ✅ Editable input fields for all environment variables should be visible
- ✅ Save and Reset buttons should appear at the bottom of each category section
- ✅ Users should be able to modify values and save changes

For users with only `system.view_config` permission (e.g., operator/viewer roles):
- ✅ Read-only (disabled) input fields showing current values
- ✅ Warning banner indicating "Read-Only Mode"
- ✅ No Save/Reset buttons

## Actual Behavior

Input fields are not visible or not rendering on the page.

## Environment

- **Branch:** `claude/make-env-settings-editable-011CUsHAp1jpYF2sMKkkLDf7`
- **Affected Page:** `/settings/environment`
- **User Role:** Admin (expected to have full edit access)

## Debug Information Added

Debug logging has been added to help diagnose the issue. When viewing the page, check the browser console (F12) for:

```javascript
Environment settings page loading...
Current user: [username]
User role: [role name]
Has configure permission: [true/false]
canEdit = [true/false]
Loading environment settings...
```

## Investigation Checklist

When debugging, please check:

### Browser Console
- [ ] Are there any error messages in the console?
- [ ] What are the values logged for user, role, and permissions?
- [ ] Does `canEdit` show as `true` or `false`?

### Network Tab
- [ ] Does `/api/environment/validate` return 200 OK?
- [ ] Does `/api/environment/variables` return 200 OK?
- [ ] What is the response body from these endpoints?

### Visual Inspection
- [ ] Is the page header visible?
- [ ] Is the category navigation sidebar visible?
- [ ] Are category sections rendering?
- [ ] Are input fields present but disabled, or completely missing?

## Possible Root Causes

1. **Permission Check Error** - Template may be failing to check `has_permission('system.configure')`
2. **JavaScript Execution Error** - Input rendering code may not be executing
3. **API Endpoint Failure** - Backend may be returning 403/500 errors
4. **Template Rendering Error** - Jinja template syntax error preventing render

## Related Commits

- `ac03a6a` - Make environment settings respect user permissions
- `9f46f70` - Add debug logging and improve permission checks
- `21c10de` - Add bug report documentation

## Files Modified

- `app.py` - Added `has_permission` to template context
- `templates/settings/environment.html` - Added permission checks and disabled states
- Backend: `webapp/admin/environment.py` (unchanged, for reference)

## Additional Context

The permission system is configured with these roles:
- **admin** - Has `system.configure` permission (should be editable)
- **operator** - Has only `system.view_config` permission (read-only)
- **viewer** - Has only `system.view_config` permission (read-only)

---

**Labels:** bug, needs-investigation, ui
**Assignee:** (assign as needed)
**Priority:** High (blocks environment configuration)
