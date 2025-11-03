# Phase 4: Tab 1 Migration - Upload Boundaries

## Overview
Migrating the "Upload Boundaries" tab from admin.html to use the design system components.

## Current State Analysis

### HTML Structure (Lines 465-510)
- **Header**: H4 with icon and description
- **Form**: Upload form with two columns
  - Left column: Boundary type dropdown + custom type input (conditional)
  - Right column: File input
- **Submit button**: Primary button with icon
- **Status div**: For displaying upload results

### Current Issues
1. Uses `btn-custom` class (not in design system)
2. Form layout is good but could use design system form patterns
3. Status div needs proper alert component styling
4. No visual feedback for file selection

### JavaScript Dependencies (Lines 4716-4800+)
- Form submit handler with async upload
- `getSelectedBoundaryType()` helper function
- `showStatus()` for displaying messages
- `loadBoundaries()` to refresh boundary list
- `initializeCustomTypeControls()` for conditional display

## Migration Strategy

### Approach: **Minimal Changes**
Since this tab has:
- Clean, functional form layout
- Good user experience
- Proper JavaScript integration
- No major visual issues

**Decision**: Apply design system classes without restructuring

### Changes Required

1. **Button Classes**
   - Replace: `btn-custom btn-primary` 
   - With: `btn btn-primary`

2. **Status Display**
   - Enhance `showStatus()` to use design system alert components
   - Add proper alert classes (alert-success, alert-danger, alert-warning)

3. **Form Enhancements** (Optional)
   - Add file input feedback (show selected filename)
   - Consider adding form validation styling

4. **Loading State**
   - Ensure loading spinner uses design system spinner

## Implementation Plan

### Step 1: Update Button Classes
```html
<!-- Before -->
<button type="submit" class="btn btn-custom btn-primary">
    <i class="fas fa-upload"></i> Upload Boundaries
</button>

<!-- After -->
<button type="submit" class="btn btn-primary">
    <i class="fas fa-upload"></i> Upload Boundaries
</button>
```

### Step 2: Enhance Status Display
Update the `showStatus()` function to use design system alerts:

```javascript
function showStatus(message, type) {
    const statusDiv = document.getElementById('uploadStatus');
    if (!statusDiv) return;
    
    const alertClass = `alert alert-${type} alert-dismissible fade show`;
    statusDiv.innerHTML = `
        <div class="${alertClass}" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
}
```

### Step 3: Add File Input Feedback (Optional Enhancement)
```javascript
document.getElementById('geoJsonFile').addEventListener('change', function(e) {
    const fileName = e.target.files[0]?.name;
    if (fileName) {
        // Show selected file feedback
        const feedback = document.createElement('div');
        feedback.className = 'form-text text-success mt-1';
        feedback.innerHTML = `<i class="fas fa-check-circle"></i> Selected: ${fileName}`;
        
        // Remove old feedback if exists
        const oldFeedback = this.parentElement.querySelector('.file-feedback');
        if (oldFeedback) oldFeedback.remove();
        
        feedback.classList.add('file-feedback');
        this.parentElement.appendChild(feedback);
    }
});
```

## Testing Checklist

- [ ] Upload form submits correctly
- [ ] Status messages display with proper styling
- [ ] Custom boundary type shows/hides correctly
- [ ] File selection works
- [ ] Loading state displays properly
- [ ] Success/error messages are clear
- [ ] Dark mode looks good
- [ ] Mobile responsive

## Estimated Time
**20-30 minutes** (minimal changes, mostly class replacements)

## Files to Modify
1. `templates/admin.html` (lines 465-510, 4716-4800)

## Success Criteria
- ✅ All `btn-custom` classes removed
- ✅ Status messages use design system alerts
- ✅ Form maintains functionality
- ✅ Visual consistency with other migrated tabs
- ✅ No regressions in upload functionality