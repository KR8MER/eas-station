# Bug Report: Environment Settings Not Editable

**Date:** 2025-11-06
**Branch:** `claude/make-env-settings-editable-011CUsHAp1jpYF2sMKkkLDf7`
**Reporter:** User (via Claude)
**Status:** Investigation Required

## Issue Description

Environmental settings page is not showing editable input fields on the front end. User reports they cannot see any inputs or forms to edit environment variables.

## Expected Behavior

Users with `system.configure` permission should see:
- Editable input fields for all environment variables
- Save and Reset buttons at the bottom of each category
- Ability to modify and save environment settings

Users with only `system.view_config` permission should see:
- Read-only (disabled) input fields showing current values
- No Save/Reset buttons
- Warning banner indicating read-only mode

## Actual Behavior

User reports: "Environmental settings aren't editable on the front end"
- Implies inputs may not be visible at all, or are not editable

## Changes Made (Commits: ac03a6a, 9f46f70)

### 1. Added Permission Checking (`app.py`)
```python
# Line 616: Added has_permission to template context
from app_core.auth.roles import has_permission

# Line 641: Made available in templates
'has_permission': has_permission,
```

### 2. Modified Template (`templates/settings/environment.html`)

**Added:**
- Warning banner for read-only users (line 217-222)
- `canEdit` JavaScript variable based on `system.configure` permission (line 271)
- `disabled` attribute on all input fields when user lacks permission (line 469)
- Conditional display of Save/Reset buttons vs read-only message (line 430-448)
- Debug logging to console (lines 248-272)

## Debug Information Added

The following debug logs are now output to browser console:

```javascript
console.log('Environment settings page loading...');
console.log('Current user:', <username>);
console.log('User role:', <role_name>);
console.log('Has configure permission:', <true/false>);
console.log('canEdit =', <true/false>);
```

## Testing Checklist

### Pre-Test Setup
- [ ] User is logged in as administrator
- [ ] Navigate to Environment Settings page: `/settings/environment`
- [ ] Open browser Developer Console (F12)

### What to Check

#### 1. Browser Console Logs
Look for these log messages and record their values:
```
Environment settings page loading...
Current user: [USERNAME]
User role: [ROLE]
Has configure permission: [true/false]
canEdit = [true/false]
Loading environment settings...
Loaded categories: [array of category names]
```

#### 2. Check for JavaScript Errors
- [ ] Are there any red error messages in console?
- [ ] Do any mention "has_permission", "current_user", or "undefined"?

#### 3. Network Tab
Check if API calls succeed:
- [ ] `/api/environment/validate` - Status should be 200
- [ ] `/api/environment/variables` - Status should be 200
- [ ] Record response body if errors occur

#### 4. Page Visual Inspection
- [ ] Is the page header visible? ("Environment Settings")
- [ ] Is the left sidebar with categories visible?
- [ ] Are the category sections rendering?
- [ ] Are input fields visible within each category?
- [ ] Are input fields enabled or disabled?
- [ ] Are Save/Reset buttons visible at bottom of each category?

### Expected Results for Admin User

For a user with **admin** role:
- `Has configure permission: true`
- `canEdit = true`
- All input fields should be **enabled** (not grayed out)
- Save and Reset buttons should be **visible**
- No "read-only mode" warning banner

For a user with **operator** or **viewer** role:
- `Has configure permission: false`
- `canEdit = false`
- All input fields should be **disabled** (grayed out)
- Save and Reset buttons should be **hidden**
- Warning banner should show: "Read-Only Mode: You have view-only access..."

## Possible Root Causes

1. **Permission Check Failing**
   - User's role may not have `system.configure` permission
   - Check database: `SELECT * FROM roles JOIN role_permissions ON roles.id = role_permissions.role_id JOIN permissions ON role_permissions.permission_id = permissions.id WHERE roles.name = 'admin';`

2. **JavaScript Not Loading**
   - `has_permission` function may be returning error in template
   - Jinja template syntax error preventing page render
   - JavaScript execution error preventing `renderVariable()` from running

3. **Template Rendering Error**
   - `current_user` may be None/undefined
   - `has_permission()` call in Jinja may be throwing exception
   - Page may be showing blank or error message

4. **API Endpoint Failure**
   - `/api/environment/variables` may be returning 403 or 500
   - Data not loading, so no inputs are rendered
   - JavaScript failing silently

## Files Modified

- `app.py` (lines 613-642)
- `templates/settings/environment.html` (multiple sections)

## Rollback Instructions

If changes cause issues:

```bash
git checkout main -- app.py templates/settings/environment.html
```

Or revert specific commits:
```bash
git revert 9f46f70  # Revert debug logging commit
git revert ac03a6a  # Revert permission changes commit
```

## Next Steps

1. **Immediate:** Check browser console logs and share output
2. **Database Check:** Verify user has correct role and permissions
3. **API Test:** Test `/api/environment/variables` endpoint directly
4. **Template Test:** Check for Jinja template errors in logs

## Additional Notes

- Original issue unclear if inputs are completely missing or just not editable
- Debug logging added to help diagnose exact failure point
- Permission system appears correctly configured in code
- May need to check if default roles were initialized properly

---

**Related Files:**
- `/home/user/eas-station/app.py`
- `/home/user/eas-station/templates/settings/environment.html`
- `/home/user/eas-station/webapp/admin/environment.py`
- `/home/user/eas-station/app_core/auth/roles.py`
