/**
 * Admin Panel Core - Shared utilities and global state
 * Contains shared variables, utility functions, and core admin functionality
 */

// These variables will be populated by the template
window.AdminCore = window.AdminCore || {};

/**
 * Initialize core admin functionality
 * This function is called from admin.html after template variables are set
 */
window.AdminCore.init = function(config) {
    // Store configuration from template
    window.BOUNDARY_TYPE_CONFIG = config.BOUNDARY_TYPE_CONFIG || {};
    window.DEFAULT_BOUNDARY_TYPES = new Set(Object.keys(window.BOUNDARY_TYPE_CONFIG));
    window.ADMIN_SETUP_MODE = config.ADMIN_SETUP_MODE || false;
    window.EAS_EVENT_CODES = config.EAS_EVENT_CODES || [];
    window.EAS_DEFAULTS = config.EAS_DEFAULTS || {};
    window.EAS_FIPS_TREE = config.EAS_FIPS_TREE || [];
    window.EAS_FIPS_LOOKUP = config.EAS_FIPS_LOOKUP || {};
    window.EAS_COUNTY_FORECAST_ZONES = config.EAS_COUNTY_FORECAST_ZONES || {};
    window.EAS_ORIGINATOR_DESCRIPTIONS = config.EAS_ORIGINATOR_DESCRIPTIONS || {};
    window.EAS_P_DIGIT_MEANINGS = config.EAS_P_DIGIT_MEANINGS || {};
    window.MAX_SAME_CODES = 31;
    window.LOCATION_FIPS_MAX = 31;
    
    // Build state lookup maps
    window.EAS_STATE_BY_ABBR = {};
    window.EAS_STATE_BY_FIPS = {};
    (Array.isArray(window.EAS_FIPS_TREE) ? window.EAS_FIPS_TREE : []).forEach((state) => {
        if (!state) return;
        if (state.abbr) {
            window.EAS_STATE_BY_ABBR[state.abbr] = state;
        }
        if (state.state_fips) {
            window.EAS_STATE_BY_FIPS[state.state_fips] = state;
        }
    });
    
    // Initialize global state variables
    window.latestOperationStatus = {};
    window.boundaryCache = {
        features: [],
        grouped: {},
        stats: { total: 0, types: 0 },
        lastLoaded: null
    };
    window.confirmationModal = null;
    window.currentOperation = null;
    window.editAlertModal = null;
    window.adminAlerts = [];
    window.adminAlertFilters = { includeExpired: false, search: '' };
    window.alertSearchTimeout = null;
    window.editingAlertId = null;
    window.locationSettingsCache = window.APP_LOCATION ? { ...window.APP_LOCATION } : null;
    window.locationReferenceCache = null;
    window.easLastResponse = null;
    window.selectedSameCodes = [];
    window.locationFipsSelection = [];
    window.locationDerivedZoneList = [];
    window.locationDerivedZoneCodes = new Set();
};

/**
 * HTML escape utility for admin panel
 */
// Legacy alias kept for callers that still reference escapeHtmlAdmin (e.g.
// zone-catalog.js). It delegates to the single canonical implementation in
// js/core/utils.js — do not reintroduce a separate body here. The previous
// local version used the textContent round-trip, which does not escape quotes
// and so was unsafe in attribute contexts.
window.escapeHtmlAdmin = function(str) {
    return window.escapeHtml(str);
};

/**
 * Show status message (for operations like backup/upgrade)
 */
window.showStatus = function(message, type = 'info', duration = 5000) {
    // Use showToast if available, otherwise console log
    if (typeof window.showToast === 'function') {
        window.showToast(message, type, duration);
    } else {
        console.log(`[${type}] ${message}`);
    }
};

/**
 * Show confirmation dialog
 */
window.showConfirmation = function(message, onConfirm, onCancel) {
    if (confirm(message)) {
        if (typeof onConfirm === 'function') onConfirm();
    } else {
        if (typeof onCancel === 'function') onCancel();
    }
};

/**
 * Format bytes to human-readable size
 */
window.formatBytes = function(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
};

/**
 * Format timestamp for display
 */
window.formatDateTimeDisplay = function(timestamp) {
    if (!timestamp) return 'N/A';
    try {
        const date = new Date(timestamp);
        return date.toLocaleString();
    } catch (e) {
        return timestamp;
    }
};

/**
 * Format latitude/longitude for display
 */
window.formatLatLon = function(lat, lon, decimals = 4) {
    if (lat === null || lat === undefined || lon === null || lon === undefined) {
        return 'N/A';
    }
    return `${parseFloat(lat).toFixed(decimals)}, ${parseFloat(lon).toFixed(decimals)}`;
};

/**
 * Format duration in minutes with proper label
 */
window.formatDurationMinutesLabel = function(minutes) {
    if (!minutes || minutes <= 0) return '0 minutes';
    if (minutes === 1) return '1 minute';
    if (minutes < 60) return `${minutes} minutes`;
    
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    
    let result = '';
    if (hours === 1) result += '1 hour';
    else if (hours > 1) result += `${hours} hours`;
    
    if (mins > 0) {
        if (result) result += ' ';
        if (mins === 1) result += '1 minute';
        else result += `${mins} minutes`;
    }
    
    return result;
};

/**
 * Sanitize boundary type input to create safe identifiers
 */
window.sanitizeBoundaryTypeInput = function(value) {
    if (!value) {
        return '';
    }
    return value
        .toString()
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '');
};

/**
 * Initialize on DOMContentLoaded
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('Admin Core initialized');

    const confirmModalEl = document.getElementById('confirmationModal');
    if (confirmModalEl) {
        // Move to <body> so Bootstrap modal z-index renders above the sticky navbar
        // stacking context created by its backdrop-filter property.
        document.body.appendChild(confirmModalEl);
        window.confirmationModal = new bootstrap.Modal(confirmModalEl);
    }
});
