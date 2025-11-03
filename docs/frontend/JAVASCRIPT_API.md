# 🚀 EAS Station JavaScript API Reference

## Overview

The EAS Station frontend includes a comprehensive JavaScript API for interacting with backend services, managing UI state, and handling real-time updates. This document provides complete reference documentation for all available APIs and modules.

## 📋 Table of Contents

- [Core Modules](#core-modules)
- [API Client](#api-client)
- [Real-time Updates](#real-time-updates)
- [UI Components API](#ui-components-api)
- [Data Visualization](#data-visualization)
- [Utility Functions](#utility-functions)
- [Event System](#event-system)

---

## Core Modules

### API Client (`EASAPI`)

The primary interface for backend communication with automatic CSRF protection and error handling.

#### Initialization
```javascript
// API client is automatically initialized with CSRF token
// Available globally as window.EASAPI
```

#### Basic Usage
```javascript
// GET request
const alerts = await EASAPI.get('/api/alerts');
console.log(alerts.data);

// POST request
const newAlert = await EASAPI.post('/api/alerts', {
  type: 'torwarning',
  areas: ['039095']
});

// PUT request (update)
const updated = await EASAPI.put('/api/alerts/123', {
  status: 'acknowledged'
});

// DELETE request
await EASAPI.delete('/api/alerts/123');
```

#### Advanced Usage
```javascript
// Request with custom headers
const response = await EASAPI.get('/api/sensitive', {
  headers: {
    'X-Custom-Header': 'value'
  }
});

// Request with timeout
const data = await EASAPI.get('/api/slow-endpoint', {
  timeout: 10000 // 10 seconds
});

// File upload
const formData = new FormData();
formData.append('file', fileInput.files[0]);
const upload = await EASAPI.post('/api/upload', formData, {
  headers: {
    'Content-Type': 'multipart/form-data'
  }
});

// Query parameters
const filtered = await EASAPI.get('/api/alerts', {
  params: {
    status: 'active',
    limit: 50
  }
});
```

#### Error Handling
```javascript
try {
  const data = await EASAPI.get('/api/endpoint');
} catch (error) {
  if (error.response) {
    // Server responded with error status
    console.error('Server error:', error.response.status);
    console.error('Error data:', error.response.data);
  } else if (error.request) {
    // Network error
    console.error('Network error:', error.message);
  } else {
    // Other error
    console.error('Error:', error.message);
  }
}

// Global error handling
EASAPI.on('error', (error) => {
  console.error('API Error:', error);
  // Show user notification
  EASNotifications.show('error', 'Request failed');
});
```

#### Response Interceptors
```javascript
// Add request interceptor
EASAPI.interceptors.request.use((config) => {
  console.log('Making request to:', config.url);
  return config;
});

// Add response interceptor
EASAPI.interceptors.response.use(
  (response) => {
    console.log('Received response:', response.status);
    return response;
  },
  (error) => {
    console.error('Response error:', error);
    return Promise.reject(error);
  }
);
```

### Theme System (`EASTheme`)

Manages application themes, color schemes, and visual preferences.

#### Basic Usage
```javascript
// Set theme
EASTheme.setTheme('dark');
EASTheme.setTheme('light');
EASTheme.setTheme('auto'); // Follows system preference

// Get current theme
const currentTheme = EASTheme.getCurrentTheme();

// Toggle theme
EASTheme.toggle();
```

#### Advanced Configuration
```javascript
// Custom theme colors
EASTheme.setCustomColors({
  primary: '#3d73cd',
  success: '#22c55e',
  warning: '#f59e0b',
  danger: '#ef4444'
});

// Theme persistence
EASTheme.setPersistence('localStorage'); // Default
EASTheme.setPersistence('sessionStorage');
EASTheme.setPersistence(false); // No persistence

// Auto-switching based on time
EASTheme.enableAutoSwitch({
  darkStart: '20:00', // 8 PM
  darkEnd: '06:00'   // 6 AM
});
```

#### Event Handling
```javascript
// Listen for theme changes
EASTheme.on('change', (newTheme) => {
  console.log('Theme changed to:', newTheme);
  // Update custom components
  updateCustomComponents(newTheme);
});

// Listen for custom color changes
EASTheme.on('colorsChanged', (colors) => {
  console.log('Colors updated:', colors);
});
```

### Notifications (`EASNotifications`)

User notification system with multiple types and persistence options.

#### Basic Notifications
```javascript
// Simple notification
EASNotifications.show('success', 'Operation completed successfully');
EASNotifications.show('error', 'An error occurred');
EASNotifications.show('warning', 'Warning: Low disk space');
EASNotifications.show('info', 'System update available');

// Notification with options
EASNotifications.show('success', 'Alert saved', {
  duration: 5000,        // Auto-dismiss after 5 seconds
  persistent: false,     // Don't persist across page loads
  icon: 'fas fa-check',  // Custom icon
  actions: [             // Action buttons
    {
      text: 'View',
      callback: () => showAlertDetails()
    }
  ]
});
```

#### Advanced Features
```javascript
// Progress notification
EASNotifications.showProgress('Processing alerts...', {
  current: 25,
  total: 100,
  onComplete: () => {
    EASNotifications.show('success', 'Processing complete!');
  }
});

// Update progress notification
EASNotifications.updateProgress('notification-id', {
  current: 50,
  total: 100
});

// Dismiss specific notification
EASNotifications.dismiss('notification-id');

// Clear all notifications
EASNotifications.clearAll();
```

#### Configuration
```javascript
// Global notification settings
EASNotifications.configure({
  position: 'top-right',  // Position on screen
  maxVisible: 5,          // Maximum simultaneous notifications
  duration: 4000,         // Default auto-dismiss time
  showProgress: true,     // Show progress bar for notifications
  enableSound: false      // Disable notification sounds
});

// Notification types configuration
EASNotifications.setConfig('success', {
  icon: 'fas fa-check-circle',
  duration: 3000
});

EASNotifications.setConfig('error', {
  icon: 'fas fa-exclamation-circle',
  persistent: true
});
```

---

## Real-time Updates

### WebSocket Connection (`EASWebSocket`)

Handles real-time communication with the server for live updates.

#### Connection Management
```javascript
// Initialize WebSocket
const ws = new EASWebSocket({
  url: 'ws://localhost:5000/ws',
  reconnect: true,
  reconnectInterval: 5000,
  maxReconnectAttempts: 10
});

// Connect to server
ws.connect();

// Disconnect
ws.disconnect();

// Check connection status
if (ws.isConnected()) {
  console.log('WebSocket is connected');
}
```

#### Event Handling
```javascript
// Listen for connection events
ws.on('connect', () => {
  console.log('Connected to server');
});

ws.on('disconnect', () => {
  console.log('Disconnected from server');
});

ws.on('error', (error) => {
  console.error('WebSocket error:', error);
});

// Listen for server messages
ws.on('message', (data) => {
  console.log('Received message:', data);
  handleServerMessage(data);
});

// Listen for specific message types
ws.on('alert:new', (alertData) => {
  showNewAlert(alertData);
});

ws.on('system:status', (statusData) => {
  updateSystemStatus(statusData);
});
```

#### Sending Messages
```javascript
// Send message to server
ws.send({
  type: 'subscribe',
  channel: 'alerts'
});

// Send with acknowledgment
ws.sendWithAck({
  type: 'action',
  action: 'refresh'
}).then((response) => {
  console.log('Server response:', response);
});
```

### Server-Sent Events (`EASSSE`)

Alternative to WebSockets for one-way server updates.

#### Basic Usage
```javascript
// Initialize SSE connection
const sse = new EASSSE('/api/events');

// Start listening
sse.start();

// Stop listening
sse.stop();

// Event handlers
sse.on('alert', (event) => {
  console.log('New alert:', event.data);
});

sse.on('system_update', (event) => {
  console.log('System update:', event.data);
});

sse.on('error', (error) => {
  console.error('SSE error:', error);
});
```

---

## UI Components API

### Modal Manager (`EASModal`)

Enhanced modal management with programmatic control.

```javascript
// Create modal programmatically
const modal = EASModal.create({
  title: 'Confirm Action',
  body: 'Are you sure you want to delete this alert?',
  buttons: [
    {
      text: 'Cancel',
      class: 'btn-secondary',
      callback: (modal) => modal.hide()
    },
    {
      text: 'Delete',
      class: 'btn-danger',
      callback: (modal) => {
        deleteAlert();
        modal.hide();
      }
    }
  ]
});

// Show modal
modal.show();

// Hide modal
modal.hide();

// Listen for modal events
modal.on('show', () => console.log('Modal shown'));
modal.on('hide', () => console.log('Modal hidden'));
modal.on('confirm', () => console.log('User confirmed'));
```

### Form Manager (`EASForm`)

Advanced form handling with validation and submission.

```javascript
// Initialize form
const form = new EASForm('#alertForm', {
  validation: {
    rules: {
      title: {
        required: true,
        maxLength: 100
      },
      type: {
        required: true
      },
      areas: {
        required: true,
        minItems: 1
      }
    },
    messages: {
      title: {
        required: 'Please enter an alert title',
        maxLength: 'Title must be less than 100 characters'
      }
    }
  },
  submission: {
    url: '/api/alerts',
    method: 'POST',
    onSuccess: (response) => {
      EASNotifications.show('success', 'Alert created successfully');
      form.reset();
    },
    onError: (error) => {
      EASNotifications.show('error', 'Failed to create alert');
    }
  }
});

// Validate form manually
const isValid = form.validate();

// Submit form programmatically
form.submit({
  data: {
    title: 'Test Alert',
    type: 'warning'
  }
});

// Reset form
form.reset();
```

### Data Table (`EASTable`)

Enhanced data tables with sorting, filtering, and pagination.

```javascript
// Initialize data table
const table = new EASTable('#alertsTable', {
  data: '/api/alerts',
  columns: [
    { key: 'id', label: 'ID', sortable: true },
    { key: 'type', label: 'Type', sortable: true },
    { key: 'status', label: 'Status', sortable: true },
    { key: 'received', label: 'Received', sortable: true },
    {
      key: 'actions',
      label: 'Actions',
      formatter: (value, row) => {
        return `
          <button class="btn btn-sm btn-primary" onclick="viewAlert(${row.id})">
            View
          </button>
        `;
      }
    }
  ],
  features: {
    sorting: true,
    filtering: true,
    pagination: true,
    export: true
  },
  pagination: {
    pageSize: 25,
    showSizeSelector: true
  }
});

// Refresh data
table.refresh();

// Apply filters
table.filter({
  status: 'active',
  type: 'torwarning'
});

// Sort by column
table.sort('received', 'desc');

// Export data
table.export('csv');
```

---

## Data Visualization

### Chart Manager (`EASChart`)

Highcharts integration with simplified API.

```javascript
// Create line chart
const lineChart = new EASChart('#lineChart', {
  type: 'line',
  title: 'Alert Trends',
  data: {
    url: '/api/chart/alerts-trends',
    params: { timeframe: '7d' }
  },
  options: {
    xAxis: {
      type: 'datetime'
    },
    yAxis: {
      title: {
        text: 'Number of Alerts'
      }
    },
    series: [{
      name: 'Alerts',
      color: '#3d73cd'
    }]
  }
});

// Create pie chart
const pieChart = new EASChart('#pieChart', {
  type: 'pie',
  title: 'Alert Distribution',
  data: {
    url: '/api/chart/alerts-by-type'
  },
  options: {
    series: [{
      name: 'Alerts',
      innerSize: '50%' // Donut chart
    }]
  }
});

// Update chart data
lineChart.updateData('/api/chart/alerts-trends', {
  timeframe: '30d'
});

// Update chart options
lineChart.updateOptions({
  title: {
    text: '30-Day Alert Trends'
  }
});
```

### Map Manager (`EASMap`)

Leaflet integration with EAS Station specific features.

```javascript
// Initialize map
const map = new EASMap('#alertMap', {
  center: [39.8283, -98.5795],
  zoom: 4,
  layers: {
    base: 'openstreetmap',
    overlays: {
      alerts: true,
      boundaries: true
    }
  }
});

// Add alert markers
map.addAlerts([
  {
    id: 1,
    lat: 41.8781,
    lng: -87.6298,
    type: 'torwarning',
    title: 'Tornado Warning'
  }
]);

// Add boundary layer
map.addBoundaries('/api/boundaries', {
  style: {
    color: '#3d73cd',
    weight: 2,
    opacity: 0.7
  }
});

// Handle map events
map.on('markerClick', (alertData) => {
  showAlertDetails(alertData);
});

map.on('boundaryClick', (boundaryData) => {
  showBoundaryInfo(boundaryData);
});

// Update map bounds
map.fitBounds(alertsData);
```

---

## Utility Functions

### Date/Time Utilities (`EASDate`)

```javascript
// Format dates
const formatted = EASDate.format(new Date(), 'YYYY-MM-DD HH:mm:ss');
const relative = EASDate.relative(new Date()); // "2 hours ago"

// Parse dates
const parsed = EASDate.parse('2025-01-28T10:30:00Z');

// Timezone handling
const local = EASDate.toLocal(utcDate);
const utc = EASDate.toUTC(localDate);

// Date calculations
const future = EASDate.addHours(new Date(), 24);
const diff = EASDate.diff(date1, date2, 'hours');
```

### String Utilities (`EASString`)

```javascript
// String formatting
const formatted = EASString.template('Alert {0} of type {1}', ['001', 'Tornado']);

// Truncation
const truncated = EASString.truncate('Long alert title...', 20);

// Slug generation
const slug = EASString.slugify('Tornado Warning Alert'); // "tornado-warning-alert"

// SAME code formatting
const sameCode = EASString.formatSAME('TOR', '039', '095'); // "ZCZC-WTOR-039095-"
```

### Validation Utilities (`EASValidation`)

```javascript
// Validate SAME codes
const isValid = EASValidation.isValidSAME('ZCZC-WTOR-039095-');

// Validate coordinates
const validCoords = EASValidation.isValidCoordinates(41.8781, -87.6298);

// Validate email
const validEmail = EASValidation.isValidEmail('user@example.com');

// Phone number validation
const validPhone = EASValidation.isValidPhone('+1-555-123-4567');
```

### Storage Utilities (`EASStorage`)

```javascript
// Local storage
EASStorage.set('userPreferences', { theme: 'dark' });
const preferences = EASStorage.get('userPreferences');

// Session storage
EASStorage.setSession('tempData', tempValue, { expires: 3600000 }); // 1 hour

// Clear storage
EASStorage.clear('userPreferences');
EASStorage.clearAll();
```

---

## Event System

### Global Events (`EASEvents`)

Centralized event management for component communication.

```javascript
// Subscribe to events
EASEvents.on('alert:created', (alertData) => {
  console.log('New alert created:', alertData);
});

EASEvents.on('user:login', (userData) => {
  updateUIForUser(userData);
});

// Emit events
EASEvents.emit('alert:created', {
  id: 123,
  type: 'torwarning',
  title: 'Tornado Warning'
});

// Once-only events
EASEvents.once('page:ready', () => {
  initializeComponents();
});

// Unsubscribe from events
const subscriptionId = EASEvents.on('alert:updated', handler);
EASEvents.off(subscriptionId);
```

### Component Events

Components emit their own events for specific interactions.

```javascript
// Table events
table.on('rowClick', (rowData) => {
  console.log('Row clicked:', rowData);
});

table.on('sort', (column, direction) => {
  console.log('Sorted by:', column, direction);
});

// Form events
form.on('validationError', (errors) => {
  console.log('Validation errors:', errors);
});

form.on('submit', (data) => {
  console.log('Form submitted:', data);
});

// Map events
map.on('zoom', (zoomLevel) => {
  console.log('Map zoomed to:', zoomLevel);
});

map.on('move', (bounds) => {
  console.log('Map moved to:', bounds);
});
```

---

## Configuration and Initialization

### Global Configuration
```javascript
// Configure EAS Station JavaScript
EASStation.configure({
  api: {
    baseUrl: '/api',
    timeout: 10000,
    retries: 3
  },
  theme: {
    default: 'light',
    persistence: true
  },
  notifications: {
    position: 'top-right',
    maxVisible: 5
  },
  charts: {
    defaultColors: ['#3d73cd', '#22c55e', '#f59e0b', '#ef4444'],
    animation: true
  },
  debug: false // Enable debug logging
});
```

### Module Loading
```javascript
// Load specific modules
EASStation.load(['api', 'theme', 'charts']).then(() => {
  console.log('Modules loaded');
});

// Check if module is available
if (EASStation.isModuleLoaded('websocket')) {
  // Use WebSocket features
}
```

### Error Handling
```javascript
// Global error handler
EASStation.on('error', (error, context) => {
  console.error('EAS Station Error:', error, context);
  
  // Send error to server for logging
  EASAPI.post('/api/log-error', {
    error: error.message,
    stack: error.stack,
    context: context
  });
});

// Module-specific error handling
EASAPI.on('networkError', (error) => {
  EASNotifications.show('warning', 'Network connection lost');
});
```

---

## Browser Compatibility

### Supported Browsers
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

### Feature Detection
```javascript
// Check browser capabilities
if (EASStation.supports.webSocket) {
  // Use WebSocket features
}

if (EASStation.supports.serviceWorker) {
  // Register service worker
}

if (EASStation.supports.notifications) {
  // Request notification permission
}
```

### Polyfills
The framework automatically includes polyfills for:
- Promise (for older browsers)
- Fetch API
- WebSocket
- CSS Custom Properties

---

## Performance Optimization

### Lazy Loading
```javascript
// Lazy load modules
EASStation.lazyLoad('charts', () => {
  return import('/static/js/charts/highcharts-wrapper.js');
});

// Lazy load components
EASStation.lazyComponent('#heavyComponent', () => {
  return loadHeavyComponent();
});
```

### Caching
```javascript
// API response caching
EASAPI.get('/api/alerts', { 
  cache: true,
  cacheTTL: 300000 // 5 minutes
});

// Component caching
EASStation.cacheComponent('#cachedComponent', 600000); // 10 minutes
```

### Memory Management
```javascript
// Cleanup resources
EASStation.cleanup();

// Cleanup specific module
EASStation.cleanupModule('charts');

// Monitor memory usage
if (EASStation.isDebugMode()) {
  console.log('Memory usage:', EASStation.getMemoryUsage());
}
```

---

This JavaScript API reference provides comprehensive documentation for all frontend functionality available in EAS Station. Each module is designed to be modular, extensible, and easy to use while maintaining high performance and accessibility standards.