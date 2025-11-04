# Phase 4: Tab 2 Migration - Preview Data Extraction

## Overview
Migrating the "Preview Data Extraction" tab to use design system alert components instead of custom alert classes.

## Current State Analysis

### HTML Structure (Lines 513-560)
- **Header**: H4 with icon and description
- **Form**: Preview form with two columns (similar to Tab 1)
  - Left column: Boundary type dropdown + custom type input
  - Right column: File input
- **Button**: Already using `btn btn-info` ✅
- **Results div**: Dynamic content area for preview results

### Current Issues
1. ✅ Button already uses design system class
2. ❌ JavaScript uses `alert-danger-custom` class (8 instances)
3. ❌ JavaScript uses `alert-warning-custom` class
4. ❌ Custom CSS for alert styling with gradients
5. ❌ Preview results use custom `.preview-container` and `.preview-item` classes

### JavaScript Dependencies (Lines 4765-4890)
- `previewExtraction()` function
- Uses `alert-danger-custom` for error messages (2 instances in this function)
- Generates dynamic HTML for preview results
- Uses custom preview styling classes

## Migration Strategy

### Approach: **Replace Custom Alerts with Design System**

Since the button is already correct, focus on:
1. Replace `alert-danger-custom` with `alert alert-danger`
2. Replace `alert-warning-custom` with `alert alert-warning`
3. Update preview result styling to use design system cards
4. Remove custom alert CSS (can be done later)

### Changes Required

1. **JavaScript Alert Classes** (8 instances total)
   - Line 4885: `alert-danger-custom` → `alert alert-danger`
   - Line 4888: `alert-danger-custom` → `alert alert-danger`
   - Line 4954: `alert-danger-custom` → `alert alert-danger`
   - Line 4996: `alert-danger-custom` → `alert alert-danger`
   - Line 4368: `alert-danger-custom` → `alert alert-danger`
   - Line 1439: `alert-danger-custom` → `alert alert-danger`
   - Line 3477: Update showStatus mapping

2. **Preview Results Styling** (Optional Enhancement)
   - Wrap preview results in design system card
   - Use proper typography classes
   - Add proper spacing utilities

## Implementation Plan

### Step 1: Replace Alert Classes in JavaScript
```javascript
// Before
resultsDiv.innerHTML = `<div class="alert alert-danger-custom">❌ ${result.error}</div>`;

// After
resultsDiv.innerHTML = `<div class="alert alert-danger" role="alert">❌ ${result.error}</div>`;
```

### Step 2: Update showStatus Function Mapping
```javascript
// Before (line 3477)
danger: 'alert-danger-custom',

// After
danger: 'alert-danger',
```

### Step 3: Enhance Preview Results (Optional)
```javascript
// Wrap preview results in card
let html = `
    <div class="card">
        <div class="card-header">
            <h5 class="mb-0">📋 Preview Results</h5>
        </div>
        <div class="card-body">
            <p><strong>Total Features:</strong> ${result.total_features}</p>
            ...
        </div>
    </div>
`;
```

## Testing Checklist

- [ ] Preview extraction works correctly
- [ ] Error messages display with proper styling
- [ ] Success messages display correctly
- [ ] Preview results are readable
- [ ] Dark mode looks good
- [ ] Mobile responsive
- [ ] No JavaScript errors

## Estimated Time
**15-20 minutes** (simple find/replace + testing)

## Files to Modify
1. `templates/admin.html` (JavaScript section, lines 1439, 3477, 4368, 4885, 4888, 4954, 4996)

## Success Criteria
- ✅ All `alert-danger-custom` replaced with `alert alert-danger`
- ✅ All `alert-warning-custom` replaced with `alert alert-warning`
- ✅ Error messages display correctly
- ✅ Preview functionality maintained
- ✅ Visual consistency with design system

## Notes

### Scope
This migration focuses on alert classes. The preview results styling can be enhanced later if needed, but the current styling is functional.

### Related Changes
- Part of comprehensive admin.html migration
- Follows Tab 1 button standardization
- Prepares for Tab 3 migration