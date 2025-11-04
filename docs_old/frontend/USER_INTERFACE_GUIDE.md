# 🖥️ EAS Station User Interface Guide

## Overview

EAS Station features a modern, responsive web interface built with Bootstrap 5, custom CSS architecture, and comprehensive JavaScript modules. This guide covers all UI components, navigation, interactions, and customization options.

## 🎨 Design System

### Color Palette
The interface uses a sophisticated color system with semantic meaning:

```css
/* Primary Brand (Emergency Alert Theme) */
--color-primary-500: #3d73cd  /* Main action buttons */
--color-primary-600: #376bc8  /* Hover states */

/* Status Colors */
--color-success-500: #22c55e  /* Active systems */
--color-warning-500: #f59e0b  /* Attention needed */
--color-danger-500: #ef4444   /* Critical alerts */
--color-info-500: #06b6d4     /* Information */

/* Dark Theme Support */
--color-surface-dark: #1a1a1a
--color-surface-light: #ffffff
```

### Typography
- **Headings**: Inter font family, progressive font weights
- **Body**: System font stack for optimal readability
- **Monospace**: SF Mono, Consolas for technical data
- **Responsive**: Scales from 14px mobile to 16px desktop

### Component Architecture
- **Bootstrap 5** foundation with custom extensions
- **CSS Custom Properties** for theming
- **Component-based** structure for maintainability
- **Accessibility-first** design principles

## 🧭 Navigation Structure

### Primary Navigation
```
🏠 Dashboard    📊 Monitoring    ⚙️ Settings    👥 Admin    📋 Help
```

### Secondary Navigation Areas
- **User Menu**: Profile, preferences, logout
- **Quick Actions**: Alert generation, system refresh
- **Breadcrumbs**: Hierarchical navigation context
- **Tab Navigation**: Organized by functional areas

### Responsive Navigation
- **Desktop**: Horizontal navigation bar
- **Tablet**: Collapsible hamburger menu
- **Mobile**: Bottom navigation drawer
- **Touch**: Optimized tap targets (44px minimum)

## 📱 Page Templates & Layouts

### Base Template (`base_new.html`)
- **Semantic HTML5** structure
- **SEO optimization** with meta tags
- **Progressive enhancement** support
- **CSRF protection** embedded
- **Theme switching** capability

### Page Categories

#### Dashboard Pages
- **Main Dashboard** (`index.html`) - System overview
- **Alert Monitoring** (`alerts.html`) - Live alert feed
- **System Health** (`system_health.html`) - Status monitoring

#### Configuration Pages
- **Admin Panel** (`admin.html`) - Full system administration
- **Radio Settings** (`settings/radio/`) - Receiver configuration
- **User Management** (`admin/users/`) - Access control

#### Operational Pages
- **LED Control** (`led_control.html`) - Sign management
- **Alert Generation** (`manual_eas/`) - Test alert creation
- **Verification** (`alert_verification.html`) - Compliance checking

#### Information Pages
- **Help System** (`help.html`) - Comprehensive documentation
- **About** (`about.html`) - System information
- **Setup Wizard** (`setup_wizard.html`) - Initial configuration

## 🎛️ UI Components

### Forms & Input Elements

#### Standard Forms
```html
<form class="eas-form">
  <div class="form-group mb-3">
    <label class="form-label">Field Label</label>
    <input type="text" class="form-control" placeholder="Enter value">
    <div class="form-text">Helper text</div>
  </div>
</form>
```

#### Validation States
- **Success**: Green border with checkmark icon
- **Error**: Red border with error message
- **Warning**: Yellow border with warning icon
- **Loading**: Spinner animation during validation

#### Specialized Inputs
- **Location Picker**: Interactive map with geocoding
- **Time Range Picker**: Dual calendar selection
- **Alert Composer**: Rich text with SAME code preview
- **Receiver Selector**: Hardware detection and configuration

### Buttons & Actions

#### Button Variants
```html
<button class="btn btn-primary">Primary Action</button>
<button class="btn btn-success">Success Action</button>
<button class="btn btn-warning">Warning Action</button>
<button class="btn btn-danger">Danger Action</button>
<button class="btn btn-outline-secondary">Secondary</button>
```

#### Icon Integration
```html
<button class="btn btn-primary">
  <i class="fas fa-bolt me-2"></i>Generate Alert
</button>
```

#### Loading States
- **Spinner Button**: Shows loading spinner during action
- **Progress Bar**: For long-running operations
- **Disabled State**: Prevents duplicate actions

### Data Display Components

#### Cards
```html
<div class="card">
  <div class="card-header">
    <h5 class="card-title">Card Title</h5>
  </div>
  <div class="card-body">
    Card content with rich data display
  </div>
</div>
```

#### Tables
- **Responsive**: Horizontal scroll on mobile
- **Sortable**: Click column headers to sort
- **Filterable**: Real-time search functionality
- **Exportable**: CSV/PDF export options

#### Status Indicators
- **Badges**: Status, count, category labels
- **Progress Bars**: Completion percentages
- **Status Lights**: Real-time system status
- **Counters**: Dynamic number displays

### Modals & Overlays

#### Confirmation Dialogs
```html
<div class="modal fade" id="confirmModal">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Confirm Action</h5>
      </div>
      <div class="modal-body">
        Are you sure you want to proceed?
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-danger">Confirm</button>
      </div>
    </div>
  </div>
</div>
```

#### Information Modals
- **Help Content**: Contextual assistance
- **Form Validation**: Error message display
- **Media Preview**: Audio/video players
- **Configuration**: Settings panels

## 📊 Data Visualization

### Charts & Graphs
- **Highcharts Integration**: Professional charting library
- **Real-time Updates**: Live data streaming
- **Interactive Tooltips**: Detailed information on hover
- **Responsive Design**: Adapts to screen size

#### Chart Types
- **Line Charts**: Alert trends over time
- **Bar Charts**: Comparison statistics
- **Pie Charts**: Distribution analysis
- **Heat Maps**: Geographic alert density
- **Gauge Charts**: System performance metrics

### Maps & Geographic Display
- **Leaflet Integration**: Interactive mapping
- **Custom Layers**: Alert boundaries, coverage areas
- **Cluster Markers**: Efficient point display
- **Drawing Tools**: Custom boundary creation

## ⚡ Interactive Features

### Real-time Updates
- **WebSocket Integration**: Live data streaming
- **Server-Sent Events**: One-way updates
- **Polling Fallback**: Compatibility mode
- **Connection Status**: Online/offline indicators

### Drag & Drop
- **File Upload**: Audio files, boundary data
- **Component Reordering**: Dashboard customization
- **Map Drawing**: Geographic boundary creation

### Keyboard Navigation
- **Tab Order**: Logical focus progression
- **Shortcuts**: Quick access to common actions
- **Escape Key**: Cancel operations, close modals
- **Enter Key**: Form submission, confirmation

## 🌓 Theme System

### Light/Dark Mode
```css
[data-theme="light"] {
  --color-background: #ffffff;
  --color-text: #1a1a1a;
}

[data-theme="dark"] {
  --color-background: #1a1a1a;
  --color-text: #ffffff;
}
```

### Theme Persistence
- **Local Storage**: Remembers user preference
- **System Detection**: Follows OS dark mode preference
- **Auto-switching**: Time-based theme changes
- **Custom Themes**: Brand color customization

### High Contrast Mode
- **WCAG AAA Compliance**: Enhanced contrast ratios
- **Focus Indicators**: Clear keyboard navigation
- **Color Blind Support**: Alternative visual cues

## 📱 Responsive Design

### Breakpoints
```css
/* Mobile Devices */
@media (max-width: 576px) { /* Small phones */ }

/* Tablets */
@media (min-width: 577px) and (max-width: 768px) { /* Tablets */ }

/* Desktop */
@media (min-width: 769px) { /* Desktop */ }

/* Large Desktop */
@media (min-width: 1200px) { /* Large screens */ }
```

### Mobile Optimizations
- **Touch Targets**: 44px minimum tap size
- **Swipe Gestures**: Navigation, card dismissal
- **Virtual Keyboard**: Form field optimization
- **Performance**: Reduced animations on battery

## 🔧 Customization Guide

### CSS Customization
```css
/* Override primary colors */
:root {
  --color-primary-500: #your-brand-color;
  --color-primary-600: #your-brand-hover-color;
}

/* Custom component styles */
.custom-alert-card {
  border-left: 4px solid var(--color-primary-500);
}
```

### JavaScript Extensions
```javascript
// Extend core API client
EASAPI.customEndpoint = function(data) {
  return this.post('/api/custom', data);
};

// Add custom chart types
Highcharts.chart('container', {
  chart: { type: 'custom-type' }
});
```

### Template Customization
- **Component Inheritance**: Extend base templates
- **Block Override**: Replace specific template sections
- **Helper Functions**: Add custom Jinja2 filters
- **Asset Pipeline**: Custom CSS/JS inclusion

## 🧪 Testing & Debugging

### Browser DevTools Integration
- **Component Inspector**: Visual component debugging
- **Performance Monitor**: Animation and render performance
- **Network Inspector**: API request analysis
- **Console Logging**: Detailed error reporting

### Testing Tools
- **Cross-browser Testing**: Chrome, Firefox, Safari, Edge
- **Mobile Testing**: iOS Safari, Android Chrome
- **Accessibility Testing**: Screen reader compatibility
- **Performance Testing**: Page speed optimization

## 🔍 Troubleshooting

### Common Issues

#### CSS Not Loading
1. Check file paths in template includes
2. Verify Flask static file serving
3. Clear browser cache
4. Check network requests in DevTools

#### JavaScript Errors
1. Check browser console for error messages
2. Verify CSRF token is present
3. Check API endpoint responses
4. Validate data format expectations

#### Responsive Layout Issues
1. Test at different viewport sizes
2. Check Bootstrap grid usage
3. Verify custom CSS media queries
4. Test on actual mobile devices

### Debug Mode
```javascript
// Enable debug logging
window.EAS_DEBUG = true;

// API request debugging
EASAPI.get('/api/debug', { debug: true });

// Performance monitoring
console.time('component-render');
// ... component code ...
console.timeEnd('component-render');
```

## 📚 API Reference

### Core JavaScript Modules

#### API Client (`static/js/core/api.js`)
```javascript
// GET request
const alerts = await EASAPI.get('/api/alerts');

// POST request
const result = await EASAPI.post('/api/alerts', data);

// Error handling
try {
  const response = await EASAPI.get('/api/data');
} catch (error) {
  console.error('API Error:', error);
}
```

#### Theme System (`static/js/core/theme.js`)
```javascript
// Switch theme
EASTheme.setTheme('dark');

// Get current theme
const currentTheme = EASTheme.getCurrentTheme();

// Listen for theme changes
EASTheme.on('change', (theme) => {
  console.log('Theme changed to:', theme);
});
```

#### Notifications (`static/js/core/notifications.js`)
```javascript
// Show notification
EASNotifications.show('success', 'Operation completed');

// Show persistent notification
EASNotifications.show('warning', 'Attention needed', { persistent: true });

// Custom notification
EASNotifications.show('info', 'Custom message', {
  duration: 5000,
  icon: 'fas fa-info-circle'
});
```

## 🎯 Best Practices

### Performance
- **Lazy Loading**: Load components on demand
- **Code Splitting**: Separate vendor and app code
- **Image Optimization**: WebP format, responsive images
- **Cache Strategy**: Service worker for offline access

### Accessibility
- **Semantic HTML**: Proper heading hierarchy
- **ARIA Labels**: Screen reader compatibility
- **Keyboard Navigation**: Full keyboard access
- **Color Contrast**: WCAG AA compliance minimum

### Security
- **CSRF Protection**: All form submissions protected
- **XSS Prevention**: Input sanitization and output encoding
- **Content Security Policy**: Restrict resource loading
- **Authentication Checks**: Protect sensitive routes

---

This guide provides comprehensive documentation for the EAS Station user interface, covering all components, features, and customization options. For specific implementation details, refer to the individual component files and API documentation.