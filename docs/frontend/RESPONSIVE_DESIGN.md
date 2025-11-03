# 📱 EAS Station Responsive Design Guide

## Overview

EAS Station is built with a mobile-first responsive design approach, ensuring optimal user experience across all device types and screen sizes. This guide covers the responsive design system, breakpoints, and implementation patterns.

## 🎯 Design Philosophy

### Mobile-First Approach
- **Base Styles**: Mobile layouts are the default
- **Progressive Enhancement**: Enhanced for larger screens
- **Touch Optimization**: Designed for touch interaction
- **Performance**: Optimized for mobile bandwidth

### Responsive Principles
- **Fluid Grids**: Flexible layouts that adapt to screen size
- **Flexible Images**: Images that scale appropriately
- **Media Queries**: Target specific viewport ranges
- **Relative Units**: Use rem, em, % instead of fixed pixels

---

## 📏 Breakpoint System

### Breakpoint Definitions

```css
/* Extra Small Devices (Portrait Phones) */
@media (max-width: 575.98px) {
  .container { max-width: 100%; }
}

/* Small Devices (Landscape Phones) */
@media (min-width: 576px) and (max-width: 767.98px) {
  .container { max-width: 540px; }
}

/* Medium Devices (Tablets) */
@media (min-width: 768px) and (max-width: 991.98px) {
  .container { max-width: 720px; }
}

/* Large Devices (Desktops) */
@media (min-width: 992px) and (max-width: 1199.98px) {
  .container { max-width: 960px; }
}

/* Extra Large Devices (Large Desktops) */
@media (min-width: 1200px) and (max-width: 1399.98px) {
  .container { max-width: 1140px; }
}

/* XX Large Devices (Extra Large Desktops) */
@media (min-width: 1400px) {
  .container { max-width: 1320px; }
}
```

### Usage Patterns
```css
/* Mobile-first approach */
.card {
  padding: 1rem;
  margin-bottom: 1rem;
}

/* Tablet and up */
@media (min-width: 768px) {
  .card {
    padding: 1.5rem;
    margin-bottom: 0;
  }
}

/* Desktop and up */
@media (min-width: 992px) {
  .card {
    padding: 2rem;
  }
}
```

---

## 🧭 Navigation Responsive Behavior

### Desktop Navigation
```html
<!-- Horizontal navigation bar -->
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container-fluid">
    <a class="navbar-brand" href="/">
      <img src="/static/img/logo.svg" height="32" alt="EAS Station">
    </a>
    
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#mainNav">
      <span class="navbar-toggler-icon"></span>
    </button>
    
    <div class="collapse navbar-collapse" id="mainNav">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="/">Dashboard</a></li>
        <li class="nav-item"><a class="nav-link" href="/alerts">Alerts</a></li>
      </ul>
    </div>
  </div>
</nav>
```

### Mobile Navigation
```css
/* Mobile navigation styles */
@media (max-width: 991.98px) {
  .navbar-nav {
    text-align: center;
    padding: 1rem 0;
  }
  
  .nav-item {
    margin-bottom: 0.5rem;
  }
  
  .navbar-collapse {
    background: rgba(0, 0, 0, 0.95);
    backdrop-filter: blur(10px);
  }
}
```

### Bottom Navigation (Mobile)
```html
<!-- Mobile bottom navigation -->
<nav class="mobile-nav d-lg-none">
  <div class="mobile-nav-item active">
    <i class="fas fa-home"></i>
    <span>Home</span>
  </div>
  <div class="mobile-nav-item">
    <i class="fas fa-bell"></i>
    <span>Alerts</span>
  </div>
  <div class="mobile-nav-item">
    <i class="fas fa-cog"></i>
    <span>Settings</span>
  </div>
</nav>

<style>
.mobile-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: white;
  border-top: 1px solid #dee2e6;
  display: flex;
  justify-content: space-around;
  padding: 0.5rem 0;
  z-index: 1000;
}

.mobile-nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0.5rem;
  min-width: 44px;
  color: #6c757d;
  text-decoration: none;
  font-size: 0.75rem;
}

.mobile-nav-item.active {
  color: #3d73cd;
}

.mobile-nav-item i {
  font-size: 1.25rem;
  margin-bottom: 0.25rem;
}
</style>
```

---

## 📊 Responsive Data Display

### Cards Grid
```html
<!-- Responsive card grid -->
<div class="row g-3">
  <div class="col-12 col-sm-6 col-lg-4 col-xl-3">
    <div class="card h-100">
      <div class="card-body">
        <h6 class="card-title">Active Alerts</h6>
        <div class="h3 text-primary">12</div>
      </div>
    </div>
  </div>
  <div class="col-12 col-sm-6 col-lg-4 col-xl-3">
    <div class="card h-100">
      <div class="card-body">
        <h6 class="card-title">System Status</h6>
        <div class="h3 text-success">98%</div>
      </div>
    </div>
  </div>
</div>
```

### Responsive Tables
```html
<!-- Mobile-friendly table -->
<div class="table-responsive">
  <table class="table table-striped table-hover">
    <thead class="table-light">
      <tr>
        <th>ID</th>
        <th>Type</th>
        <th>Location</th>
        <th class="d-none d-md-table-cell">Received</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>001</td>
        <td>Tornado</td>
        <td>Chicago, IL</td>
        <td class="d-none d-md-table-cell">2 min ago</td>
        <td>
          <button class="btn btn-sm btn-outline-primary">View</button>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

### Card-Based Mobile Table
```html
<!-- Alternative mobile table layout -->
<div class="d-lg-none">
  <div class="card mb-3">
    <div class="card-body">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <h6 class="card-title mb-1">Alert #001</h6>
          <p class="text-muted mb-1">Tornado Warning</p>
          <small class="text-muted">Chicago, IL • 2 min ago</small>
        </div>
        <div>
          <span class="badge bg-danger">Active</span>
        </div>
      </div>
      <div class="mt-3">
        <button class="btn btn-sm btn-primary">View Details</button>
      </div>
    </div>
  </div>
</div>
```

---

## 📈 Responsive Charts & Visualizations

### Chart Container
```html
<div class="chart-container">
  <div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
      <h5 class="card-title mb-0">Alert Trends</h5>
      <div class="btn-group btn-group-sm">
        <button class="btn btn-outline-secondary active">24h</button>
        <button class="btn btn-outline-secondary">7d</button>
        <button class="btn btn-outline-secondary">30d</button>
      </div>
    </div>
    <div class="card-body p-0">
      <div id="chart-container" style="height: 300px;"></div>
    </div>
  </div>
</div>

<style>
.chart-container {
  margin-bottom: 1rem;
}

@media (max-width: 767.98px) {
  #chart-container {
    height: 250px !important;
  }
  
  .btn-group-sm .btn {
    font-size: 0.75rem;
    padding: 0.25rem 0.5rem;
  }
}

@media (max-width: 575.98px) {
  .chart-container .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }
  
  .btn-group {
    width: 100%;
  }
  
  .btn-group-sm .btn {
    flex: 1;
  }
}
</style>
```

### Responsive Map
```html
<div class="map-container">
  <div class="card">
    <div class="card-header">
      <h5 class="card-title mb-0">Alert Coverage</h5>
    </div>
    <div class="card-body p-0">
      <div id="map" style="height: 400px;"></div>
    </div>
  </div>
</div>

<style>
.map-container {
  margin-bottom: 1rem;
}

@media (max-width: 991.98px) {
  #map {
    height: 300px !important;
  }
}

@media (max-width: 767.98px) {
  #map {
    height: 250px !important;
  }
}
</style>
```

---

## 📝 Responsive Forms

### Form Layout
```html
<div class="row">
  <div class="col-12 col-md-6">
    <div class="form-group mb-3">
      <label for="alertTitle" class="form-label">Alert Title</label>
      <input type="text" class="form-control" id="alertTitle">
    </div>
  </div>
  <div class="col-12 col-md-6">
    <div class="form-group mb-3">
      <label for="alertType" class="form-label">Alert Type</label>
      <select class="form-select" id="alertType">
        <option>Select type...</option>
      </select>
    </div>
  </div>
  <div class="col-12">
    <div class="form-group mb-3">
      <label for="message" class="form-label">Message</label>
      <textarea class="form-control" id="message" rows="4"></textarea>
    </div>
  </div>
</div>
```

### Mobile-Optimized Inputs
```css
/* Mobile-friendly form inputs */
@media (max-width: 767.98px) {
  .form-control {
    font-size: 16px; /* Prevents zoom on iOS */
    min-height: 44px; /* Touch-friendly */
  }
  
  .form-select {
    font-size: 16px;
    min-height: 44px;
  }
  
  .form-label {
    font-weight: 600;
    margin-bottom: 0.5rem;
  }
}
```

### Responsive Buttons
```html
<!-- Stack buttons on mobile -->
<div class="d-flex gap-2 flex-column flex-md-row">
  <button type="button" class="btn btn-primary flex-md-grow-0 flex-grow-1">Save</button>
  <button type="button" class="btn btn-outline-secondary flex-md-grow-0 flex-grow-1">Cancel</button>
</div>

<!-- Button groups -->
<div class="btn-group flex-wrap" role="group">
  <button type="button" class="btn btn-outline-primary">Option 1</button>
  <button type="button" class="btn btn-outline-primary">Option 2</button>
  <button type="button" class="btn btn-outline-primary">Option 3</button>
</div>
```

---

## 🎛️ Responsive Components

### Dashboard Grid
```html
<div class="dashboard-grid">
  <div class="row g-3">
    <!-- Primary Stats -->
    <div class="col-12 col-lg-8">
      <div class="card">
        <div class="card-body">
          <!-- Main chart -->
        </div>
      </div>
    </div>
    
    <!-- Side Stats -->
    <div class="col-12 col-lg-4">
      <div class="row g-3">
        <div class="col-6 col-lg-12">
          <div class="card">
            <div class="card-body">
              <h6>Active Receivers</h6>
              <div class="h3">12</div>
            </div>
          </div>
        </div>
        <div class="col-6 col-lg-12">
          <div class="card">
            <div class="card-body">
              <h6>Signal Quality</h6>
              <div class="h3">98%</div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Recent Alerts -->
    <div class="col-12">
      <div class="card">
        <div class="card-body">
          <!-- Alerts table -->
        </div>
      </div>
    </div>
  </div>
</div>
```

### Responsive Modals
```html
<!-- Modal with responsive sizing -->
<div class="modal fade" id="alertModal" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Alert Details</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="row">
          <div class="col-12 col-md-8">
            <!-- Main content -->
          </div>
          <div class="col-12 col-md-4">
            <!-- Side content -->
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
@media (max-width: 767.98px) {
  .modal-dialog {
    margin: 0.5rem;
  }
  
  .modal-body {
    padding: 1rem;
  }
}
</style>
```

---

## 🖼️ Responsive Images & Media

### Responsive Images
```html
<!-- Responsive image with proper sizing -->
<img src="/static/img/alert-map.jpg" 
     class="img-fluid" 
     alt="Alert coverage map"
     loading="lazy">

<!-- Picture element for art direction -->
<picture>
  <source media="(max-width: 767.98px)" srcset="/static/img/alert-map-mobile.jpg">
  <source media="(min-width: 768px)" srcset="/static/img/alert-map-desktop.jpg">
  <img src="/static/img/alert-map-fallback.jpg" 
       class="img-fluid" 
       alt="Alert coverage map">
</picture>
```

### Video Container
```html
<!-- Responsive video container -->
<div class="ratio ratio-16x9">
  <video src="/static/video/alert-demo.mp4" 
         controls 
         poster="/static/img/video-poster.jpg">
  </video>
</div>
```

---

## 🎨 Responsive Design System

### CSS Custom Properties for Responsive Design
```css
:root {
  /* Responsive spacing scale */
  --spacing-xs: 0.25rem;   /* 4px */
  --spacing-sm: 0.5rem;    /* 8px */
  --spacing-md: 1rem;      /* 16px */
  --spacing-lg: 1.5rem;    /* 24px */
  --spacing-xl: 3rem;      /* 48px */
  
  /* Responsive font sizes */
  --font-size-xs: 0.75rem;  /* 12px */
  --font-size-sm: 0.875rem; /* 14px */
  --font-size-base: 1rem;   /* 16px */
  --font-size-lg: 1.125rem; /* 18px */
  --font-size-xl: 1.25rem;  /* 20px */
  
  /* Component sizing */
  --btn-height-sm: 2rem;
  --btn-height-md: 2.5rem;
  --btn-height-lg: 3rem;
}

@media (max-width: 767.98px) {
  :root {
    --spacing-md: 0.75rem;   /* Reduced spacing on mobile */
    --font-size-base: 0.875rem; /* Smaller base font */
  }
}
```

### Utility Classes
```html
<!-- Responsive display utilities -->
<div class="d-none d-md-block">Desktop only</div>
<div class="d-block d-md-none">Mobile only</div>
<div class="d-lg-none">Hidden on large screens</div>

<!-- Responsive flex utilities -->
<div class="flex-column flex-md-row">
  <div>Column on mobile, row on desktop</div>
</div>

<!-- Responsive text utilities -->
<h1 class="h3 h2-md h1-lg">Responsive heading</h1>
<p class="text-sm text-md text-lg">Responsive text</p>
```

---

## 🔧 JavaScript Responsive Features

### Viewport Detection
```javascript
// Breakpoint detection utility
const Responsive = {
  breakpoints: {
    xs: 575.98,
    sm: 767.98,
    md: 991.98,
    lg: 1199.98,
    xl: 1399.98
  },
  
  is(breakpoint) {
    return window.innerWidth <= this.breakpoints[breakpoint];
  },
  
  isMin(breakpoint) {
    return window.innerWidth > this.breakpoints[breakpoint];
  },
  
  current() {
    const width = window.innerWidth;
    if (width <= this.breakpoints.xs) return 'xs';
    if (width <= this.breakpoints.sm) return 'sm';
    if (width <= this.breakpoints.md) return 'md';
    if (width <= this.breakpoints.lg) return 'lg';
    if (width <= this.breakpoints.xl) return 'xl';
    return 'xxl';
  }
};

// Usage
if (Responsive.is('md')) {
  // Mobile-specific behavior
}
```

### Responsive Charts
```javascript
// Chart responsive configuration
const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: Responsive.isMin('lg'),
      position: 'top'
    }
  },
  scales: {
    x: {
      ticks: {
        maxTicksLimit: Responsive.is('md') ? 6 : 12
      }
    }
  }
};

// Update chart on resize
window.addEventListener('resize', () => {
  chart.update();
});
```

### Component Adaptation
```javascript
// Responsive component manager
class ResponsiveComponent {
  constructor(element, options = {}) {
    this.element = element;
    this.options = options;
    this.breakpoints = options.breakpoints || {};
    this.init();
  }
  
  init() {
    this.update();
    window.addEventListener('resize', this.debounce(this.update.bind(this), 250));
  }
  
  update() {
    const currentBreakpoint = Responsive.current();
    
    Object.keys(this.breakpoints).forEach(breakpoint => {
      const handler = this.breakpoints[breakpoint];
      
      if (currentBreakpoint === breakpoint) {
        handler.call(this, currentBreakpoint);
      }
    });
  }
  
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
}

// Usage
const responsiveTable = new ResponsiveComponent('#dataTable', {
  breakpoints: {
    xs: () => {
      // Mobile layout
      this.element.classList.add('mobile-view');
    },
    md: () => {
      // Desktop layout
      this.element.classList.remove('mobile-view');
    }
  }
});
```

---

## 🧪 Testing Responsive Design

### Browser DevTools
1. **Device Simulation**: Chrome/Firefox responsive design mode
2. **Network Throttling**: Test on slow connections
3. **Touch Events**: Simulate touch interactions
4. **Orientation Changes**: Test portrait/landscape

### Testing Checklist
- [ ] Navigation works on all screen sizes
- [ ] Forms are usable on mobile devices
- [ ] Tables adapt to small screens
- [ ] Charts are readable on mobile
- [ ] Touch targets are at least 44px
- [ ] No horizontal scrolling on mobile
- [ ] Text remains readable at all sizes
- [ ] Interactive elements are accessible

### Automated Testing
```javascript
// Responsive testing utilities
const ResponsiveTests = {
  testBreakpoints() {
    const sizes = [
      { width: 375, name: 'iPhone SE' },
      { width: 768, name: 'iPad' },
      { width: 1024, name: 'iPad Pro' },
      { width: 1920, name: 'Desktop' }
    ];
    
    sizes.forEach(size => {
      cy.viewport(size.width, 667);
      cy.get('.navbar').should('be.visible');
      cy.get('.main-content').should('not.have.css', 'overflow-x', 'auto');
    });
  },
  
  testTouchTargets() {
    cy.get('button, a, input, select').each(($el) => {
      const height = $el.innerHeight();
      const width = $el.innerWidth();
      expect(height).to.be.at.least(44);
      expect(width).to.be.at.least(44);
    });
  }
};
```

---

## 📊 Performance Optimization

### Responsive Images
```html
<!-- Lazy loading with proper sizing -->
<img src="/static/img/placeholder.jpg" 
     data-src="/static/img/alert-map.jpg" 
     class="lazyload img-fluid" 
     alt="Alert coverage map"
     loading="lazy">
```

### CSS Optimization
```css
/* Efficient media queries */
/* Use min-width for mobile-first */
@media (min-width: 768px) {
  .component {
    /* Enhanced styles */
  }
}

/* Avoid overly specific media queries */
@media (min-width: 768px) and (max-width: 1023px) {
  /* Use broader ranges when possible */
}
```

### JavaScript Optimization
```javascript
// Debounce resize events
const debounceResize = debounce(() => {
  updateLayout();
}, 250);

window.addEventListener('resize', debounceResize);

// Use ResizeObserver for component-specific changes
const resizeObserver = new ResizeObserver(entries => {
  entries.forEach(entry => {
    if (entry.contentRect.width < 768) {
      // Mobile layout
    }
  });
});

resizeObserver.observe(document.querySelector('.responsive-component'));
```

---

## ♿ Accessibility in Responsive Design

### Touch Accessibility
- Minimum 44px touch targets
- Adequate spacing between interactive elements
- Clear visual feedback for touch states

### Screen Reader Support
```html
<!-- Responsive navigation with accessibility -->
<nav class="navbar" role="navigation" aria-label="Main navigation">
  <button class="navbar-toggler" 
          type="button" 
          aria-expanded="false" 
          aria-controls="mainNav"
          aria-label="Toggle navigation">
    <span class="navbar-toggler-icon"></span>
  </button>
</nav>
```

### Focus Management
```css
/* Ensure focus indicators are visible on all screen sizes */
@media (hover: none) {
  /* Touch devices */
  .btn:focus {
    outline: 3px solid #3d73cd;
    outline-offset: 2px;
  }
}

@media (hover: hover) {
  /* Devices with mouse */
  .btn:hover {
    background-color: var(--color-primary-600);
  }
}
```

---

This responsive design guide ensures that EAS Station provides an optimal user experience across all devices, from mobile phones to large desktop displays, while maintaining accessibility and performance standards.