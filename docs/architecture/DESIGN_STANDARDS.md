# EAS Station™ Design Standards
## Enterprise-Grade Design System Guidelines

**Version:** 3.0 - Professional Edition  
**Last Updated:** December 2025  
**Status:** ✅ MANDATORY - All new pages and components MUST follow these standards

---

## 🎯 Mission Statement

EAS Station™ is a **professional, enterprise-grade** emergency alert management system. Every aspect of the user interface must reflect this standard. No exceptions.

---

## 📋 Core Principles

### 1. Consistency is Non-Negotiable
- Every page uses the same components
- Same spacing, same colors, same patterns
- If it looks different, it's wrong

### 2. Professional Over Flashy
- Subtle animations, not distracting
- Clean gradients, not rainbow colors
- Enterprise users, not consumers

### 3. Accessibility First
- WCAG AA minimum standard
- Keyboard navigation always works
- Screen readers properly supported

### 4. Performance Matters
- 60fps animations or none at all
- No jank, no lag, no stuttering
- Smooth professional experience

---

## 🎨 Visual Design System

### Color Palette

#### Primary Brand Colors
```css
--primary-color: #1e3a8a;      /* Deep Professional Blue */
--primary-soft: #3b82f6;       /* Bright Blue */
--secondary-color: #7c3aed;    /* Professional Purple */
--accent-color: #3b82f6;       /* Accent Blue */
```

#### Status Colors
```css
--success-color: #10b981;      /* Green - Success */
--danger-color: #ef4444;       /* Red - Danger/Error */
--warning-color: #f59e0b;      /* Amber - Warning */
--info-color: #3b82f6;         /* Blue - Info */
```

#### Neutrals
```css
--bg-color: #f1f5f9;           /* Page background */
--surface-color: #ffffff;      /* Card/surface */
--text-color: #0f172a;         /* Primary text */
--text-secondary: #475569;     /* Secondary text */
--text-muted: #94a3b8;         /* Muted text */
--border-color: #e2e8f0;       /* Borders */
```

### Typography Scale

#### Font Families
- **Body**: System font stack (San Francisco, Segoe UI, Roboto, etc.)
- **Mono**: UI monospace (SF Mono, Menlo, Monaco, etc.)

#### Type Scale (Perfect Fourth - 1.333 ratio)
```css
--font-size-xs:   0.75rem;     /* 12px - Small labels */
--font-size-sm:   0.875rem;    /* 14px - Body small, buttons */
--font-size-base: 1rem;        /* 16px - Body text */
--font-size-lg:   1.125rem;    /* 18px - Large text */
--font-size-xl:   1.333rem;    /* 21px - Small headings */
--font-size-2xl:  1.777rem;    /* 28px - Medium headings */
--font-size-3xl:  2.369rem;    /* 38px - Large headings */
```

#### Font Weights
```css
--font-weight-normal:    400;   /* Body text */
--font-weight-medium:    500;   /* Emphasis */
--font-weight-semibold:  600;   /* Headings, buttons */
--font-weight-bold:      700;   /* Strong emphasis */
--font-weight-extrabold: 800;   /* Extra emphasis */
```

### Spacing System

**Base Unit:** 4px  
**Scale:** Powers and multiples of 4

```css
--spacing-1:  0.25rem;  /*  4px */
--spacing-2:  0.5rem;   /*  8px */
--spacing-3:  0.75rem;  /* 12px */
--spacing-4:  1rem;     /* 16px */
--spacing-5:  1.25rem;  /* 20px */
--spacing-6:  1.5rem;   /* 24px */
--spacing-8:  2rem;     /* 32px */
--spacing-10: 2.5rem;   /* 40px */
--spacing-12: 3rem;     /* 48px */
--spacing-16: 4rem;     /* 64px */
```

### Shadows

```css
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
--shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
--shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
--shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
```

### Border Radius

```css
--radius-sm:  0.375rem;  /*  6px - Small elements */
--radius-md:  0.5rem;    /*  8px - Buttons, inputs */
--radius-lg:  0.75rem;   /* 12px - Cards */
--radius-xl:  1rem;      /* 16px - Large cards */
--radius-2xl: 1.5rem;    /* 24px - Extra large */
```

---

## 🧩 Component Standards

### Page Header (MANDATORY)

**Every page MUST start with this:**

```html
<div class="page-header">
    <div class="container-fluid">
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-3">
            <div>
                <h1 class="page-title mb-0">
                    <i class="fas fa-icon-name me-2"></i>Page Title
                </h1>
                <p class="page-subtitle mb-0">Brief page description</p>
            </div>
            <div class="page-header-actions">
                <button class="btn btn-success">
                    <i class="fas fa-plus me-1"></i>Primary Action
                </button>
                <a href="#" class="btn btn-outline-light">
                    <i class="fas fa-cog me-1"></i>Secondary
                </a>
            </div>
        </div>
    </div>
</div>
```

**Rules:**
- Page title must have an icon with `me-2` spacing
- Subtitle is optional but recommended
- Actions go in `page-header-actions`
- Primary actions use solid buttons
- Secondary actions use `btn-outline-light`

### Section Headers

```html
<div class="section-header">
    <div>
        <h3 class="section-title mb-0">
            <i class="fas fa-icon me-2"></i>Section Title
        </h3>
        <p class="section-subtitle mb-0">Optional description</p>
    </div>
    <div class="section-actions">
        <button class="btn btn-sm btn-primary">Action</button>
    </div>
</div>
```

### Cards

```html
<!-- Standard Card -->
<div class="card">
    <div class="card-header">
        <h5 class="mb-0">Card Title</h5>
    </div>
    <div class="card-body">
        Card content here
    </div>
</div>

<!-- Colored Header Card -->
<div class="card">
    <div class="card-header bg-success">
        <h5 class="mb-0">Success Card</h5>
    </div>
    <div class="card-body">
        Content
    </div>
</div>
```

**Available header classes:**
- `bg-primary` - Primary gradient
- `bg-success` - Success gradient
- `bg-warning` - Warning gradient
- `bg-danger` - Danger gradient
- `bg-info` - Info gradient

### Statistics Cards

```html
<div class="stats-grid">
    <div class="card bg-success-gradient text-white">
        <div class="card-body text-center">
            <h3 class="mb-0">125</h3>
            <small>Label</small>
        </div>
    </div>
    <!-- More stat cards -->
</div>
```

**Available classes:**
- `.bg-success-gradient`
- `.bg-warning-gradient`
- `.bg-danger-gradient`
- `.bg-info-gradient`
- `.stat-card` (default primary gradient)

### Buttons

```html
<!-- With Icon (REQUIRED) -->
<button class="btn btn-primary">
    <i class="fas fa-save me-1"></i>Save Changes
</button>

<!-- Button Variants -->
<button class="btn btn-primary">Primary</button>
<button class="btn btn-success">Success</button>
<button class="btn btn-danger">Danger</button>
<button class="btn btn-warning">Warning</button>
<button class="btn btn-outline-primary">Outline</button>
<button class="btn btn-outline-light">Light (for dark backgrounds)</button>

<!-- Button Sizes -->
<button class="btn btn-sm">Small</button>
<button class="btn">Default</button>
<button class="btn btn-lg">Large</button>
```

**Rules:**
- ALL buttons must have icons
- Icon spacing: `me-1` (0.25rem gap)
- Use solid for primary actions
- Use outline for secondary actions
- Use `btn-outline-light` on gradient backgrounds

### Info Boxes

```html
<!-- Info -->
<div class="info-box">
    <div class="info-box-title"><i class="fas fa-info-circle me-2"></i>Title</div>
    Message content
</div>

<!-- Variants -->
<div class="info-box success">...</div>
<div class="info-box warning">...</div>
<div class="info-box danger">...</div>
```

### Empty States

```html
<div class="empty-state">
    <div class="empty-state-icon">
        <i class="fas fa-inbox"></i>
    </div>
    <div class="empty-state-title">No Items</div>
    <div class="empty-state-text">Description</div>
    <button class="btn btn-primary">
        <i class="fas fa-plus me-1"></i>Create Item
    </button>
</div>
```

### Layout Grids

```html
<!-- 2 Column -->
<div class="content-grid content-grid-2">
    <div class="card">...</div>
    <div class="card">...</div>
</div>

<!-- 3 Column -->
<div class="content-grid content-grid-3">
    <div class="card">...</div>
    <div class="card">...</div>
    <div class="card">...</div>
</div>

<!-- 4 Column -->
<div class="content-grid content-grid-4">
    <div class="card">...</div>
    <div class="card">...</div>
    <div class="card">...</div>
    <div class="card">...</div>
</div>
```

---

## 🚫 DO NOT Do These Things

### ❌ NO Inline Styles
```html
<!-- WRONG -->
<div style="color: red; padding: 10px;">
    Content
</div>

<!-- CORRECT -->
<div class="info-box danger">
    Content
</div>
```

### ❌ NO Hardcoded Colors
```css
/* WRONG */
.custom-box {
    background: #FF0000;
    color: #0000FF;
}

/* CORRECT */
.custom-box {
    background: var(--danger-color);
    color: var(--primary-color);
}
```

### ❌ NO Random Spacing
```html
<!-- WRONG -->
<div style="margin-bottom: 13px;">
    
<!-- CORRECT -->
<div class="mb-3">  <!-- Uses standard spacing scale -->
```

### ❌ NO Mixed Component Styles
```html
<!-- WRONG - Mixing different patterns -->
<div class="some-custom-header-style">
    <h2>Page Title</h2>
</div>

<!-- CORRECT - Use standard page header -->
<div class="page-header">
    <div class="container-fluid">
        <h1 class="page-title"><i class="fas fa-icon me-2"></i>Page Title</h1>
    </div>
</div>
```

### ❌ NO Buttons Without Icons
```html
<!-- WRONG -->
<button class="btn btn-primary">Save</button>

<!-- CORRECT -->
<button class="btn btn-primary">
    <i class="fas fa-save me-1"></i>Save
</button>
```

---

## ✅ Best Practices

### 1. Consistent Spacing
- Use margin bottom classes: `mb-3`, `mb-4`, `mb-5`
- Section spacing: `mb-5` (3rem)
- Card spacing: `mb-4` (1.5rem)
- Element spacing: `mb-3` (1rem)

### 2. Icon Usage
- Font Awesome 6.4.0
- Always prefix text with icons
- Use `me-1` or `me-2` for spacing
- Match icon to action (save → fa-save, edit → fa-edit)

### 3. Visual Hierarchy
```
Page Header (largest, gradient background)
  ↓
Section Header (medium, subtle background)
  ↓
Cards (contained content)
  ↓
Form elements / Lists
```

### 4. Color Usage
- **Primary**: Main actions, headers
- **Success**: Positive actions (save, create, confirm)
- **Warning**: Caution, review needed
- **Danger**: Destructive actions (delete, cancel, error)
- **Info**: Informational, neutral actions

### 5. Responsive Design
- Use Bootstrap grid: `col-12 col-md-6 col-lg-4`
- Flex utilities: `d-flex`, `justify-content-between`
- Responsive spacing: `mb-3 mb-md-4`
- Mobile-first approach

---

## 📐 Layout Templates

### Standard Page Layout

```html
<div class="container-fluid">
    <!-- Page Header -->
    <div class="page-header">
        <!-- ... -->
    </div>

    <!-- Stats Cards (Optional) -->
    <div class="stats-grid">
        <!-- ... -->
    </div>

    <!-- Section 1 -->
    <div class="section-header">
        <!-- ... -->
    </div>
    <div class="card">
        <!-- ... -->
    </div>

    <!-- Section 2 -->
    <div class="section-header">
        <!-- ... -->
    </div>
    <div class="content-grid content-grid-2">
        <!-- ... -->
    </div>
</div>
```

### Form Page Layout

```html
<div class="container-fluid">
    <!-- Page Header -->
    <div class="page-header"><!-- ... --></div>

    <!-- Form Card -->
    <div class="card">
        <div class="card-header">
            <h5 class="mb-0">Form Title</h5>
        </div>
        <div class="card-body">
            <form>
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="form-label">Field Label</label>
                        <input type="text" class="form-control">
                    </div>
                    <!-- More fields -->
                </div>
                <div class="mt-4">
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-save me-1"></i>Save
                    </button>
                    <button type="button" class="btn btn-outline-secondary">
                        <i class="fas fa-times me-1"></i>Cancel
                    </button>
                </div>
            </form>
        </div>
    </div>
</div>
```

---

## 🎬 Animation Guidelines

### Timing
```css
--transition-fast:   150ms;  /* Button hovers, small changes */
--transition-medium: 250ms;  /* Card hovers, modals */
--transition-slow:   350ms;  /* Page transitions */
```

### Easing
```css
--ease-smooth: cubic-bezier(0.4, 0.0, 0.2, 1);  /* Default */
--ease-enter:  cubic-bezier(0.0, 0.0, 0.2, 1);  /* Elements entering */
--ease-exit:   cubic-bezier(0.4, 0.0, 1, 1);    /* Elements leaving */
```

### What to Animate
- ✅ Opacity
- ✅ Transform (translate, scale)
- ✅ Box-shadow
- ✅ Background-color
- ❌ Width/Height (causes reflow)
- ❌ Top/Left (use transform instead)

---

## 🧪 Testing Checklist

Before committing any page changes:

- [ ] Page uses standard page header
- [ ] All sections have section headers
- [ ] Cards use proper card classes
- [ ] All buttons have icons
- [ ] Spacing follows the scale
- [ ] Colors use CSS variables
- [ ] Responsive on mobile (320px+)
- [ ] Keyboard navigation works
- [ ] No console errors
- [ ] Tested in light and dark themes

---

## 📚 Reference Files

1. **Live Style Guide**: `/style_guide` route (view in browser)
2. **Component Templates**: `templates/partials/`
3. **CSS Variables**: `static/css/styles.css` (lines 1-150)

---

## 🆘 Getting Help

### When Unsure
1. Check the style guide page (`/style_guide`)
2. Look at recently updated pages for examples
3. Copy patterns from `alerts.html` (good example)

### Questions to Ask
- "Does this page look like it came from the same designer as others?"
- "Would a Fortune 500 company use this interface?"
- "Is every element consistent with the design system?"

If the answer to any is "no", it needs revision.

---

## 📝 Version History

- **v3.0** (December 2025): Professional design system overhaul
- **v2.0** (November 2025): Theme improvements and gradients
- **v1.0** (October 2025): Initial design system

---

**Remember**: Consistency is not optional. It's mandatory. Every page, every component, every interaction must follow these standards. No exceptions.
