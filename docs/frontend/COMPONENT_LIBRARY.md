# 🧩 EAS Station Component Library

## Overview

This comprehensive reference documents all UI components available in the EAS Station interface. Each component includes usage examples, customization options, and accessibility guidelines.

## 🎯 Component Categories

### Navigation Components
- [Navigation Bar](#navigation-bar)
- [Breadcrumb Trail](#breadcrumb-trail)
- [Tab Navigation](#tab-navigation)
- [Sidebar Menu](#sidebar-menu)

### Form Components
- [Input Fields](#input-fields)
- [Select Dropdowns](#select-dropdowns)
- [Checkboxes & Radio Buttons](#checkboxes--radio-buttons)
- [Text Areas](#text-areas)
- [File Upload](#file-upload)

### Display Components
- [Cards](#cards)
- [Tables](#tables)
- [Badges & Labels](#badges--labels)
- [Progress Bars](#progress-bars)
- [Status Indicators](#status-indicators)

### Action Components
- [Buttons](#buttons)
- [Button Groups](#button-groups)
- [Dropdown Menus](#dropdown-menus)
- [Modal Dialogs](#modal-dialogs)

### Data Visualization
- [Charts](#charts)
- [Maps](#maps)
- [Timelines](#timelines)

### Feedback Components
- [Alerts & Notifications](#alerts--notifications)
- [Loading States](#loading-states)
- [Tooltips](#tooltips)
- [Popovers](#popovers)

---

## Navigation Components

### Navigation Bar

The primary navigation provides access to main application areas.

```html
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container-fluid">
    <!-- Logo and Brand -->
    <a class="navbar-brand" href="/">
      <img src="/static/img/eas-station-logo.svg" alt="EAS Station" height="32">
      <span class="brand-text">EAS Station</span>
    </a>

    <!-- Mobile Toggle -->
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
      <span class="navbar-toggler-icon"></span>
    </button>

    <!-- Navigation Items -->
    <div class="collapse navbar-collapse" id="navbarNav">
      <ul class="navbar-nav me-auto">
        <li class="nav-item">
          <a class="nav-link active" href="/">
            <i class="fas fa-home me-1"></i>Dashboard
          </a>
        </li>
        <li class="nav-item dropdown">
          <a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown">
            <i class="fas fa-chart-line me-1"></i>Monitoring
          </a>
          <ul class="dropdown-menu">
            <li><a class="dropdown-item" href="/alerts">Live Alerts</a></li>
            <li><a class="dropdown-item" href="/system_health">System Health</a></li>
          </ul>
        </li>
      </ul>

      <!-- User Actions -->
      <div class="navbar-nav">
        <div class="nav-item dropdown">
          <a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown">
            <i class="fas fa-user-circle"></i>
          </a>
          <ul class="dropdown-menu dropdown-menu-end">
            <li><a class="dropdown-item" href="/profile">Profile</a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item" href="/logout">Logout</a></li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</nav>
```

**Features:**
- Responsive collapse on mobile devices
- Dropdown submenus for complex navigation
- Active state highlighting
- Icon integration for visual clarity
- Keyboard accessible navigation

**Variants:**
- `navbar-light` / `navbar-dark` - Theme variants
- `bg-primary` / `bg-secondary` - Background colors
- `navbar-expand-lg` / `navbar-expand-md` - Breakpoint control

### Breadcrumb Trail

Provides hierarchical navigation context.

```html
<nav aria-label="breadcrumb">
  <ol class="breadcrumb">
    <li class="breadcrumb-item">
      <a href="/"><i class="fas fa-home"></i></a>
    </li>
    <li class="breadcrumb-item">
      <a href="/admin">Administration</a>
    </li>
    <li class="breadcrumb-item">
      <a href="/admin/alerts">Alert Management</a>
    </li>
    <li class="breadcrumb-item active" aria-current="page">
      Edit Alert
    </li>
  </ol>
</nav>
```

**Features:**
- Semantic navigation structure
- Current page highlighting
- Collapsible on mobile devices
- Screen reader accessible

### Tab Navigation

Organizes content within a single page.

```html
<ul class="nav nav-tabs" role="tablist">
  <li class="nav-item">
    <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#overview" type="button">
      <i class="fas fa-chart-pie me-2"></i>Overview
    </button>
  </li>
  <li class="nav-item">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#details" type="button">
      <i class="fas fa-list me-2"></i>Details
    </button>
  </li>
  <li class="nav-item">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#history" type="button">
      <i class="fas fa-history me-2"></i>History
    </button>
  </li>
</ul>

<div class="tab-content">
  <div class="tab-pane fade show active" id="overview">
    <!-- Tab content -->
  </div>
  <div class="tab-pane fade" id="details">
    <!-- Tab content -->
  </div>
  <div class="tab-pane fade" id="history">
    <!-- Tab content -->
  </div>
</div>
```

---

## Form Components

### Input Fields

Standard text input with validation states.

```html
<!-- Basic Input -->
<div class="form-group mb-3">
  <label for="alertTitle" class="form-label">Alert Title</label>
  <input type="text" class="form-control" id="alertTitle" placeholder="Enter alert title">
  <div class="form-text">Max 100 characters</div>
</div>

<!-- Input with Icon -->
<div class="form-group mb-3">
  <label for="location" class="form-label">Location</label>
  <div class="input-group">
    <span class="input-group-text">
      <i class="fas fa-map-marker-alt"></i>
    </span>
    <input type="text" class="form-control" id="location" placeholder="Enter location">
  </div>
</div>

<!-- Validation States -->
<div class="form-group mb-3">
  <label for="email" class="form-label">Email Address</label>
  <input type="email" class="form-control is-valid" id="email">
  <div class="valid-feedback">Valid email address</div>
</div>

<div class="form-group mb-3">
  <label for="password" class="form-label">Password</label>
  <input type="password" class="form-control is-invalid" id="password">
  <div class="invalid-feedback">Password must be at least 8 characters</div>
</div>

<!-- Input Sizes -->
<input class="form-control form-control-lg" type="text" placeholder="Large input">
<input class="form-control" type="text" placeholder="Normal input">
<input class="form-control form-control-sm" type="text" placeholder="Small input">
```

**Features:**
- Built-in validation states
- Icon integration via input groups
- Floating label support
- Multiple size variants
- Accessibility attributes

### Select Dropdowns

```html
<!-- Standard Select -->
<div class="form-group mb-3">
  <label for="alertType" class="form-label">Alert Type</label>
  <select class="form-select" id="alertType">
    <option selected>Choose alert type...</option>
    <option value="tor">Tornado Warning</option>
    <option value="sev">Severe Thunderstorm</option>
    <option value="flood">Flood Warning</option>
  </select>
</div>

<!-- Multi-Select -->
<div class="form-group mb-3">
  <label for="counties" class="form-label">Affected Counties</label>
  <select class="form-select" id="counties" multiple size="4">
    <option value="001">Adams County</option>
    <option value="003">Alexander County</option>
    <option value="005">Bond County</option>
  </select>
  <div class="form-text">Hold Ctrl/Cmd to select multiple</div>
</div>

<!-- Select with Search -->
<div class="form-group mb-3">
  <label for="searchable" class="form-label">Searchable Select</label>
  <select class="form-select" id="searchable" data-bs-toggle="select2">
    <!-- Options populated via JavaScript -->
  </select>
</div>
```

### Checkboxes & Radio Buttons

```html
<!-- Checkboxes -->
<div class="form-check">
  <input class="form-check-input" type="checkbox" value="" id="enabled">
  <label class="form-check-label" for="enabled">
    Enable automatic alerts
  </label>
</div>

<div class="form-check">
  <input class="form-check-input" type="checkbox" value="" id="notifications" checked>
  <label class="form-check-label" for="notifications">
    Send email notifications
  </label>
</div>

<!-- Inline Checkboxes -->
<div class="form-check form-check-inline">
  <input class="form-check-input" type="checkbox" id="monday">
  <label class="form-check-label" for="monday">Mon</label>
</div>
<div class="form-check form-check-inline">
  <input class="form-check-input" type="checkbox" id="tuesday">
  <label class="form-check-label" for="tuesday">Tue</label>
</div>

<!-- Radio Buttons -->
<div class="form-check">
  <input class="form-check-input" type="radio" name="priority" id="high" value="high">
  <label class="form-check-label" for="high">
    High Priority
  </label>
</div>
<div class="form-check">
  <input class="form-check-input" type="radio" name="priority" id="normal" value="normal" checked>
  <label class="form-check-label" for="normal">
    Normal Priority
  </label>
</div>
```

### File Upload

```html
<!-- Basic File Upload -->
<div class="form-group mb-3">
  <label for="audioFile" class="form-label">Upload Audio File</label>
  <input type="file" class="form-control" id="audioFile" accept="audio/*">
  <div class="form-text">Supported formats: MP3, WAV, M4A</div>
</div>

<!-- Advanced Upload with Preview -->
<div class="file-upload-area" id="dropZone">
  <div class="upload-content">
    <i class="fas fa-cloud-upload-alt fa-3x text-muted mb-3"></i>
    <p class="text-muted">Drag and drop files here or click to browse</p>
    <button type="button" class="btn btn-outline-primary">Choose Files</button>
  </div>
  <div class="upload-progress d-none">
    <div class="progress">
      <div class="progress-bar" role="progressbar" style="width: 0%"></div>
    </div>
  </div>
</div>
```

---

## Display Components

### Cards

Flexible content containers for grouping related information.

```html
<!-- Basic Card -->
<div class="card">
  <div class="card-header">
    <h5 class="card-title mb-0">System Status</h5>
  </div>
  <div class="card-body">
    <p class="card-text">All systems are operational.</p>
    <a href="#" class="btn btn-primary">View Details</a>
  </div>
</div>

<!-- Card with Image -->
<div class="card mb-3">
  <img src="path/to/image.jpg" class="card-img-top" alt="Card image">
  <div class="card-body">
    <h5 class="card-title">Alert Statistics</h5>
    <p class="card-text">Current alert activity overview.</p>
  </div>
  <div class="card-footer text-muted">
    Last updated 5 minutes ago
  </div>
</div>

<!-- Status Card -->
<div class="card border-success">
  <div class="card-header bg-success text-white">
    <i class="fas fa-check-circle me-2"></i>System Healthy
  </div>
  <div class="card-body">
    <div class="row">
      <div class="col-6">
        <div class="d-flex align-items-center">
          <i class="fas fa-server fa-2x text-success me-3"></i>
          <div>
            <div class="h4 mb-0">12</div>
            <small class="text-muted">Active Receivers</small>
          </div>
        </div>
      </div>
      <div class="col-6">
        <div class="d-flex align-items-center">
          <i class="fas fa-broadcast-tower fa-2x text-info me-3"></i>
          <div>
            <div class="h4 mb-0">98%</div>
            <small class="text-muted">Signal Quality</small>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

**Card Variants:**
- Color borders: `border-primary`, `border-success`, `border-warning`, `border-danger`
- Background colors: `bg-light`, `bg-dark`, `.text-white`
- Header styles: `card-header` with custom backgrounds
- Footer support: `card-footer` for metadata

### Tables

Data display with sorting, filtering, and pagination.

```html
<!-- Basic Table -->
<div class="table-responsive">
  <table class="table table-striped">
    <thead>
      <tr>
        <th scope="col">Alert ID</th>
        <th scope="col">Type</th>
        <th scope="col">Status</th>
        <th scope="col">Received</th>
        <th scope="col">Actions</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>2025-001</td>
        <td>Tornado Warning</td>
        <td><span class="badge bg-danger">Active</span></td>
        <td>2 minutes ago</td>
        <td>
          <button class="btn btn-sm btn-outline-primary">View</button>
        </td>
      </tr>
    </tbody>
  </table>
</div>

<!-- Interactive Table with Controls -->
<div class="card">
  <div class="card-header">
    <div class="row align-items-center">
      <div class="col">
        <h5 class="card-title mb-0">Alert History</h5>
      </div>
      <div class="col-auto">
        <div class="btn-group" role="group">
          <button class="btn btn-outline-secondary" type="button">
            <i class="fas fa-download"></i> Export
          </button>
          <button class="btn btn-outline-secondary" type="button">
            <i class="fas fa-sync"></i> Refresh
          </button>
        </div>
      </div>
    </div>
  </div>
  <div class="card-body">
    <!-- Search and Filter -->
    <div class="row mb-3">
      <div class="col-md-6">
        <input type="search" class="form-control" placeholder="Search alerts...">
      </div>
      <div class="col-md-3">
        <select class="form-select">
          <option>All Types</option>
          <option>Tornado</option>
          <option>Severe Storm</option>
        </select>
      </div>
      <div class="col-md-3">
        <select class="form-select">
          <option>All Status</option>
          <option>Active</option>
          <option>Expired</option>
        </select>
      </div>
    </div>

    <!-- Table -->
    <div class="table-responsive">
      <table class="table table-hover" id="alertsTable">
        <thead class="table-light">
          <tr>
            <th class="sortable" data-sort="id">
              ID <i class="fas fa-sort ms-1"></i>
            </th>
            <th class="sortable" data-sort="type">
              Type <i class="fas fa-sort ms-1"></i>
            </th>
            <th>Location</th>
            <th>Received</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <!-- Table rows populated via JavaScript -->
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <nav aria-label="Table pagination">
      <ul class="pagination justify-content-center">
        <li class="page-item disabled">
          <a class="page-link" href="#" tabindex="-1">Previous</a>
        </li>
        <li class="page-item active"><a class="page-link" href="#">1</a></li>
        <li class="page-item"><a class="page-link" href="#">2</a></li>
        <li class="page-item"><a class="page-link" href="#">3</a></li>
        <li class="page-item">
          <a class="page-link" href="#">Next</a>
        </li>
      </ul>
    </nav>
  </div>
</div>
```

### Badges & Labels

```html
<!-- Status Badges -->
<span class="badge bg-primary">Primary</span>
<span class="badge bg-success">Active</span>
<span class="badge bg-warning">Warning</span>
<span class="badge bg-danger">Critical</span>
<span class="badge bg-info">Info</span>
<span class="badge bg-secondary">Inactive</span>

<!-- Pill Badges -->
<span class="badge rounded-pill bg-primary">Primary Pill</span>
<span class="badge rounded-pill bg-success">Active Pill</span>

<!-- Badges with Icons -->
<span class="badge bg-success">
  <i class="fas fa-check me-1"></i>Online
</span>
<span class="badge bg-danger">
  <i class="fas fa-exclamation-triangle me-1"></i>Error
</span>

<!-- Count Badges -->
<button class="btn btn-primary position-relative">
  Notifications
  <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger">
    5
    <span class="visually-hidden">unread notifications</span>
  </span>
</button>
```

### Progress Bars

```html
<!-- Basic Progress Bar -->
<div class="progress mb-3">
  <div class="progress-bar" role="progressbar" style="width: 75%" aria-valuenow="75" aria-valuemin="0" aria-valuemax="100">75%</div>
</div>

<!-- Colored Progress Bars -->
<div class="progress mb-2">
  <div class="progress-bar bg-success" style="width: 25%">Success</div>
</div>
<div class="progress mb-2">
  <div class="progress-bar bg-warning" style="width: 50%">Warning</div>
</div>
<div class="progress mb-2">
  <div class="progress-bar bg-danger" style="width: 75%">Danger</div>
</div>

<!-- Striped Progress Bar -->
<div class="progress">
  <div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 45%"></div>
</div>

<!-- Stacked Progress Bar -->
<div class="progress">
  <div class="progress-bar" style="width: 15%">Completed</div>
  <div class="progress-bar bg-warning" style="width: 30%">In Progress</div>
  <div class="progress-bar bg-danger" style="width: 20%">Failed</div>
</div>

<!-- Progress with Label -->
<div class="d-flex justify-content-between mb-1">
  <span>System Resources</span>
  <span>67%</span>
</div>
<div class="progress" style="height: 8px;">
  <div class="progress-bar" role="progressbar" style="width: 67%"></div>
</div>
```

---

## Action Components

### Buttons

Primary action elements with multiple variants and states.

```html
<!-- Button Variants -->
<button type="button" class="btn btn-primary">Primary</button>
<button type="button" class="btn btn-secondary">Secondary</button>
<button type="button" class="btn btn-success">Success</button>
<button type="button" class="btn btn-danger">Danger</button>
<button type="button" class="btn btn-warning">Warning</button>
<button type="button" class="btn btn-info">Info</button>
<button type="button" class="btn btn-light">Light</button>
<button type="button" class="btn btn-dark">Dark</button>

<!-- Outline Buttons -->
<button type="button" class="btn btn-outline-primary">Primary</button>
<button type="button" class="btn btn-outline-secondary">Secondary</button>
<button type="button" class="btn btn-outline-success">Success</button>

<!-- Button Sizes -->
<button type="button" class="btn btn-primary btn-lg">Large button</button>
<button type="button" class="btn btn-primary">Default button</button>
<button type="button" class="btn btn-primary btn-sm">Small button</button>

<!-- Buttons with Icons -->
<button type="button" class="btn btn-primary">
  <i class="fas fa-save me-2"></i>Save Changes
</button>
<button type="button" class="btn btn-danger">
  <i class="fas fa-trash me-2"></i>Delete
</button>

<!-- Icon Only Buttons -->
<button type="button" class="btn btn-outline-secondary">
  <i class="fas fa-edit"></i>
</button>
<button type="button" class="btn btn-outline-primary">
  <i class="fas fa-download"></i>
</button>

<!-- Loading Button -->
<button type="button" class="btn btn-primary" disabled>
  <span class="spinner-border spinner-border-sm me-2" role="status"></span>
  Loading...
</button>

<!-- Dropdown Buttons -->
<div class="btn-group">
  <button type="button" class="btn btn-primary">Action</button>
  <button type="button" class="btn btn-primary dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown">
    <span class="visually-hidden">Toggle Dropdown</span>
  </button>
  <ul class="dropdown-menu">
    <li><a class="dropdown-item" href="#">Action 1</a></li>
    <li><a class="dropdown-item" href="#">Action 2</a></li>
  </ul>
</div>
```

### Modal Dialogs

Overlays for user interaction and confirmation.

```html
<!-- Basic Modal -->
<div class="modal fade" id="exampleModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Modal Title</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <p>Modal content goes here.</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
        <button type="button" class="btn btn-primary">Save changes</button>
      </div>
    </div>
  </div>
</div>

<!-- Confirmation Modal -->
<div class="modal fade" id="deleteModal" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header bg-danger text-white">
        <h5 class="modal-title">
          <i class="fas fa-exclamation-triangle me-2"></i>Confirm Deletion
        </h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <p>Are you sure you want to delete this alert?</p>
        <p class="text-muted">This action cannot be undone.</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-danger">Delete Alert</button>
      </div>
    </div>
  </div>
</div>

<!-- Large Modal -->
<div class="modal fade" id="largeModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Large Modal</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="row">
          <div class="col-md-6">
            <!-- Left column content -->
          </div>
          <div class="col-md-6">
            <!-- Right column content -->
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

---

## Data Visualization

### Charts

```html
<!-- Chart Container -->
<div class="card">
  <div class="card-header">
    <h5 class="card-title">Alert Trends</h5>
    <div class="card-actions">
      <div class="btn-group btn-group-sm">
        <button class="btn btn-outline-secondary active" data-range="24h">24h</button>
        <button class="btn btn-outline-secondary" data-range="7d">7d</button>
        <button class="btn btn-outline-secondary" data-range="30d">30d</button>
      </div>
    </div>
  </div>
  <div class="card-body">
    <div id="alertChart" style="height: 300px;"></div>
  </div>
</div>

<!-- JavaScript Chart Initialization -->
<script>
Highcharts.chart('alertChart', {
  chart: { type: 'line' },
  title: { text: null },
  xAxis: {
    type: 'datetime',
    categories: ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']
  },
  yAxis: {
    title: { text: 'Number of Alerts' }
  },
  series: [{
    name: 'Alerts',
    data: [2, 5, 3, 8, 4, 6],
    color: '#3d73cd'
  }]
});
</script>
```

### Maps

```html
<!-- Interactive Map Container -->
<div class="card">
  <div class="card-header">
    <h5 class="card-title">Alert Coverage</h5>
    <div class="card-actions">
      <button class="btn btn-sm btn-outline-primary" id="resetMap">
        <i class="fas fa-sync me-1"></i>Reset View
      </button>
    </div>
  </div>
  <div class="card-body p-0">
    <div id="alertMap" style="height: 400px;"></div>
  </div>
</div>

<!-- Map JavaScript -->
<script>
// Initialize Leaflet map
const map = L.map('alertMap').setView([39.8283, -98.5795], 4);

// Add tile layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors'
}).addTo(map);

// Add alert markers
const alerts = [
  { lat: 41.8781, lng: -87.6298, type: 'torwarning' },
  { lat: 39.7392, lng: -104.9903, type: 'sevthunder' }
];

alerts.forEach(alert => {
  const marker = L.marker([alert.lat, alert.lng]).addTo(map);
  marker.bindPopup(`Alert Type: ${alert.type}`);
});
</script>
```

---

## Feedback Components

### Alerts & Notifications

```html
<!-- Success Alert -->
<div class="alert alert-success alert-dismissible fade show" role="alert">
  <i class="fas fa-check-circle me-2"></i>
  <strong>Success!</strong> Alert configuration saved successfully.
  <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
</div>

<!-- Warning Alert -->
<div class="alert alert-warning alert-dismissible fade show" role="alert">
  <i class="fas fa-exclamation-triangle me-2"></i>
  <strong>Warning:</strong> Receiver signal strength is below optimal levels.
  <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
</div>

<!-- Error Alert -->
<div class="alert alert-danger alert-dismissible fade show" role="alert">
  <i class="fas fa-times-circle me-2"></i>
  <strong>Error:</strong> Unable to connect to alert service.
  <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
</div>

<!-- Info Alert -->
<div class="alert alert-info alert-dismissible fade show" role="alert">
  <i class="fas fa-info-circle me-2"></i>
  <strong>Info:</strong> System maintenance scheduled for 2:00 AM.
  <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
</div>

<!-- Inline Alert -->
<div class="alert alert-secondary mb-3">
  <i class="fas fa-lightbulb me-2"></i>
  <strong>Tip:</strong> You can drag alerts to reorder them.
</div>
```

### Loading States

```html
<!-- Page Loading Spinner -->
<div class="d-flex justify-content-center align-items-center" style="height: 200px;">
  <div class="spinner-border text-primary" role="status">
    <span class="visually-hidden">Loading...</span>
  </div>
</div>

<!-- Card Loading State -->
<div class="card">
  <div class="card-body text-center py-5">
    <div class="spinner-border text-muted mb-3" role="status"></div>
    <p class="text-muted mb-0">Loading alert data...</p>
  </div>
</div>

<!-- Progress Loading -->
<div class="mb-3">
  <div class="d-flex justify-content-between mb-1">
    <span>Processing alerts...</span>
    <span>45%</span>
  </div>
  <div class="progress" style="height: 8px;">
    <div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 45%"></div>
  </div>
</div>

<!-- Skeleton Loading -->
<div class="skeleton-loader">
  <div class="skeleton-item skeleton-header"></div>
  <div class="skeleton-item skeleton-text"></div>
  <div class="skeleton-item skeleton-text short"></div>
  <div class="skeleton-item skeleton-text"></div>
</div>
```

---

## Accessibility Guidelines

### ARIA Labels
Always include appropriate ARIA labels for screen readers:

```html
<!-- Accessible Button -->
<button type="button" class="btn btn-primary" aria-label="Generate new alert">
  <i class="fas fa-bolt"></i>
</button>

<!-- Accessible Form -->
<form role="form" aria-labelledby="alertFormTitle">
  <h3 id="alertFormTitle">Create Alert</h3>
  
  <div class="form-group">
    <label for="alertType">Alert Type</label>
    <select id="alertType" aria-required="true" aria-describedby="typeHelp">
      <!-- Options -->
    </select>
    <div id="typeHelp" class="form-text">Select the type of alert to generate</div>
  </div>
</form>
```

### Keyboard Navigation
Ensure all interactive elements are keyboard accessible:

```html
<!-- Focusable Elements -->
<button type="button" class="btn" tabindex="0">Button</button>
<a href="#" tabindex="0">Link</a>

<!-- Focus Management in Modals -->
<div class="modal" tabindex="-1">
  <div class="modal-dialog">
    <!-- Modal content -->
  </div>
</div>
```

### Color Contrast
Maintain WCAG AA contrast ratios (4.5:1 for normal text):

```css
/* Ensure sufficient contrast */
.text-important {
  color: #1a1a1a; /* Against white background */
}

.bg-dark .text-light {
  color: #ffffff; /* Against dark background */
}
```

---

## Responsive Design

### Mobile-First Components
All components are designed to work on mobile first, then enhanced for larger screens:

```html
<!-- Responsive Card Grid -->
<div class="row g-3">
  <div class="col-12 col-md-6 col-lg-4">
    <div class="card h-100">
      <!-- Card content -->
    </div>
  </div>
  <div class="col-12 col-md-6 col-lg-4">
    <div class="card h-100">
      <!-- Card content -->
    </div>
  </div>
</div>

<!-- Responsive Table -->
<div class="table-responsive">
  <table class="table table-striped table-sm">
    <!-- Table content -->
  </table>
</div>
```

### Touch-Friendly Interactions
Minimum 44px touch targets for mobile devices:

```css
.btn-touch {
  min-height: 44px;
  min-width: 44px;
  padding: 12px 16px;
}

.form-control-touch {
  min-height: 44px;
  font-size: 16px; /* Prevents zoom on iOS */
}
```

---

This component library provides comprehensive documentation for all UI elements used in the EAS Station interface. Each component is designed with accessibility, responsiveness, and usability in mind.