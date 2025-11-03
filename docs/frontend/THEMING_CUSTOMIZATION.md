# 🎨 EAS Station Theming & Customization Guide

## Overview

EAS Station features a comprehensive theming system built on CSS Custom Properties (CSS Variables) that allows for extensive customization while maintaining performance and accessibility. This guide covers theme creation, customization options, and brand adaptation.

## 🎯 Design System Architecture

### CSS Custom Properties Foundation
The entire design system is built on CSS Custom Properties for:
- **Dynamic Theming**: Runtime theme switching
- **Performance**: No recompilation required
- **Accessibility**: Maintains contrast ratios
- **Maintainability**: Single source of truth for design tokens

### Theme Structure
```
themes/
├── core/                 # Core design tokens
│   ├── colors.css       # Color system
│   ├── typography.css   # Font scales and styles
│   ├── spacing.css      # Spatial system
│   └── shadows.css      # Elevation and shadows
├── themes/              # Theme variants
│   ├── light.css        # Light theme
│   ├── dark.css         # Dark theme
│   └── high-contrast.css # Accessibility theme
└── brand/               # Brand customizations
    └── custom.css       # Custom brand colors
```

---

## 🌈 Color System

### Primary Color Palette
```css
:root {
  /* Primary Brand Colors */
  --color-primary-50: #e8eef9;
  --color-primary-100: #c5d5f0;
  --color-primary-200: #9eb9e6;
  --color-primary-300: #779ddc;
  --color-primary-400: #5a88d5;
  --color-primary-500: #3d73cd;  /* Main brand color */
  --color-primary-600: #376bc8;
  --color-primary-700: #2f5fb8;
  --color-primary-800: #2753a8;
  --color-primary-900: #1e4798;
}
```

### Semantic Color System
```css
:root {
  /* Success Colors */
  --color-success-50: #f0fdf4;
  --color-success-100: #dcfce7;
  --color-success-500: #22c55e;
  --color-success-600: #16a34a;
  --color-success-700: #15803d;
  
  /* Warning Colors */
  --color-warning-50: #fffbeb;
  --color-warning-100: #fef3c7;
  --color-warning-500: #f59e0b;
  --color-warning-600: #d97706;
  --color-warning-700: #b45309;
  
  /* Danger Colors */
  --color-danger-50: #fef2f2;
  --color-danger-100: #fee2e2;
  --color-danger-500: #ef4444;
  --color-danger-600: #dc2626;
  --color-danger-700: #b91c1c;
  
  /* Info Colors */
  --color-info-50: #f0f9ff;
  --color-info-100: #e0f2fe;
  --color-info-500: #06b6d4;
  --color-info-600: #0891b2;
  --color-info-700: #0e7490;
}
```

### Neutral Color System
```css
:root {
  /* Light Theme Neutrals */
  --color-gray-50: #f9fafb;
  --color-gray-100: #f3f4f6;
  --color-gray-200: #e5e7eb;
  --color-gray-300: #d1d5db;
  --color-gray-400: #9ca3af;
  --color-gray-500: #6b7280;
  --color-gray-600: #4b5563;
  --color-gray-700: #374151;
  --color-gray-800: #1f2937;
  --color-gray-900: #111827;
}

[data-theme="dark"] {
  /* Dark Theme Neutrals */
  --color-gray-50: #111827;
  --color-gray-100: #1f2937;
  --color-gray-200: #374151;
  --color-gray-300: #4b5563;
  --color-gray-400: #6b7280;
  --color-gray-500: #9ca3af;
  --color-gray-600: #d1d5db;
  --color-gray-700: #e5e7eb;
  --color-gray-800: #f3f4f6;
  --color-gray-900: #f9fafb;
}
```

---

## 🎨 Theme Implementation

### Base Theme Variables
```css
:root {
  /* Surface Colors */
  --color-surface: var(--color-gray-50);
  --color-surface-variant: var(--color-gray-100);
  --color-surface-container: var(--color-white);
  --color-surface-container-high: var(--color-gray-50);
  
  /* Content Colors */
  --color-on-surface: var(--color-gray-900);
  --color-on-surface-variant: var(--color-gray-700);
  --color-on-surface-container: var(--color-gray-900);
  
  /* Interactive Elements */
  --color-primary: var(--color-primary-500);
  --color-on-primary: var(--color-white);
  --color-primary-container: var(--color-primary-100);
  --color-on-primary-container: var(--color-primary-900);
  
  /* State Colors */
  --color-error: var(--color-danger-500);
  --color-on-error: var(--color-white);
  --color-warning: var(--color-warning-500);
  --color-on-warning: var(--color-gray-900);
  --color-success: var(--color-success-500);
  --color-on-success: var(--color-white);
}
```

### Dark Theme Override
```css
[data-theme="dark"] {
  /* Surface Colors */
  --color-surface: var(--color-gray-900);
  --color-surface-variant: var(--color-gray-800);
  --color-surface-container: var(--color-gray-800);
  --color-surface-container-high: var(--color-gray-700);
  
  /* Content Colors */
  --color-on-surface: var(--color-gray-100);
  --color-on-surface-variant: var(--color-gray-300);
  --color-on-surface-container: var(--color-gray-100);
  
  /* Interactive Elements */
  --color-primary: var(--color-primary-400);
  --color-on-primary: var(--color-gray-900);
  --color-primary-container: var(--color-primary-900);
  --color-on-primary-container: var(--color-primary-100);
}
```

### High Contrast Theme
```css
[data-theme="high-contrast"] {
  /* Enhanced contrast for accessibility */
  --color-primary: #0000ff;
  --color-on-primary: #ffffff;
  --color-surface: #000000;
  --color-on-surface: #ffffff;
  --color-error: #ff0000;
  --color-warning: #ffff00;
  --color-success: #00ff00;
  
  /* Strong borders and outlines */
  --border-width: 2px;
  --outline-width: 3px;
}
```

---

## 🎯 Component Theming

### Button Component
```css
.btn {
  /* Base button styles */
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  border: 1px solid var(--color-primary);
  
  /* Using color ramps for hover states */
  &:hover {
    background-color: var(--color-primary-600);
    border-color: var(--color-primary-600);
  }
  
  &:active {
    background-color: var(--color-primary-700);
  }
}

/* Button variants */
.btn-success {
  background-color: var(--color-success);
  color: var(--color-on-success);
  border-color: var(--color-success);
}

.btn-outline-primary {
  background-color: transparent;
  color: var(--color-primary);
  border-color: var(--color-primary);
  
  &:hover {
    background-color: var(--color-primary);
    color: var(--color-on-primary);
  }
}
```

### Card Component
```css
.card {
  background-color: var(--color-surface-container);
  border: 1px solid var(--color-surface-variant);
  color: var(--color-on-surface-container);
  
  /* Subtle shadows for elevation */
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

[data-theme="dark"] .card {
  /* Adjust shadows for dark theme */
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}
```

### Form Component
```css
.form-control {
  background-color: var(--color-surface);
  border: 1px solid var(--color-surface-variant);
  color: var(--color-on-surface);
  
  &:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 3px rgba(61, 115, 205, 0.1);
  }
  
  &.is-valid {
    border-color: var(--color-success);
  }
  
  &.is-invalid {
    border-color: var(--color-error);
  }
}
```

---

## 🛠️ Customization API

### JavaScript Theme Manager
```javascript
class EASThemeManager {
  constructor() {
    this.currentTheme = 'light';
    this.customColors = {};
    this.listeners = [];
  }
  
  // Set theme
  setTheme(themeName) {
    document.documentElement.setAttribute('data-theme', themeName);
    this.currentTheme = themeName;
    this.notifyListeners('change', themeName);
    this.savePreference(themeName);
  }
  
  // Get current theme
  getCurrentTheme() {
    return this.currentTheme;
  }
  
  // Toggle between light and dark
  toggle() {
    const newTheme = this.currentTheme === 'light' ? 'dark' : 'light';
    this.setTheme(newTheme);
  }
  
  // Set custom brand colors
  setCustomColors(colors) {
    Object.entries(colors).forEach(([key, value]) => {
      document.documentElement.style.setProperty(`--color-${key}`, value);
    });
    this.customColors = { ...this.customColors, ...colors };
    this.notifyListeners('colorsChanged', this.customColors);
  }
  
  // Apply system preference
  applySystemPreference() {
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      this.setTheme('dark');
    } else {
      this.setTheme('light');
    }
  }
  
  // Listen for changes
  on(event, callback) {
    this.listeners.push({ event, callback });
  }
  
  // Remove listener
  off(event, callback) {
    this.listeners = this.listeners.filter(
      listener => listener.event !== event || listener.callback !== callback
    );
  }
  
  // Private methods
  notifyListeners(event, data) {
    this.listeners
      .filter(listener => listener.event === event)
      .forEach(listener => listener.callback(data));
  }
  
  savePreference(theme) {
    localStorage.setItem('eas-theme', theme);
  }
  
  loadPreference() {
    return localStorage.getItem('eas-theme') || 'light';
  }
}

// Global instance
window.EASTheme = new EASThemeManager();
```

### Theme Controls
```html
<!-- Theme selector component -->
<div class="theme-selector">
  <div class="dropdown">
    <button class="btn btn-outline-secondary dropdown-toggle" 
            type="button" 
            data-bs-toggle="dropdown">
      <i class="fas fa-palette me-2"></i>
      Theme
    </button>
    <ul class="dropdown-menu">
      <li>
        <button class="dropdown-item active" data-theme="light">
          <i class="fas fa-sun me-2"></i>Light
        </button>
      </li>
      <li>
        <button class="dropdown-item" data-theme="dark">
          <i class="fas fa-moon me-2"></i>Dark
        </button>
      </li>
      <li>
        <button class="dropdown-item" data-theme="high-contrast">
          <i class="fas fa-adjust me-2"></i>High Contrast
        </button>
      </li>
      <li><hr class="dropdown-divider"></li>
      <li>
        <button class="dropdown-item" data-theme="auto">
          <i class="fas fa-desktop me-2"></i>Auto (System)
        </button>
      </li>
    </ul>
  </div>
</div>

<script>
// Theme selector functionality
document.querySelectorAll('[data-theme]').forEach(button => {
  button.addEventListener('click', (e) => {
    e.preventDefault();
    const theme = e.currentTarget.dataset.theme;
    
    if (theme === 'auto') {
      EASTheme.applySystemPreference();
    } else {
      EASTheme.setTheme(theme);
    }
    
    // Update active state
    document.querySelectorAll('[data-theme]').forEach(btn => {
      btn.classList.remove('active');
    });
    e.currentTarget.classList.add('active');
  });
});
</script>
```

---

## 🎨 Brand Customization

### Custom Brand Colors
```css
/* Override brand colors for organization */
.organization-brand {
  --color-primary-500: #1e40af;  /* Custom blue */
  --color-primary-600: #1e3a8a;
  --color-primary-700: #172554;
  
  /* Custom accent colors */
  --color-accent-500: #7c3aed;
  --color-accent-600: #6d28d9;
  --color-accent-700: #5b21b6;
  
  /* Custom status colors */
  --color-status-normal: #059669;
  --color-status-warning: #d97706;
  --color-status-critical: #dc2626;
}
```

### Logo and Typography
```css
.brand-customization {
  /* Custom logo dimensions */
  --logo-height: 32px;
  --logo-width: auto;
  
  /* Custom typography */
  --font-family-brand: 'Custom Font', system-ui, sans-serif;
  --font-family-heading: var(--font-family-brand);
  --font-weight-heading: 600;
  
  /* Custom heading sizes */
  --font-size-h1: 2.5rem;
  --font-size-h2: 2rem;
  --font-size-h3: 1.5rem;
}
```

### Component Branding
```css
.brand-customization .navbar {
  background-color: var(--color-primary-600);
  border-bottom: 3px solid var(--color-accent-500);
}

.brand-customization .btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  border: none;
}

.brand-customization .card-header {
  background-color: var(--color-primary-50);
  border-bottom: 2px solid var(--color-primary-200);
}
```

---

## 🔧 Advanced Customization

### Dynamic Color Generation
```javascript
class ColorGenerator {
  // Generate color palette from base color
  static generatePalette(baseColor) {
    const hsl = this.hexToHSL(baseColor);
    const palette = {};
    
    // Generate color ramp
    for (let i = 1; i <= 9; i++) {
      const lightness = 95 - (i * 10);
      palette[`${i * 100}`] = this.hslToHex(hsl.h, hsl.s, lightness);
    }
    
    return palette;
  }
  
  // Generate complementary colors
  static generateComplementary(baseColor) {
    const hsl = this.hexToHSL(baseColor);
    const complementary = {
      h: (hsl.h + 180) % 360,
      s: hsl.s,
      l: hsl.l
    };
    return this.hslToHex(complementary.h, complementary.s, complementary.l);
  }
  
  // Color utility methods
  static hexToHSL(hex) {
    // Convert hex to HSL
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;
    
    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
        case g: h = ((b - r) / d + 2) / 6; break;
        case b: h = ((r - g) / d + 4) / 6; break;
      }
    }
    
    return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
  }
  
  static hslToHex(h, s, l) {
    s /= 100;
    l /= 100;
    
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs((h / 60) % 2 - 1));
    const m = l - c / 2;
    let r = 0, g = 0, b = 0;
    
    if (0 <= h && h < 60) {
      r = c; g = x; b = 0;
    } else if (60 <= h && h < 120) {
      r = x; g = c; b = 0;
    } else if (120 <= h && h < 180) {
      r = 0; g = c; b = x;
    } else if (180 <= h && h < 240) {
      r = 0; g = x; b = c;
    } else if (240 <= h && h < 300) {
      r = x; g = 0; b = c;
    } else if (300 <= h && h < 360) {
      r = c; g = 0; b = x;
    }
    
    r = Math.round((r + m) * 255);
    g = Math.round((g + m) * 255);
    b = Math.round((b + m) * 255);
    
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
  }
}

// Usage: Generate custom theme
const baseColor = '#3d73cd';
const palette = ColorGenerator.generatePalette(baseColor);
EASTheme.setCustomColors(palette);
```

### Animation Customization
```css
/* Custom animation timing */
:root {
  --animation-duration-fast: 150ms;
  --animation-duration-normal: 250ms;
  --animation-duration-slow: 350ms;
  
  --animation-easing-in: cubic-bezier(0.4, 0, 1, 1);
  --animation-easing-out: cubic-bezier(0, 0, 0.2, 1);
  --animation-easing-in-out: cubic-bezier(0.4, 0, 0.2, 1);
}

/* Theme-specific animations */
[data-theme="dark"] {
  --animation-duration-normal: 200ms; /* Slightly faster in dark mode */
}

/* Reduced motion support */
@media (prefers-reduced-motion: reduce) {
  :root {
    --animation-duration-fast: 0ms;
    --animation-duration-normal: 0ms;
    --animation-duration-slow: 0ms;
  }
}
```

---

## 🎭 Special Themes

### Seasonal Themes
```css
/* Holiday theme */
[data-theme="holiday"] {
  --color-primary-500: #c41e3a;  /* Holiday red */
  --color-primary-600: #a01529;
  --color-accent-500: #0f7938;  /* Holiday green */
  
  /* Festive effects */
  --bg-pattern: url('/static/img/holiday-pattern.png');
  --sparkle-color: #ffd700;
}

/* Emergency response theme */
[data-theme="emergency"] {
  --color-primary-500: #dc2626;  /* Alert red */
  --color-warning-500: #ea580c;  /* Emergency orange */
  
  /* High visibility */
  --border-width: 3px;
  --font-weight-bold: 700;
}
```

### User Role Themes
```css
/* Administrator theme */
[data-user-role="admin"] {
  --color-primary-500: #7c3aed;  /* Admin purple */
  --color-surface: #faf5ff;      /* Light purple background */
}

/* Operator theme */
[data-user-role="operator"] {
  --color-primary-500: #0891b2;  /* Operator blue */
  --color-surface: #f0fdfa;      /* Light cyan background */
}

/* Viewer theme */
[data-user-role="viewer"] {
  --color-primary-500: #64748b;  /* Neutral gray */
  --color-surface: #f8fafc;      /* Light gray background */
}
```

---

## 📊 Theme Configuration

### Configuration API
```javascript
// Theme configuration object
const themeConfig = {
  name: 'Custom Organization Theme',
  version: '1.0.0',
  
  colors: {
    primary: '#3d73cd',
    secondary: '#64748b',
    success: '#22c55e',
    warning: '#f59e0b',
    danger: '#ef4444',
    info: '#06b6d4'
  },
  
  typography: {
    fontFamily: 'Inter, system-ui, sans-serif',
    fontSize: {
      xs: '0.75rem',
      sm: '0.875rem',
      base: '1rem',
      lg: '1.125rem',
      xl: '1.25rem'
    }
  },
  
  spacing: {
    scale: 'minor-third', // Musical scale for spacing
    base: '1rem'
  },
  
  animations: {
    enabled: true,
    duration: {
      fast: '150ms',
      normal: '250ms',
      slow: '350ms'
    }
  },
  
  features: {
    darkMode: true,
    highContrast: true,
    customColors: true,
    brandCustomization: true
  }
};

// Apply theme configuration
EASTheme.applyConfiguration(themeConfig);
```

### Theme Export/Import
```javascript
// Export current theme
const currentTheme = EASTheme.exportTheme();
localStorage.setItem('custom-theme', JSON.stringify(currentTheme));

// Import theme
const importedTheme = JSON.parse(localStorage.getItem('custom-theme'));
EASTheme.importTheme(importedTheme);

// Share theme URL
const themeURL = EASTheme.generateShareableURL(themeConfig);
console.log('Share this theme:', themeURL);
```

---

## 🧪 Theme Testing

### Contrast Ratio Testing
```javascript
class AccessibilityTester {
  static testContrast(color1, color2) {
    const rgb1 = this.hexToRGB(color1);
    const rgb2 = this.hexToRGB(color2);
    
    const l1 = this.relativeLuminance(rgb1);
    const l2 = this.relativeLuminance(rgb2);
    
    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);
    
    return (lighter + 0.05) / (darker + 0.05);
  }
  
  static relativeLuminance(rgb) {
    const [r, g, b] = rgb.map(val => {
      val = val / 255;
      return val <= 0.03928 ? val / 12.92 : Math.pow((val + 0.055) / 1.055, 2.4);
    });
    
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  
  static validateTheme(theme) {
    const issues = [];
    
    // Test primary color contrast
    const primaryContrast = this.testContrast(
      theme.colors.primary,
      theme.colors.surface
    );
    
    if (primaryContrast < 4.5) {
      issues.push('Primary color has insufficient contrast');
    }
    
    return issues;
  }
}

// Test theme during development
const themeIssues = AccessibilityTester.validateTheme(themeConfig);
if (themeIssues.length > 0) {
  console.warn('Theme accessibility issues:', themeIssues);
}
```

---

## 🚀 Performance Optimization

### CSS Optimization
```css
/* Efficient theme switching */
.theme-transition * {
  transition: 
    background-color var(--animation-duration-normal) var(--animation-easing-in-out),
    border-color var(--animation-duration-normal) var(--animation-easing-in-out),
    color var(--animation-duration-normal) var(--animation-easing-in-out);
}

/* Optimize custom property usage */
.card {
  /* Good: Use semantic variables */
  background-color: var(--color-surface-container);
  color: var(--color-on-surface-container);
  
  /* Avoid: Too many custom properties */
  /* box-shadow: var(--shadow-1), var(--shadow-2), var(--shadow-3); */
}
```

### JavaScript Optimization
```javascript
// Debounce theme switching
const debounceThemeChange = debounce((theme) => {
  EASTheme.setTheme(theme);
}, 100);

// Batch color updates
EASTheme.batchColorUpdate = function(colors) {
  requestAnimationFrame(() => {
    Object.entries(colors).forEach(([key, value]) => {
      document.documentElement.style.setProperty(`--color-${key}`, value);
    });
  });
};
```

---

This theming and customization guide provides comprehensive documentation for creating, modifying, and extending themes in EAS Station while maintaining accessibility, performance, and brand consistency.