# UI Design System & Color Palette Guide

This document provides guidance for maintaining consistent UI styling across the EAS Station application.

## 🎨 Unified Color Palette

The application uses a unified color palette defined in `static/css/design-system.css`. **Always use these CSS variables** for consistency across the application.

### Primary Theme Colors

#### Light Mode
```css
--color-primary: #0B66FF;      /* Main brand color - vibrant blue */
--color-accent: #FF6B35;        /* Accent color - warm orange */
--color-bg: #e8ecf7;            /* Page background */
--color-surface: #ffffff;       /* Cards and elevated surfaces */
--color-text: #1c2233;          /* Primary text */
--color-muted: #5a6c8f;         /* Secondary/muted text (WCAG AA compliant) */
```

#### Dark Mode
```css
--color-primary: #5a88d5;       /* Lightened primary for dark backgrounds */
--color-accent: #FF8C5A;        /* Lightened accent for dark backgrounds */
--color-bg: #0F1724;            /* Dark page background */
--color-surface: #111827;       /* Dark card surfaces */
--color-text: #E5E7EB;          /* Light text on dark */
--color-muted: #9CA3AF;         /* Muted text on dark */
```

### Status Colors (WCAG AA Compliant)
```css
--color-success: #059669;       /* Success/positive states (darkened for contrast) */
--color-warning: #d97706;       /* Warning/caution states (darkened for contrast) */
--color-error: #dc2626;         /* Error/danger states (darkened for contrast) */
```

**Note**: Status colors meet WCAG AA standards for large text (18pt+) and UI components. Error color meets AA for normal text as well.

### Extended Palette
For nuanced color needs, use the extended primary palette:
- `--color-primary-50` through `--color-primary-900` (lightest to darkest)
- `--color-neutral-50` through `--color-neutral-900`

## 🔤 Typography

```css
/* Font Families */
--font-sans: System font stack (default)
--font-mono: Monospace font stack

/* Font Sizes */
--text-xs: 0.75rem;    /* 12px */
--text-sm: 0.875rem;   /* 14px */
--text-base: 1rem;     /* 16px */
--text-lg: 1.125rem;   /* 18px */
--text-xl: 1.25rem;    /* 20px */
--text-2xl: 1.5rem;    /* 24px */
--text-3xl: 1.875rem;  /* 30px */

/* Font Weights */
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

## 📐 Spacing & Layout

```css
/* Spacing Scale */
--space-1: 0.25rem;    /* 4px */
--space-2: 0.5rem;     /* 8px */
--space-3: 0.75rem;    /* 12px */
--space-4: 1rem;       /* 16px */
--space-6: 1.5rem;     /* 24px */
--space-8: 2rem;       /* 32px */

/* Border Radius */
--radius-sm: 0.25rem;  /* 4px */
--radius-md: 0.375rem; /* 6px */
--radius-lg: 0.5rem;   /* 8px */
--radius-xl: 0.75rem;  /* 12px */
```

## 🎯 Component Guidelines

### Buttons
Use standardized button classes from `static/css/components.css`:
- `.btn-primary` - Primary actions (uses `--color-primary`)
- `.btn-secondary` - Secondary actions
- `.btn-ghost` - Tertiary/minimal actions
- `.btn-success`, `.btn-warning`, `.btn-danger` - Status-specific actions

### Links
Links automatically use `--color-primary` with `--color-accent` on hover. Enhanced focus styles are applied for accessibility.

### Cards
Cards use `--color-surface` for background and `--color-border` for borders. Status variants available:
- `.card-success`, `.card-warning`, `.card-danger`, `.card-info`

## ♿ Accessibility Requirements

### Focus States
All interactive elements have enhanced focus styles using `--color-accent` with 3px outline for visibility:
```css
element:focus-visible {
    outline: 3px solid var(--color-accent);
    outline-offset: 2px;
}
```

### Contrast Requirements
- All text must meet WCAG AA contrast ratio (4.5:1 for normal text, 3:1 for large text)
- Status colors are chosen to meet WCAG AA standards
- Test contrast using browser DevTools or online checkers

### Interactive Element Sizing
- Minimum touch target: 44x44px (enforced in `.btn` class)
- Adequate spacing between interactive elements

## 🎨 Logo Usage

### Navbar Logo
- Located in: `templates/components/navbar.html`
- Max height: 56px (set in `static/css/layout.css`)
- Uses accent color for logo bars: `fill: var(--color-accent)`
- White text on navbar for contrast

### Hero/Landing Logo
- Class: `.hero-logo` or `.dashboard-page-logo`
- Max height: 120px (responsive: 96px tablet, 80px mobile)
- Automatically scales down on smaller screens

### Logo Files
- SVG preferred: `static/img/eas-station-logo.svg`
- Wordmark: `static/img/eas-system-wordmark.svg`
- SVGs are scalable and maintain quality at all sizes

## 📝 Best Practices

### DO:
✅ Use CSS variables for all colors: `var(--color-primary)`  
✅ Use the unified theme colors for consistency  
✅ Test in both light and dark modes  
✅ Validate color contrast for accessibility  
✅ Use semantic HTML and ARIA labels  
✅ Maintain minimum touch target sizes  

### DON'T:
❌ Hard-code color hex values in new code  
❌ Use inline styles for colors (use CSS classes)  
❌ Create new color variables without documenting them  
❌ Override focus styles without ensuring accessibility  
❌ Use small text without proper contrast  

## 🔄 Making Changes

When adding new UI components:

1. **Reference existing variables** from `design-system.css`
2. **Add styles** to appropriate CSS file:
   - `base.css` - Core HTML element styles
   - `components.css` - Reusable component styles
   - `layout.css` - Page layout and navigation
   - `utilities.css` - Utility classes
3. **Test** in light and dark modes
4. **Validate** color contrast meets WCAG AA
5. **Document** any new patterns in this file

## 📚 File Structure

```
static/css/
├── design-system.css      # ⭐ Primary theme variables and utilities
├── base.css               # Core HTML element styles and legacy theme vars
├── components.css         # Reusable UI components (buttons, cards, badges)
├── layout.css             # Navigation, footer, and page layout
├── utilities.css          # Utility classes
├── accessibility.css      # Accessibility enhancements
├── responsive-enhancements.css  # Responsive utilities
└── ...
```

## 🎯 Quick Reference

Need a color? Use these:
- **Brand/Primary actions**: `var(--color-primary)`
- **Highlights/CTAs**: `var(--color-accent)`
- **Success messages**: `var(--color-success)`
- **Warnings**: `var(--color-warning)`
- **Errors**: `var(--color-error)`
- **Text**: `var(--color-text)`
- **Muted text**: `var(--color-muted)`
- **Backgrounds**: `var(--color-bg)`, `var(--color-surface)`

## 📞 Questions?

For questions about UI patterns or to propose changes to the design system, please:
1. Review this guide and existing CSS
2. Check `static/css/design-system.css` for available variables
3. Create an issue describing the use case
4. Propose changes that maintain consistency

---

**Last Updated**: November 2025  
**Maintained by**: KR8MER/eas-station contributors
