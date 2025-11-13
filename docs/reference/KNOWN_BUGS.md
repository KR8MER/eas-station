# Known Bugs Report

Generated: 2025-11-06
Last Updated: 2025-11-06

**✅ MAJOR UPDATE - Most Critical Bugs Fixed!**

All critical and high-priority bugs have been fixed in commit `[pending]`. See [Fixed Bugs](#fixed-bugs) section below for details.

## Table of Contents
0. [Fixed Bugs](#fixed-bugs)
1. [RBAC (Role-Based Access Control) Issues](#rbac-role-based-access-control-issues)
2. [Text-to-Speech (TTS) Issues](#text-to-speech-tts-issues)
3. [Display Screens (/screens) Issues](#display-screens-screens-issues)
4. [Environment Settings (/settings/environment) Issues](#environment-settings-settingsenvironment-issues)
5. [GPIO Configuration Issues](#gpio-configuration-issues)
6. [Docker/Portainer Deployment Issues](#dockerportainer-deployment-issues)
7. [Priority Recommendations](#priority-recommendations)
8. [Testing Checklist](#testing-checklist)

---

## Fixed Bugs

The following bugs have been **FIXED** and are no longer blocking functionality:

### ✅ RBAC Issues (Fixed)
1. **Missing `user_count` field** - ✅ FIXED in `app_core/auth/roles.py:61`
2. **Permissions format mismatch** - ✅ FIXED in `app_core/auth/roles.py:60` (now returns objects)
3. **Generic error messages** - ✅ FIXED in `templates/admin/rbac_management.html:285-297` (now shows 403 details)

### ✅ Display Screens Issues (Fixed)
1. **Missing editScreen() function** - ✅ FIXED in `templates/screens.html:716-745`
2. **Missing editRotation() function** - ✅ FIXED in `templates/screens.html:840-878`
3. **No response validation** - ✅ FIXED in `templates/screens.html:525-543, 633-651`

### ✅ Environment Settings Issues (Fixed)
1. **No permission checks (SECURITY)** - ✅ FIXED in `webapp/admin/environment.py:674,689,743,800,873`
2. **Missing script checks** - ✅ FIXED in `templates/settings/environment.html:232-239`
3. **No response validation** - ✅ FIXED in `templates/settings/environment.html:254-274`

### ✅ GPIO Configuration Issues (Fixed)
1. **GPIO_PIN_<number> format not supported** - ✅ FIXED in `webapp/routes/system_controls.py:100-144`

### ✅ Docker/Portainer Issues (Fixed)
1. **docker-compose.yml only supports .env** - ✅ FIXED in `docker-compose.yml:12-13,31-32,56-57` (now supports both stack.env and .env)

---

## RBAC (Role-Based Access Control) Issues

### CRITICAL Issues - ✅ ALL FIXED

#### 1. Missing `user_count` field in Role API response - ✅ FIXED
**File:** `app_core/auth/roles.py:54-62`
**Affected Route:** `/security/roles` (GET)
**Impact:** Frontend rendering fails when displaying role cards

**Description:**
The Role model's `to_dict()` method does not include a `user_count` field, but the frontend JavaScript expects this field to display the number of users assigned to each role.

**Frontend Code Expecting Field:**
```javascript
// templates/admin/rbac_management.html:314
<span class="user-count-badge">
    <i class="fas fa-users me-1"></i> ${role.user_count || 0}
</span>
```

**Current API Response:**
```python
# app_core/auth/roles.py:54-62
def to_dict(self):
    return {
        'id': self.id,
        'name': self.name,
        'description': self.description,
        'permissions': [p.name for p in self.permissions],  # ALSO A BUG - see below
        'created_at': self.created_at.isoformat() if self.created_at else None,
        # MISSING: 'user_count': len(self.users)
    }
```

**Fix Required:**
Add `'user_count': len(self.users)` to the `to_dict()` method.

---

#### 2. Permissions format mismatch
**File:** `app_core/auth/roles.py:60`
**Affected Route:** `/security/roles` (GET)
**Impact:** Frontend JavaScript errors when trying to render permission badges

**Description:**
The Role API returns permissions as an array of strings, but the frontend JavaScript expects an array of objects with a `.name` property.

**Current API Response:**
```python
# app_core/auth/roles.py:60
'permissions': [p.name for p in self.permissions]
# Returns: ["alerts.view", "alerts.create", ...]
```

**Frontend Code Expecting Objects:**
```javascript
// templates/admin/rbac_management.html:321-322
${(role.permissions || []).slice(0, 5).map(p =>
    `<span class="permission-badge">${escapeHtml(p.name)}</span>`
).join('')}
```

**Current Behavior:**
- JavaScript tries to access `p.name` on strings
- `"alerts.view".name` returns `undefined`
- Permission badges appear empty or cause rendering errors

**Fix Required:**
Change line 60 to: `'permissions': [p.to_dict() for p in self.permissions]`
OR keep as strings and update frontend to: `${escapeHtml(p)}`

---

#### 3. 403 Forbidden - Primary cause of "Failed to load roles" error
**File:** `webapp/routes_security.py:211-218`
**Affected Route:** `/security/roles` (GET)
**Impact:** Users without proper permissions cannot access RBAC management page

**Description:**
The `/security/roles` endpoint is protected by `@require_permission('system.view_users')` decorator. If a user:
1. Has no role assigned (`user.role` is `None`)
2. Lacks the `system.view_users` permission
3. Is not active (`user.is_active` is `False`)

Then the request returns 403 Forbidden, and the frontend displays "Failed to load roles" in all tabs.

**Affected Code:**
```python
# webapp/routes_security.py:211-218
@security_bp.route('/roles', methods=['GET'])
@require_permission('system.view_users')
def list_roles():
    """List all roles with their permissions."""
    roles = Role.query.all()
    return jsonify({
        'roles': [role.to_dict() for role in roles]
    })
```

**Root Cause Check:**
```python
# app_core/auth/roles.py:210-233
def has_permission(permission_name: str, user=None) -> bool:
    if user is None:
        user = get_current_user()

    if not user or not user.is_active:
        return False

    # If user has no role, deny access
    if not user.role:
        return False

    # Check if role has the permission
    return user.role.has_permission(permission_name)
```

**Common Scenarios:**
1. **New user without role assigned** - Most likely cause
2. **User with "viewer" role** - May lack `system.view_users` permission depending on configuration
3. **Database not initialized** - Roles/permissions tables are empty

**Fix Required:**
1. Ensure all users have roles assigned (check with migration or admin tool)
2. Run `/security/init-roles` endpoint to initialize default roles
3. Add better error handling in frontend to show permission denied message instead of generic "Failed to load roles"

---

### MAJOR Issues

#### 4. No user-friendly error message for permission denials
**File:** `templates/admin/rbac_management.html:282-292`
**Impact:** Users see generic "Failed to load roles" instead of specific permission error

**Description:**
When a 403 Forbidden response is returned (due to missing permissions), the frontend catch block displays a generic error message.

**Current Code:**
```javascript
// templates/admin/rbac_management.html:282-292
async function loadRoles() {
    try {
        const response = await fetch('/security/roles');
        const data = await response.json();
        rolesData = data.roles;
        renderRoles();
    } catch (error) {
        console.error('Failed to load roles:', error);
        document.getElementById('roles-container').innerHTML =
            '<div class="col-12"><div class="alert alert-danger">Failed to load roles</div></div>';
    }
}
```

**Better Approach:**
```javascript
async function loadRoles() {
    try {
        const response = await fetch('/security/roles');
        if (!response.ok) {
            if (response.status === 403) {
                throw new Error('You do not have permission to view roles. Contact your administrator to grant you the "system.view_users" permission.');
            }
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        rolesData = data.roles;
        renderRoles();
    } catch (error) {
        console.error('Failed to load roles:', error);
        document.getElementById('roles-container').innerHTML =
            `<div class="col-12"><div class="alert alert-danger">${error.message}</div></div>`;
    }
}
```

---

### MINOR Issues

#### 5. Potential lazy loading issue with user.role relationship
**File:** `app_core/models.py:164`
**Impact:** May cause N+1 query issues or relationship loading problems

**Description:**
The AdminUser model uses `lazy='joined'` for the role relationship, which may not work properly with all query patterns.

**Current Code:**
```python
# app_core/models.py:164
role = relationship('Role', foreign_keys=[role_id], lazy='joined', back_populates='users')
```

**Potential Issue:**
When using `.query.get()` to fetch a user, the `lazy='joined'` may not always eagerly load the role, causing the `user.role` to be `None` even when a `role_id` exists.

**Recommendation:**
- Review all user query patterns to ensure role is loaded
- Consider using `joinedload()` explicitly in queries: `AdminUser.query.options(joinedload(AdminUser.role)).get(user_id)`

---

## Text-to-Speech (TTS) Issues

### Summary
Based on comprehensive investigation, the TTS system appears to be functioning correctly. Recent fixes (commits 782e72b, cc59196) resolved critical numpy JSON serialization bugs that were causing 500 errors.

### Configuration Issues (User-facing)

#### 1. TTS Provider Not Configured
**Impact:** Users expect TTS but get warning "No TTS provider configured; supply narration manually."

**Description:**
If environment variable `EAS_TTS_PROVIDER` is not set or is empty, TTS will not be generated for manual EAS broadcasts.

**Required Environment Variables:**

**For Azure Speech:**
```bash
EAS_TTS_PROVIDER=azure
AZURE_SPEECH_KEY=<your-key>
AZURE_SPEECH_REGION=<your-region>
AZURE_SPEECH_VOICE=en-US-AriaNeural  # Optional, default shown
```

**For Azure OpenAI:**
```bash
EAS_TTS_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=<your-endpoint>
AZURE_OPENAI_KEY=<your-key>
AZURE_OPENAI_VOICE=alloy  # Optional, default shown
AZURE_OPENAI_MODEL=tts-1-hd  # Optional, default shown
```

**For pyttsx3 (Local/Offline):**
```bash
EAS_TTS_PROVIDER=pyttsx3
PYTTSX3_VOICE=<voice-id>  # Optional
PYTTSX3_RATE=150  # Optional, words per minute (80-450)
PYTTSX3_VOLUME=1.0  # Optional, 0.0-1.0
```

**Check Configuration:**
View current TTS configuration at `/settings/environment` under "EAS Configuration" section.

---

#### 2. Missing pyttsx3 Dependencies
**Impact:** pyttsx3 provider fails with "synthesis failed" warning

**Description:**
The pyttsx3 TTS provider requires system packages that may not be installed:
- `espeak` or `espeak-ng` (speech synthesis engine)
- `libespeak1` or `libespeak-ng1` (library)
- `ffmpeg` (audio processing)

**Error Indicators:**
- TTS warning: "pyttsx3 is configured but synthesis failed."
- Log shows: "espeak not found" or ImportError

**Fix:**
```bash
# Debian/Ubuntu
apt-get install espeak espeak-ng libespeak-ng1 ffmpeg

# Alpine (Docker)
apk add espeak espeak-ng ffmpeg

# Check Dockerfile - should already include these
```

---

#### 3. Azure Credentials Invalid
**Impact:** Azure providers fail with "synthesis failed" warning

**Description:**
If Azure Speech or Azure OpenAI credentials are invalid, expired, or have incorrect permissions, TTS will fail silently.

**Error Indicators:**
- TTS warning: "Azure Speech is configured but synthesis failed."
- Check application logs for detailed error messages

**Fix:**
1. Verify credentials in Azure portal
2. Ensure Speech resource has correct region
3. Check API key has not expired
4. Verify firewall/network allows connection to Azure endpoints

---

### Recently Fixed Issues (No Action Needed)

#### ✅ Numpy float32 JSON serialization error (Fixed in cc59196)
Audio APIs were returning 500 errors with "Object of type float32 is not JSON serializable". Fixed by adding `_sanitize_float()` helper.

#### ✅ Numpy bool_ JSON serialization error (Fixed in 782e72b)
Audio APIs were returning intermittent 500 errors with "Object of type bool is not JSON serializable". Fixed by adding `_sanitize_bool()` helper.

#### ✅ Missing pydub dependency (Fixed in 0b36a59)
Added `pydub==0.25.1` to requirements.txt for MP3/AAC/OGG stream decoding.

---

## Display Screens (/screens) Issues

### CRITICAL Issues

#### 1. Missing JavaScript functions cause page failure
**File:** `templates/screens.html`
**Affected Route:** `/screens` (GET)
**Impact:** Page shows infinite spinner, Edit buttons don't work

**Description:**
The screens.html template references JavaScript functions that are never defined, causing the page to fail silently or show errors.

**Missing Functions:**
- `editScreen(id)` - Called on line 598 when user clicks Edit button on a screen
- `editRotation(id)` - Called on line 680 when user clicks Edit button on a rotation

**Frontend Code:**
```html
<!-- templates/screens.html:598 -->
<button class="btn btn-sm btn-primary" onclick="editScreen(${screen.id})">
    <i class="fas fa-edit"></i> Edit
</button>

<!-- templates/screens.html:680 -->
<button class="btn btn-sm btn-primary" onclick="editRotation(${rotation.id})">
    <i class="fas fa-edit"></i> Edit
</button>
```

**Impact:**
- Spinner never stops because JS errors prevent page from rendering
- Edit functionality completely broken
- Users cannot modify existing screens or rotations

**Fix Required:**
Add the missing functions to the JavaScript section or implement full edit modal workflow.

---

#### 2. No response validation in fetch calls
**File:** `templates/screens.html:525-541, 631-646`
**Affected Functions:** `loadScreens()`, `loadRotations()`
**Impact:** Silent failures, misleading error messages

**Description:**
The fetch calls don't check `response.ok` before attempting to parse JSON, leading to undefined behavior when APIs return error status codes.

**Current Code (lines 525-541):**
```javascript
async function loadScreens() {
    try {
        const response = await fetch('/api/screens');
        const data = await response.json();  // ❌ Missing response.ok check!
        allScreens = data.screens || [];
        renderScreens();
    } catch (error) {
        console.error('Error loading screens:', error);
        showToast('Error loading screens', 'danger');
    }
}
```

**Problem:**
- If API returns 500, 403, or 404, `response.json()` may fail
- Error message "Error loading screens" doesn't indicate the actual problem
- Server errors are hidden from the user

**Fix Required:**
```javascript
const response = await fetch('/api/screens');
if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
}
const data = await response.json();
```

---

## Environment Settings (/settings/environment) Issues

### CRITICAL Issues

#### 1. Page shows no settings - potential script loading failure
**File:** `templates/settings/environment.html`
**Affected Route:** `/settings/environment` (GET)
**Impact:** Users cannot view or edit environment variables

**Description:**
The environment settings page displays no settings and shows no editable fields. This appears to be caused by JavaScript loading issues or API failures.

**Potential Root Causes:**

**A. Missing Global Utility Functions:**
The template calls `showLoading()`, `hideLoading()`, and `showToast()` without checking if they exist:

```javascript
// templates/settings/environment.html:277-280
async function loadSettings() {
    showLoading();  // May not be defined!
    try {
        const validationResponse = await fetch('/api/environment/validate');
```

These functions are defined in `/static/js/loading-error-utils.js`, but if that script fails to load or loads in the wrong order, all subsequent code fails silently.

**B. API Fetch Failures:**
The page makes three API calls on load:
1. `GET /api/environment/validate` - Validation status
2. `GET /api/environment/variables` - All environment variables
3. `GET /api/environment/categories` - Category structure

If any of these fail, the page may not render properly.

**C. Missing Toast Container:**
The template expects a toast container in the DOM from `base.html:66`, but if it's missing, notifications fail.

**Files Involved:**
- Route: `/home/user/eas-station/webapp/admin/environment.py:867-881`
- Template: `/home/user/eas-station/templates/settings/environment.html`
- Utils: `/home/user/eas-station/static/js/loading-error-utils.js`
- Base: `/home/user/eas-station/templates/base.html`

**Fix Required:**
1. Ensure loading-error-utils.js loads before inline scripts
2. Add checks for function existence before calling
3. Add response validation to all fetch calls
4. Display user-friendly error messages

---

#### 2. No permission checks on environment settings
**File:** `webapp/admin/environment.py:867-881, 672-865`
**Impact:** Unprotected admin functionality

**Description:**
The `/settings/environment` route and all its API endpoints lack `@require_permission()` decorators, even though the RBAC system exists with appropriate permissions (`system.configure`, `system.view_config`).

**Affected Endpoints:**
- `GET /settings/environment` - No auth (line 867)
- `GET /api/environment/categories` - No auth (line 672)
- `GET /api/environment/variables` - No auth (line 686)
- `PUT /api/environment/variables` - No auth (line 739)
- `GET /api/environment/validate` - No auth (line 795)

**Security Risk:**
Any authenticated user can view and modify all environment variables, including sensitive credentials.

**Fix Required:**
Add permission decorators:
```python
@app.route('/settings/environment')
@require_permission('system.view_config')
def environment_settings():
    ...

@app.route('/api/environment/variables', methods=['PUT'])
@require_permission('system.configure')
def update_environment():
    ...
```

---

## GPIO Configuration Issues

### CRITICAL Issues

#### ✅ 1. GPIO page recognizes `GPIO_PIN_<number>` format
**Status:** Fixed via `app_utils/gpio.py` loader and `webapp/routes/system_controls.py`

The GPIO configuration loader now normalizes entries from `EAS_GPIO_PIN`, `GPIO_ADDITIONAL_PINS`,
and `GPIO_PIN_<number>` environment variables, so all supported formats appear in the control panel.
Documentation has been updated to reflect the accepted formats and the persistent environment editor
now exposes these fields directly under **Settings → Environment → GPIO Control**.

---

## Docker/Portainer Deployment Issues

### CRITICAL Issues

#### 1. docker-compose.yml references `.env` instead of `stack.env`
**File:** `docker-compose.yml:11-12`
**Impact:** Portainer deployments fail without prompts

**Description:**
The main docker-compose.yml file uses `env_file: - .env`, but when deploying from Git in Portainer, the environment file is named `stack.env`.

**Current Code (docker-compose.yml:11-12):**
```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SOAPYSDR_DRIVERS: ${SOAPYSDR_DRIVERS:-rtlsdr,airspy}
    image: eas-station:latest
    ports:
      - "5000:5000"
    env_file:
      - .env  # ❌ Should be stack.env for Portainer Git deployments
    environment:
      SDR_ARGS: ${SDR_ARGS:-driver=airspy}
```

**Impact:**
- Portainer Git deployments fail with "env file not found"
- Users see no prompts, just silent failure
- Build process cannot find required environment variables

**Portainer Documentation Says (PORTAINER_DEPLOYMENT.md:324-350):**
> **For Git Repository deployments (recommended):**
> - ✅ Portainer automatically loads `stack.env` from the repository
> - ✅ All default values are already set
> - ✅ You only override critical variables

**Fix Options:**

**Option A (Recommended):** Support both files
```yaml
env_file:
  - stack.env  # For Portainer Git deployments
  - .env       # For local docker-compose up
```

**Option B:** Use only stack.env
```yaml
env_file:
  - stack.env
```
And update documentation to say users should copy `stack.env` to `.env` for local development.

**Option C:** Make env_file optional
Remove `env_file` entirely and rely on environment variables being passed through Portainer's UI or as shell environment.

---

#### 2. docker-compose.embedded-db.yml missing env_file entirely
**File:** `docker-compose.embedded-db.yml`
**Impact:** Embedded database deployments may fail to load configuration

**Description:**
The `docker-compose.embedded-db.yml` file extends the main compose file but doesn't specify any `env_file`. This means it inherits the issue from the main file.

**Fix Required:**
Ensure the embedded database compose file properly loads stack.env.

---

## Priority Recommendations

### Critical Priority (Blocking Functionality)
1. **Fix docker-compose.yml env_file** - Support both `stack.env` and `.env` for Portainer compatibility
2. **Implement missing editScreen/editRotation functions** - /screens page is completely broken
3. **Fix environment settings page** - Users cannot view or edit environment variables
4. **Add GPIO_PIN_<number> format support** - GPIO page shows no pins even when configured

### High Priority (Security & RBAC)
1. **Add permission checks to environment settings** - Currently unprotected, allows any user to view/edit sensitive config
2. **Fix RBAC permissions format mismatch** - Update `Role.to_dict()` to return permission objects instead of strings
3. **Add user_count field to roles** - Frontend expects this field for display
4. **Initialize roles for existing users** - Run migration to ensure all users have roles
5. **Improve RBAC error messages** - Update frontend to show specific permission denial messages

### Medium Priority (User Experience)
1. **Add response validation to all fetch calls** - Screens page, environment page, and others fail silently
2. **Ensure script loading order** - loading-error-utils.js must load before inline scripts
3. **Add TTS configuration check** - Show warning in UI if TTS provider is not configured
4. **Add TTS dependency check** - Validate pyttsx3 dependencies on startup
5. **Add role initialization UI** - Provide admin button to initialize default roles without using API
6. **Document GPIO environment variable formats** - Clarify supported formats in setup guide

### Low Priority (Code Quality)
1. **Review lazy loading strategy** - Ensure role relationships load correctly in all query patterns
2. **Add integration tests** - Test RBAC flows with different permission scenarios
3. **Add TTS provider health checks** - Periodic validation of Azure/pyttsx3 connectivity
4. **Standardize error handling patterns** - Consistent fetch error handling across all pages

---

## Testing Checklist

### RBAC Testing
- [ ] Verify user can access `/admin/rbac` with `system.view_users` permission
- [ ] Verify 403 error shown when user lacks permission
- [ ] Verify roles display with correct user counts
- [ ] Verify permissions display as badges (not empty)
- [ ] Verify all three tabs (Roles, Permissions, User Assignments) load correctly
- [ ] Test role creation with permission assignment
- [ ] Test role editing
- [ ] Test user role assignment

### TTS Testing
- [ ] Verify Azure Speech TTS generates audio correctly
- [ ] Verify Azure OpenAI TTS generates audio correctly
- [ ] Verify pyttsx3 TTS generates audio correctly (if dependencies installed)
- [ ] Verify TTS warning messages display when provider fails
- [ ] Verify TTS warning messages display when provider not configured
- [ ] Verify manual EAS generation with TTS enabled
- [ ] Verify manual EAS generation with TTS disabled
- [ ] Verify TTS audio amplitude matches SAME header amplitude

### Display Screens Testing
- [ ] Verify `/screens` page loads without infinite spinner
- [ ] Verify screens list displays correctly
- [ ] Verify rotations list displays correctly
- [ ] Test creating a new screen
- [ ] Test editing an existing screen (should work, not show error)
- [ ] Test deleting a screen
- [ ] Test creating a new rotation
- [ ] Test editing an existing rotation (should work, not show error)
- [ ] Test deleting a rotation
- [ ] Verify error messages display when API calls fail

### Environment Settings Testing
- [ ] Verify `/settings/environment` page loads
- [ ] Verify all environment categories display in sidebar
- [ ] Verify all environment variables display in forms
- [ ] Verify sensitive values are masked
- [ ] Verify validation status banner displays correctly
- [ ] Test saving changes to environment variables
- [ ] Verify unsaved changes indicator works
- [ ] Verify reset button reverts changes
- [ ] Test with user lacking `system.view_config` permission (should deny access)
- [ ] Test with user lacking `system.configure` permission (should allow view, deny save)

### GPIO Configuration Testing
- [ ] Set `EAS_GPIO_PIN=17` in environment and verify it appears on GPIO page
- [ ] Set `GPIO_ADDITIONAL_PINS="27:Test:HIGH:3:600"` and verify it appears
- [ ] Verify "No GPIO pins configured" message shows when no pins set
- [ ] Test activating a GPIO pin
- [ ] Test deactivating a GPIO pin
- [ ] Test force deactivate (emergency override)
- [ ] Verify activation history displays correctly
- [ ] Verify hold time and watchdog timers work correctly

### Docker/Portainer Deployment Testing
- [ ] Deploy stack from Git using Portainer with `docker-compose.yml`
- [ ] Verify stack.env file is loaded automatically
- [ ] Verify all containers start successfully
- [ ] Test deploying with `docker-compose.embedded-db.yml`
- [ ] Verify environment variable overrides work in Portainer
- [ ] Test "Pull and redeploy" feature in Portainer
- [ ] Verify local `docker-compose up` works with `.env` file
- [ ] Verify all services connect to database correctly

---

## Related Files

### RBAC System
- `app_core/auth/roles.py` - Role and Permission models, decorators
- `app_core/auth/audit.py` - Audit logging for RBAC actions
- `app_core/models.py` - AdminUser model with role relationship
- `webapp/routes_security.py` - RBAC API endpoints
- `templates/admin/rbac_management.html` - RBAC management UI

### TTS System
- `app_utils/eas_tts.py` - TTS engine implementation (3 providers)
- `app_utils/eas.py` - EAS audio generator with TTS integration
- `webapp/admin/audio.py` - Manual EAS generation API
- `app_core/models.py` - EASMessage model with tts_warning field

### Display Screens System
- `webapp/routes_screens.py` - Screens and rotations API endpoints
- `templates/screens.html` - Screens management UI (912 lines)
- `app_core/models.py` - DisplayScreen and ScreenRotation models (lines 922-1030)
- `app_core/migrations/versions/20251106_add_display_screens.py` - Database migration

### Environment Settings System
- `webapp/admin/environment.py` - Environment management routes and APIs (lines 672-881)
- `templates/settings/environment.html` - Environment settings UI (230 lines)
- `static/js/loading-error-utils.js` - Global utility functions
- `templates/base.html` - Base template with toast container

### GPIO System
- `webapp/routes/system_controls.py` - GPIO routes and configuration parsing (lines 42-385)
- `templates/gpio_control.html` - GPIO control panel UI
- `app_utils/gpio.py` - GPIOController and pin management
- `app_core/models.py` - GPIOActivationLog model
- `docs/hardware/gpio.md` - GPIO hardware setup documentation

### Docker/Portainer
- `docker-compose.yml` - Main compose file for stack deployment
- `docker-compose.embedded-db.yml` - Embedded database variant
- `stack.env` - Portainer environment file with defaults (277 lines)
- `.env.example` - Local development environment template
- `docs/guides/PORTAINER_DEPLOYMENT.md` - Complete Portainer guide (1491 lines)

---

## Contact

For questions or to report additional bugs, please:
1. Check application logs in `/logs` directory
2. Review environment configuration at `/settings/environment`
3. Contact system administrator for permission issues
4. File issues in project repository
