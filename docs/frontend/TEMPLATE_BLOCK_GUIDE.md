# Preventing Template Block Mismatches

## The Problem

Template block mismatches occur when a child template uses a block name (e.g., `{% block extra_js %}`) that isn't defined in the parent template (`base.html`). When this happens:

- **JavaScript and CSS fail to load silently** - No errors appear in the console
- **Features stop working** - Buttons don't respond, forms don't submit
- **Debugging is difficult** - The code looks correct but doesn't execute

This was the root cause of GPIO save/activation failures in PR #689.

## Prevention Strategies

### 1. Automated Testing ✅

We've implemented automated tests that run on every template change:

**Test File:** `tests/test_template_blocks.py`
**GitHub Action:** `.github/workflows/template-consistency.yml`

The test automatically:
- Verifies all child template blocks are defined in `base.html`
- Checks for critical blocks (title, content, extra_css, extra_js, scripts)
- Warns about inconsistent JavaScript block usage
- Fails CI builds if mismatches are found

**Run locally:**
```bash
python tests/test_template_blocks.py
```

### 2. Template Block Standards

#### Current Block Names in `base.html`

```jinja2
{% block title %}{% endblock %}        # Page title (<title> tag)
{% block nav_title %}{% endblock %}    # Navigation title (if needed)
{% block extra_css %}{% endblock %}    # Additional CSS files/styles
{% block content %}{% endblock %}      # Main page content
{% block scripts %}{% endblock %}      # Page-specific JavaScript (STANDARD - use this)
```

#### When Adding a New Block

1. **Check if the block exists** in `base.html` first
2. **If adding a new block type**, add it to `base.html` first, then use it in child templates
3. **Run the test** after making changes: `python tests/test_template_blocks.py`

#### JavaScript Block Usage

**✅ STANDARDIZED:** All templates now use `{% block scripts %}` for JavaScript.

- **Use:** `{% block scripts %}` for ALL JavaScript
- **Don't use:** `extra_js` (deprecated and removed)
- **All 18 templates** now consistently use `scripts`

### 3. Code Review Checklist

When reviewing PRs that modify templates:

- [ ] Check that all `{% block ... %}` declarations exist in `base.html`
- [ ] Verify JavaScript blocks use `scripts` (NOT `extra_js` - deprecated)
- [ ] Run `python tests/test_template_blocks.py` locally
- [ ] Test the actual page in a browser (click buttons, submit forms, etc.)
- [ ] Check browser console for JavaScript errors

### 4. Development Best Practices

#### Template Structure
```jinja2
{% extends "base.html" %}

{% block title %}My Page - EAS Station{% endblock %}

{% block extra_css %}
<style>
    /* Page-specific CSS */
</style>
{% endblock %}

{% block content %}
    <!-- Page content here -->
{% endblock %}

{% block scripts %}
<script>
    // Page-specific JavaScript
    console.log('Page loaded');
</script>
{% endblock %}
```

#### Testing Your Template

After creating/modifying a template:

1. **Load the page in a browser**
2. **Open Developer Tools** (F12)
3. **Check the Console tab** for errors
4. **Check the Elements/Inspector tab** - verify your JavaScript block appears in the `<body>`
5. **Test interactive features** - Click buttons, submit forms, etc.

### 5. Error Handling Best Practices

All JavaScript that makes API calls should handle auth errors:

```javascript
try {
    const response = await fetch('/api/endpoint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    
    // Handle authentication errors BEFORE parsing JSON
    if (response.status === 401) {
        alert('🔒 Authentication required. Redirecting to login...');
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
        return;
    }
    
    if (response.status === 403) {
        alert('🚫 Permission denied. Contact your administrator.');
        return;
    }
    
    const data = await response.json();
    
    if (!response.ok) {
        throw new Error(data.error || 'Request failed');
    }
    
    // Success handling
    console.log('Success:', data);
    
} catch (error) {
    console.error('Error:', error);
    alert('❌ ' + error.message);
}
```

### 6. Logging Best Practices

Add comprehensive console logging for debugging:

```javascript
function criticalFunction() {
    console.log('criticalFunction called');
    
    // Log important values
    console.log('Data:', data);
    
    try {
        // Do work
        console.log('Operation successful');
    } catch (error) {
        console.error('Operation failed:', error);
        console.error('Stack trace:', error.stack);
    }
}
```

## What Changed to Fix This Issue

### Files Modified

1. **templates/base.html** - Added `{% block extra_js %}` after `{% block scripts %}`
2. **templates/gpio_pin_map.html** - Enhanced error handling and logging
3. **templates/gpio_control.html** - Enhanced error handling and logging
4. **templates/admin/gpio_statistics.html** - Added navigation links
5. **tests/test_template_blocks.py** - NEW: Automated consistency testing
6. **.github/workflows/template-consistency.yml** - NEW: CI/CD automation

### Root Cause

`base.html` only defined `{% block scripts %}`, but several templates used `{% block extra_js %}`. The template engine silently ignored the undefined block, causing all JavaScript in those templates to be discarded during rendering.

### The Fix

Added `{% block extra_js %}` to `base.html` alongside the existing `{% block scripts %}` to support both naming conventions.

## Future Improvements

## Standardization Complete ✅

**All templates now use `{% block scripts %}`** for JavaScript. The migration included:

1. ✅ Updated 5 templates (gpio_control, gpio_pin_map, led_control, screens, analytics_dashboard)
2. ✅ Removed deprecated `extra_js` block from `base.html`
3. ✅ Updated tests to enforce the standard
4. ✅ All 18 templates now consistent

The test now **fails** if any template uses the deprecated `extra_js` block, preventing future inconsistencies.

### Enhanced Testing

Consider adding:
- Visual regression testing to catch UI issues
- JavaScript execution tests (Selenium/Playwright)
- Template rendering tests in the test suite

## Questions?

If you encounter template issues:
1. Run `python tests/test_template_blocks.py`
2. Check browser console (F12) for errors
3. Verify the block name exists in `base.html`
4. Check if JavaScript is actually rendering in the page source (View → Page Source)
