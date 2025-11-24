# UI Component Checklist

## Color System Reference

EAS Station uses a comprehensive CSS variable system defined in `static/css/base.css` and `static/css/design-system.css`. Always use these variables instead of hardcoded colors.

### Core Color Variables

#### Primary Brand Colors
- `--primary-color`: Main brand color (Aegean Blue by default)
- `--primary-soft`: Lighter variant of primary
- `--secondary-color`: Secondary brand color (Plum Crazy by default)
- `--secondary-soft`: Lighter variant of secondary
- `--accent-color`: Accent highlights
- `--accent-primary`: Primary accent (alias)
- `--accent-secondary`: Secondary accent (alias)

#### Status Colors
- `--success-color`: Success states and positive feedback
- `--danger-color`: Errors and critical warnings
- `--warning-color`: Warnings and cautionary states
- `--info-color`: Informational messages
- `--critical-color`: Critical alerts (highest severity)

#### Background & Surface Colors
- `--bg-color`: Page background
- `--surface-color`: Card and component backgrounds
- `--bg-card`: Card backgrounds (alias)
- `--bg-primary`: Primary dark background
- `--light-color`: Light variant background
- `--dark-color`: Dark variant background

#### Text Colors
- `--text-color`: Primary text (adapts to theme)
- `--text-secondary`: Secondary text (less prominent)
- `--text-muted`: Muted/disabled text
- `--text-inverse`: Inverse text (for dark backgrounds)
- `--color-text-primary`: Design system alias
- `--color-text-secondary`: Design system alias
- `--color-text-muted`: Design system alias

#### Border & Shadow
- `--border-color`: Standard borders
- `--border-color-light`: Lighter borders
- `--border-color-dark`: Darker borders
- `--shadow-color`: Drop shadow color
- `--shadow`: Shadow color (alias)

#### Design System Variables
The design system provides additional granular color scales:
- `--color-primary-50` through `--color-primary-900` (9 shades)
- `--color-neutral-50` through `--color-neutral-900` (9 shades)
- `--color-success-light`, `--color-success-dark`
- `--color-warning-light`, `--color-warning-dark`
- `--color-danger-light`, `--color-danger-dark`
- `--color-info-light`, `--color-info-dark`

### Typography Variables
- `--font-sans`: System sans-serif font stack
- `--font-mono`: Monospace font stack
- `--text-xs` through `--text-5xl`: Font size scale
- `--font-normal`, `--font-medium`, `--font-semibold`, `--font-bold`: Font weights
- `--leading-none` through `--leading-loose`: Line heights

### Spacing & Layout
- `--space-0` through `--space-24`: Spacing scale (0-96px)
- `--spacing-xs`, `--spacing-sm`, `--spacing-md`, `--spacing-lg`, `--spacing-xl`: Semantic spacing
- `--radius-none` through `--radius-full`: Border radius scale
- `--layout-padding-top`, `--layout-padding-x`, `--layout-padding-bottom`: Layout spacing

### Shadows & Effects
- `--shadow-xs` through `--shadow-2xl`: Shadow scale (6 levels)
- `--transition-fast`, `--transition-base`, `--transition-slow`: Transitions
- `--logo-backdrop`, `--logo-border-color`, `--logo-shadow`: Logo treatment

## Theme Support

The system supports 15+ theme variants:
- **Light themes**: cosmo (default), spring, tide, sunset
- **Dark themes**: dark, coffee, aurora, nebula, midnight
- **Color themes**: red, green, blue, purple, pink, orange, yellow

All themes automatically adapt all CSS variables. Components using variables will work across all themes without modification.

## Checklist for New UI Components

When adding or modifying UI components:

### 1. Colors
- [ ] Use CSS variables for ALL colors (no hardcoded hex values)
- [ ] Use semantic color names (e.g., `--success-color` not `--green`)
- [ ] Test component in both light and dark themes
- [ ] Test in at least 2-3 different theme variants
- [ ] Ensure text has sufficient contrast (WCAG AA: 4.5:1 for normal text, 3:1 for large text)

### 2. Typography
- [ ] Use typography variables (`--text-*`, `--font-*`, `--leading-*`)
- [ ] Ensure font sizes scale appropriately
- [ ] Use semantic font weights
- [ ] Test readability at different viewport sizes

### 3. Spacing & Layout
- [ ] Use spacing variables (`--space-*` or `--spacing-*`)
- [ ] Use border radius variables (`--radius-*`)
- [ ] Use shadow variables (`--shadow-*`)
- [ ] Test responsive behavior (mobile, tablet, desktop)

### 4. Accessibility
- [ ] Add proper ARIA labels and roles
- [ ] Ensure keyboard navigation works
- [ ] Test with focus outlines visible (`:focus-visible`)
- [ ] Add alternative text for images and icons
- [ ] Use semantic HTML elements
- [ ] Minimum touch target size of 44x44px (48x48px on mobile)
- [ ] Test with screen reader if critical functionality

### 5. Interactive States
- [ ] Define hover states using CSS variables
- [ ] Define focus states (outline visible)
- [ ] Define active/pressed states
- [ ] Define disabled states (reduced opacity, cursor not-allowed)
- [ ] Use transition variables for smooth animations
- [ ] Respect `prefers-reduced-motion` media query

### 6. Buttons
Always use these classes from `static/css/components.css`:
- `.btn` - Base button
- `.btn-primary` - Primary actions (uses `--color-primary-500`)
- `.btn-secondary` - Secondary actions (uses `--color-surface`)
- `.btn-success` - Success actions (uses `--color-success`)
- `.btn-warning` - Warning actions (uses `--color-warning`)
- `.btn-danger` - Destructive actions (uses `--color-danger`)
- `.btn-ghost` - Minimal button (transparent background)
- `.btn-sm`, `.btn-lg` - Size variants
- `.btn-icon` - Icon-only buttons

### 7. Cards
Use card classes from `static/css/components.css`:
- `.card` - Base card
- `.card-elevated` - Card with shadow
- `.card-outlined` - Card with border only
- `.card-success`, `.card-warning`, `.card-danger`, `.card-info` - Status cards

### 8. Alerts & Notifications
Use alert classes:
- `.alert-success` - Success messages
- `.alert-warning` - Warning messages
- `.alert-danger` - Error messages
- `.alert-info` - Informational messages

### 9. Forms
- Use `.form-label`, `.form-control`, `.form-select` classes
- Mark required fields with `.required` class on label
- Add `.error` class for error states
- Include `.error-message` for validation feedback
- Ensure inputs have `min-height: 44px` (48px on mobile)

### 10. Logo Usage
The logo is available as an SVG partial in `templates/partials/logo_wordmark.html`:
- Navbar logo: `brand-logo` class (height: 112px, 80px on mobile)
- Dashboard/landing page logo: `dashboard-page-logo` class (max-width: 360px, 280px on mobile)
- Footer logo: `footer-logo` class (max-width: 200px)
- Logo colors adapt to theme automatically via CSS variables
- Logo has proper semantic HTML with `role="img"` and `aria-label`

## Files to Update When Changing Colors

If you need to add new color variants:

1. **Define in base.css**: Add CSS variable in `:root` and theme variants
2. **Update design-system.css**: Add to semantic color aliases if needed
3. **Update this checklist**: Document the new variable and its purpose
4. **Test across themes**: Verify the color works in all 15+ theme variants

## Common Pitfalls to Avoid

❌ **DON'T**:
- Use hardcoded hex colors (e.g., `color: #204885`)
- Use RGB colors (e.g., `color: rgb(32, 72, 133)`)
- Use Bootstrap color classes that don't adapt to theme (e.g., `bg-white`, `text-dark`)
- Hardcode shadows (use `--shadow-*` variables)
- Use fixed pixel spacing (use `--space-*` or rem values)
- Skip theme testing
- Forget keyboard accessibility

✅ **DO**:
- Use CSS variables for all colors (e.g., `color: var(--primary-color)`)
- Use semantic variable names
- Test in multiple themes (light and dark minimum)
- Use spacing and typography scales
- Add proper focus states
- Ensure sufficient color contrast
- Use rem units for scalable typography
- Test with keyboard navigation
- Add ARIA labels for screen readers

## Quick Reference

### Most Common Variables
```css
/* Colors */
background-color: var(--surface-color);
color: var(--text-color);
border: 1px solid var(--border-color);

/* Buttons */
background-color: var(--primary-color);
color: var(--text-inverse);

/* Status */
background-color: var(--success-color);  /* or --warning-color, --danger-color, --info-color */

/* Spacing */
padding: var(--space-4);
gap: var(--space-3);
margin-bottom: var(--space-6);

/* Shadows */
box-shadow: var(--shadow-md);

/* Borders */
border-radius: var(--radius-lg);

/* Typography */
font-size: var(--text-base);
font-weight: var(--font-semibold);
line-height: var(--leading-normal);

/* Transitions */
transition: all var(--transition-fast);
```

## Resources

- **Base styles**: `static/css/base.css` - Theme definitions and color variables
- **Design system**: `static/css/design-system.css` - Design tokens and scales
- **Components**: `static/css/components.css` - Pre-built component styles
- **Layout**: `static/css/layout.css` - Navigation, header, footer
- **Accessibility**: `static/css/accessibility.css` - WCAG compliance helpers
- **Logo partial**: `templates/partials/logo_wordmark.html` - Reusable logo component

## Version
Last updated: 2025-11-21
Based on: EAS Station CSS architecture with 15+ theme support
