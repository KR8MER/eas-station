# Form Components Guide

## Overview
This guide provides standardized form patterns using the design system for consistent form layouts across the EAS Station application.

## Form Layout Patterns

### 1. Basic Form Structure
```html
<div class="card">
    <div class="card-header">
        <h5 class="card-title mb-0">
            <i class="fas fa-icon"></i> Form Title
        </h5>
    </div>
    <div class="card-body">
        <form method="POST" action="/endpoint">
            <!-- Form fields here -->
            
            <div class="form-actions">
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Save Changes
                </button>
                <button type="reset" class="btn btn-secondary">
                    <i class="fas fa-undo"></i> Reset
                </button>
            </div>
        </form>
    </div>
</div>
```

### 2. Form Field Patterns

#### Text Input
```html
<div class="mb-3">
    <label for="field-name" class="form-label">Field Label</label>
    <input type="text" class="form-control" id="field-name" name="field_name" 
           placeholder="Enter value..." required>
    <div class="form-text">Helper text for this field</div>
</div>
```

#### Select Dropdown
```html
<div class="mb-3">
    <label for="select-field" class="form-label">Select Option</label>
    <select class="form-select" id="select-field" name="select_field" required>
        <option value="">Choose...</option>
        <option value="option1">Option 1</option>
        <option value="option2">Option 2</option>
    </select>
</div>
```

#### Checkbox
```html
<div class="mb-3">
    <div class="form-check">
        <input class="form-check-input" type="checkbox" id="checkbox-field" 
               name="checkbox_field" value="true">
        <label class="form-check-label" for="checkbox-field">
            Enable this option
        </label>
    </div>
</div>
```

#### Radio Buttons
```html
<div class="mb-3">
    <label class="form-label">Choose Option</label>
    <div class="form-check">
        <input class="form-check-input" type="radio" name="radio-group" 
               id="radio1" value="option1" checked>
        <label class="form-check-label" for="radio1">
            Option 1
        </label>
    </div>
    <div class="form-check">
        <input class="form-check-input" type="radio" name="radio-group" 
               id="radio2" value="option2">
        <label class="form-check-label" for="radio2">
            Option 2
        </label>
    </div>
</div>
```

#### Textarea
```html
<div class="mb-3">
    <label for="textarea-field" class="form-label">Description</label>
    <textarea class="form-control" id="textarea-field" name="textarea_field" 
              rows="4" placeholder="Enter description..."></textarea>
</div>
```

#### File Upload
```html
<div class="mb-3">
    <label for="file-upload" class="form-label">Upload File</label>
    <input class="form-control" type="file" id="file-upload" name="file_upload">
    <div class="form-text">Accepted formats: .csv, .json, .geojson</div>
</div>
```

### 3. Form Sections

#### Section with Header
```html
<div class="form-section mb-4">
    <h6 class="form-section-title">
        <i class="fas fa-cog"></i> Section Title
    </h6>
    <div class="form-section-content">
        <!-- Form fields here -->
    </div>
</div>
```

#### Collapsible Section
```html
<div class="accordion mb-4" id="accordionExample">
    <div class="accordion-item">
        <h2 class="accordion-header" id="headingOne">
            <button class="accordion-button" type="button" 
                    data-bs-toggle="collapse" data-bs-target="#collapseOne">
                <i class="fas fa-cog me-2"></i> Advanced Settings
            </button>
        </h2>
        <div id="collapseOne" class="accordion-collapse collapse show" 
             data-bs-parent="#accordionExample">
            <div class="accordion-body">
                <!-- Form fields here -->
            </div>
        </div>
    </div>
</div>
```

### 4. Form Actions

#### Standard Actions
```html
<div class="form-actions">
    <button type="submit" class="btn btn-primary">
        <i class="fas fa-save"></i> Save Changes
    </button>
    <button type="reset" class="btn btn-secondary">
        <i class="fas fa-undo"></i> Reset
    </button>
    <a href="/back" class="btn btn-outline-secondary">
        <i class="fas fa-times"></i> Cancel
    </a>
</div>
```

#### Actions with Confirmation
```html
<div class="form-actions">
    <button type="submit" class="btn btn-primary">
        <i class="fas fa-save"></i> Save Changes
    </button>
    <button type="button" class="btn btn-danger" 
            onclick="confirmDelete()">
        <i class="fas fa-trash"></i> Delete
    </button>
</div>
```

### 5. Validation States

#### Success State
```html
<div class="mb-3">
    <label for="valid-field" class="form-label">Valid Field</label>
    <input type="text" class="form-control is-valid" id="valid-field" 
           value="Valid input">
    <div class="valid-feedback">
        Looks good!
    </div>
</div>
```

#### Error State
```html
<div class="mb-3">
    <label for="invalid-field" class="form-label">Invalid Field</label>
    <input type="text" class="form-control is-invalid" id="invalid-field" 
           value="Invalid input">
    <div class="invalid-feedback">
        Please provide a valid value.
    </div>
</div>
```

### 6. Form Layouts

#### Two-Column Layout
```html
<div class="row g-3">
    <div class="col-md-6">
        <label for="first-name" class="form-label">First Name</label>
        <input type="text" class="form-control" id="first-name">
    </div>
    <div class="col-md-6">
        <label for="last-name" class="form-label">Last Name</label>
        <input type="text" class="form-control" id="last-name">
    </div>
</div>
```

#### Three-Column Layout
```html
<div class="row g-3">
    <div class="col-md-4">
        <label for="field1" class="form-label">Field 1</label>
        <input type="text" class="form-control" id="field1">
    </div>
    <div class="col-md-4">
        <label for="field2" class="form-label">Field 2</label>
        <input type="text" class="form-control" id="field2">
    </div>
    <div class="col-md-4">
        <label for="field3" class="form-label">Field 3</label>
        <input type="text" class="form-control" id="field3">
    </div>
</div>
```

#### Inline Form
```html
<form class="row row-cols-lg-auto g-3 align-items-center">
    <div class="col-12">
        <label class="visually-hidden" for="inline-input">Name</label>
        <input type="text" class="form-control" id="inline-input" 
               placeholder="Name">
    </div>
    <div class="col-12">
        <button type="submit" class="btn btn-primary">Submit</button>
    </div>
</form>
```

## Design System Integration

### CSS Classes to Use

#### Form Controls
- `form-control` - Standard input styling
- `form-select` - Select dropdown styling
- `form-check` - Checkbox/radio wrapper
- `form-check-input` - Checkbox/radio input
- `form-check-label` - Checkbox/radio label
- `form-label` - Field label
- `form-text` - Helper text
- `form-actions` - Action buttons container

#### Validation
- `is-valid` - Valid state
- `is-invalid` - Invalid state
- `valid-feedback` - Success message
- `invalid-feedback` - Error message

#### Layout
- `mb-3` - Margin bottom (spacing between fields)
- `row g-3` - Grid row with gap
- `col-md-6` - Column width (responsive)

### Custom CSS for Forms

Add to `static/css/components.css`:

```css
/* Form Sections */
.form-section {
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: var(--spacing-lg);
    background: var(--surface-color);
}

.form-section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-color);
    margin-bottom: var(--spacing-md);
    padding-bottom: var(--spacing-sm);
    border-bottom: 2px solid var(--border-color);
}

.form-section-content {
    padding-top: var(--spacing-sm);
}

/* Form Actions */
.form-actions {
    display: flex;
    gap: var(--spacing-sm);
    padding-top: var(--spacing-lg);
    border-top: 1px solid var(--border-color);
    margin-top: var(--spacing-lg);
}

/* Form Text */
.form-text {
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-top: var(--spacing-xs);
}

/* Required Field Indicator */
.form-label.required::after {
    content: " *";
    color: var(--danger-color);
}

/* Form Help Icon */
.form-help {
    display: inline-block;
    margin-left: var(--spacing-xs);
    color: var(--text-muted);
    cursor: help;
}

/* Disabled State */
.form-control:disabled,
.form-select:disabled {
    background-color: var(--light-color);
    opacity: 0.6;
    cursor: not-allowed;
}
```

## Best Practices

### 1. Accessibility
- Always use `<label>` elements with `for` attribute
- Provide helper text for complex fields
- Use proper ARIA labels when needed
- Ensure keyboard navigation works
- Maintain proper tab order

### 2. Validation
- Validate on both client and server side
- Provide clear error messages
- Show validation state visually
- Don't rely on color alone
- Use icons for validation states

### 3. User Experience
- Group related fields together
- Use appropriate input types
- Provide placeholder text
- Show character limits when applicable
- Auto-focus first field when appropriate
- Disable submit button during processing

### 4. Mobile Responsiveness
- Use responsive grid layouts
- Ensure touch targets are large enough (44px minimum)
- Stack fields vertically on mobile
- Use appropriate input types for mobile keyboards

### 5. Dark Mode
- All form elements support dark mode
- Proper contrast ratios maintained
- Focus states visible in both modes
- Validation colors work in both modes

## Migration Checklist

When migrating existing forms:

- [ ] Replace inline styles with design system classes
- [ ] Use proper form structure (card > card-body > form)
- [ ] Add form-label to all labels
- [ ] Use form-control for inputs
- [ ] Use form-select for dropdowns
- [ ] Add form-text for helper text
- [ ] Implement form-actions for buttons
- [ ] Add validation states where needed
- [ ] Test keyboard navigation
- [ ] Test mobile responsiveness
- [ ] Test dark mode
- [ ] Verify accessibility

## Examples

See the following files for examples:
- `templates/alerts_new.html` - Filter form example
- `templates/system_health_new.html` - Settings form example

## Next Steps

1. Apply these patterns to admin.html sections
2. Create reusable form components
3. Document specific form types (upload, multi-step, etc.)
4. Add JavaScript validation helpers