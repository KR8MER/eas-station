# Template Structure Documentation

This document explains the EAS Station template architecture, where page elements are located, and which files are actively used.

---

## 📁 Directory Structure

```
/templates/                    # All Jinja2 templates (62+ files)
├── base.html                 # ✅ ACTIVE - Main base template
├── base_new.html             # ❌ ORPHANED - Not used anywhere
├── components/               # Reusable components
│   ├── navbar_new.html       # ✅ ACTIVE - Current navbar
│   ├── navbar.html           # ❌ ORPHANED - Has RBAC features but unused
│   ├── confidence_scale.html # ✅ ACTIVE - Macro component
│   └── form-example.html     # ❌ ORPHANED - Example file
├── admin/                    # Admin interface templates
├── audio/                    # Audio management templates
├── docs/                     # Documentation templates
├── eas/                      # EAS broadcast templates
├── errors/                   # Error page templates
├── settings/                 # Settings templates
└── stats/                    # Statistics templates

/components/                   # ⚠️ WRONG LOCATION - Should be in templates/
├── footer.html               # ❌ DELETED - Was orphaned, not included anywhere
├── navbar.html               # ❌ ORPHANED - Duplicate in wrong directory
└── page_header.html          # ⚠️ CHECK - Macro component, wrong location
```

---

## 🎯 Active Base Template

### `base.html` (ACTIVE)
**Location**: `/templates/base.html`
**Lines**: 163
**Status**: ✅ All 62+ page templates extend from this

**Structure Overview**:
```html
<!DOCTYPE html>
<html>
<head>
    <!-- Meta tags, CSS, theme variables -->
</head>
<body>
    <!-- Toast Container (line 66) -->

    <!-- Navbar Component (line 69) -->
    {% include 'components/navbar_new.html' %}

    <!-- System Status Banner (lines 72-81, inline) -->

    <!-- Flash Messages (lines 84-95, inline) -->

    <!-- Main Content Block (lines 98-100) -->
    <main>
        {% block content %}{% endblock %}
    </main>

    <!-- Footer (lines 103-144, inline) -->
    <footer class="footer">
        <!-- Copyright, version, legal links -->
        <!-- Tech stack badges (lines 131-137) -->
        <!-- Disclaimer -->
    </footer>

    <!-- JavaScript includes (lines 146-160) -->
</body>
</html>
```

---

## 📍 Page Element Locations

### Where Everything Is Located

| Element | Location | Type | Details |
|---------|----------|------|---------|
| **Navbar** | `templates/components/navbar_new.html` | Component (included) | 404 lines, Bootstrap 5 navbar with dropdowns, health indicator, theme toggle |
| **Footer** | `templates/base.html` lines 103-144 | Inline in base | Copyright, version, tech badges, legal links, disclaimer |
| **System Status Banner** | `templates/base.html` lines 72-81 | Inline in base | Conditional alert banner |
| **Flash Messages** | `templates/base.html` lines 84-95 | Inline in base | Bootstrap alerts for user feedback |
| **Toast Container** | `templates/base.html` line 66 | Inline in base | Toast notifications container |
| **Page Header** | `components/page_header.html` | Macro component | ⚠️ Wrong location, should be in templates/components/ |

---

## 🔧 How Templates Are Used

### Template Inheritance

**All pages extend `base.html`:**
```jinja2
{% extends "base.html" %}

{% block title %}My Page Title{% endblock %}

{% block content %}
    <!-- Your page content here -->
{% endblock %}
```

**Example templates that extend base.html:**
- `index.html` - Dashboard
- `alerts.html` - Alert list
- `admin.html` - Admin panel
- `login.html` - Login page
- All 62+ other page templates

**No templates extend `base_new.html`** - it's orphaned.

---

## 🧩 Component Patterns

### 1. Include Components
Used for navbar that's the same across all pages:

```jinja2
<!-- In base.html -->
{% include 'components/navbar_new.html' %}
```

### 2. Macro Components
Used for reusable UI elements with parameters:

```jinja2
<!-- Import the macro -->
{% from 'components/confidence_scale.html' import confidence_scale %}

<!-- Use the macro -->
{{ confidence_scale(value=85, label="Confidence Score") }}
```

**Active Macro Components:**
- `confidence_scale.html` - Displays confidence/quality scores
- `page_header.html` - Page headers with breadcrumbs (⚠️ wrong location)

### 3. Inline Components
Used for elements that need to be in every page:

```jinja2
<!-- In base.html -->
<footer class="footer">
    <!-- Footer content inline -->
</footer>
```

---

## 🚨 When Making Changes

### Changing the Navbar

**✅ EDIT THIS FILE:**
```
/templates/components/navbar_new.html
```

**❌ DO NOT EDIT:**
- `/templates/components/navbar.html` (orphaned)
- `/components/navbar.html` (wrong location, orphaned)

### Changing the Footer

**✅ EDIT THIS FILE:**
```
/templates/base.html (lines 103-144)
```

**❌ DO NOT EDIT:**
- `/components/footer.html` (deleted - was orphaned)

### Changing System Status Banner

**✅ EDIT THIS FILE:**
```
/templates/base.html (lines 72-81)
```

### Changing Flash Messages

**✅ EDIT THIS FILE:**
```
/templates/base.html (lines 84-95)
```

### Creating New Pages

**✅ CORRECT PATTERN:**
```html
{% extends "base.html" %}

{% block title %}My New Feature{% endblock %}

{% block extra_css %}
<style>
    /* Page-specific styles using CSS variables */
    .my-element {
        background-color: var(--bg-color);
        color: var(--text-color);
    }
</style>
{% endblock %}

{% block content %}
<div class="container-fluid mt-4">
    <h1>My New Feature</h1>
    <!-- Your content -->
</div>
{% endblock %}

{% block extra_js %}
<script>
    // Page-specific JavaScript
</script>
{% endblock %}
```

**❌ WRONG PATTERNS:**
- Extending `base_new.html` (doesn't exist in practice)
- Not extending any base template (missing navbar, footer, theme support)
- Creating duplicate navbar/footer in your template

---

## 🗑️ Orphaned Files (To Be Cleaned Up)

### High Priority - Should Delete

1. **`templates/base_new.html`** (505 lines)
   - Not used anywhere
   - Only mentioned in archived docs
   - **Action**: DELETE

2. **`templates/admin.html.backup`** (266KB)
   - Backup file shouldn't be in templates/
   - **Action**: MOVE to backups/ or DELETE

3. **`templates/components/form-example.html`** (262 lines)
   - Example file, not production code
   - **Action**: MOVE to docs/examples/ or DELETE

### Medium Priority - Wrong Location

4. **`components/navbar.html`** (345 lines)
   - In wrong directory (should be templates/components/)
   - Duplicate functionality
   - **Action**: DELETE

5. **`components/page_header.html`** (432 lines)
   - In wrong directory (should be templates/components/)
   - **Action**: MOVE to `templates/components/` IF actively used

### Medium Priority - Evaluate Features

6. **`templates/components/navbar.html`** (517 lines)
   - Has advanced RBAC permission checks
   - Not currently used
   - **Action**: EVALUATE if RBAC features needed, then DELETE or MERGE

### Low Priority - Evaluate New Templates

7. **`templates/alerts_new.html`** (401 lines)
   - May be work-in-progress
   - **Action**: EVALUATE usage or DELETE

8. **`templates/system_health_new.html`** (373 lines)
   - May be work-in-progress
   - **Action**: EVALUATE usage or DELETE

---

## 📊 Statistics

- **Total Templates**: 62+ HTML files
- **Active Base Template**: 1 (`base.html`)
- **Orphaned Base Templates**: 1 (`base_new.html`)
- **Active Navbar**: 1 (`templates/components/navbar_new.html`)
- **Orphaned Navbars**: 2
- **Macro Components**: 2
- **Files in Wrong Location**: 2
- **Backup Files**: 1
- **Example Files**: 1

---

## 🎓 Best Practices

### 1. Always Extend base.html
```jinja2
{% extends "base.html" %}
```

### 2. Use Theme Variables
```css
.my-element {
    background-color: var(--bg-color);
    color: var(--text-color);
    border: 1px solid var(--border-color);
}
```

### 3. Support Dark Mode
```css
/* Light mode automatically handled by CSS variables */

/* Optional dark mode overrides */
[data-theme="dark"] .my-element {
    /* Specific dark mode tweaks if needed */
}
```

### 4. Use Bootstrap 5 Classes
```html
<div class="container-fluid mt-4">
    <div class="row">
        <div class="col-md-6">
            <!-- Responsive layout -->
        </div>
    </div>
</div>
```

### 5. Add Navigation Links
When creating a new page, add it to the navbar in `templates/components/navbar_new.html`:

```html
<li class="nav-item">
    <a class="nav-link" href="{{ url_for('my_new_page') }}">
        <i class="fas fa-icon"></i> My Feature
    </a>
</li>
```

### 6. Block Structure
Use these blocks in your templates:

- `{% block title %}` - Page title for `<title>` tag
- `{% block extra_css %}` - Page-specific CSS
- `{% block content %}` - Main page content (required)
- `{% block extra_js %}` - Page-specific JavaScript

---

## 🔍 Finding Template Usage

### Search for Template Usage
```bash
# Find which templates extend base.html
grep -r "extends.*base.html" templates/

# Find which pages include a component
grep -r "include.*navbar" templates/

# Find which pages import a macro
grep -r "from.*import" templates/
```

### Verify Template is Used
```bash
# Search Python code for template references
grep -r "render_template.*mytemplate" .

# Check if template is in a route
grep -r "@app.route" webapp/ | grep -A 5 "mytemplate"
```

---

## 📝 Checklist for Template Changes

### Before Modifying Templates

- [ ] Verify which file is actually being used (check imports/includes)
- [ ] Check if it's the active base template (`base.html`) or orphaned (`base_new.html`)
- [ ] Look for duplicate files in wrong locations
- [ ] Search for all references to the template in Python code

### After Modifying Templates

- [ ] Test in browser (light mode)
- [ ] Test in browser (dark mode)
- [ ] Test on mobile/tablet viewport
- [ ] Verify navbar still works
- [ ] Verify footer still displays
- [ ] Check browser console for errors
- [ ] Clear browser cache and retest

### When Adding New Components

- [ ] Place in correct directory (`templates/components/`)
- [ ] Use include or macro pattern appropriately
- [ ] Document in this file
- [ ] Update AGENTS.md with any new patterns
- [ ] Add to navigation if it's a page

---

## 🆘 Troubleshooting

### "My template changes aren't showing"

1. **Check if you edited the right file**
   - Is it the active file or an orphaned copy?
   - Use `grep -r` to find which file is actually included

2. **Clear template cache**
   ```bash
   sudo docker compose restart app
   ```

3. **Clear browser cache**
   - Hard refresh: Ctrl+F5 (Windows/Linux) or Cmd+Shift+R (Mac)

4. **Check for template errors**
   ```bash
   sudo docker compose logs app | grep -i error
   ```

### "Component isn't showing up"

1. **Verify the include path**
   ```jinja2
   {% include 'components/navbar_new.html' %}  # ✅ Correct
   {% include 'navbar_new.html' %}             # ❌ Wrong
   ```

2. **Check file location**
   - Components should be in `/templates/components/`
   - Not in `/components/` (wrong directory)

3. **Verify Flask can find it**
   ```python
   # In Flask, templates are relative to /templates/
   render_template('components/navbar_new.html')
   ```

---

## 📚 Related Documentation

- [AGENTS.md](../development/AGENTS.md) - Development guidelines
- [FUNCTION_TREE.md](../reference/FUNCTION_TREE.md) - Code structure reference
- [Frontend UI Standards](../development/AGENTS.md#-frontend-guidelines) - UI/UX guidelines

---

**Last Updated**: 2025-11-12
**Maintainer**: Development Team
