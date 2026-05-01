/**
 * Admin Panel - Location Settings Module
 * Handles location settings form submission, FIPS code selection, and zone code management
 */

/**
 * Parse newline-separated values into an array
 * @param {string} value - Raw textarea value
 * @returns {string[]} - Array of non-empty trimmed values
 */
function parseNewlineValues(value) {
    if (!value || typeof value !== 'string') {
        return [];
    }
    return value
        .split(/[\r\n]+/)
        .map(line => line.trim().toUpperCase())
        .filter(line => line.length > 0);
}

/**
 * Initialize location settings form handlers
 */
function initLocationSettings() {
    const form = document.getElementById('locationSettingsForm');
    if (!form) {
        return;
    }

    // Initialize FIPS state dropdown
    initFipsStateDropdown();

    // Initialize FIPS county dropdown event handlers
    initFipsCountyDropdown();

    // Initialize add FIPS button
    initAddFipsButton();

    // Initialize location reference refresh button
    initLocationReferenceRefresh();

    // Initialize reset button
    initResetButton();

    // Form submission handler
    form.addEventListener('submit', handleLocationSettingsSubmit);

    // Load initial FIPS codes from hidden input
    loadInitialFipsCodes();

    // Load location reference data
    loadLocationReference();
}

/**
 * Handle location settings form submission
 * @param {Event} e - Submit event
 */
async function handleLocationSettingsSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const statusEl = document.getElementById('locationSettingsStatus');
    const submitBtn = form.querySelector('button[type="submit"]');

    // Disable submit button during request
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    }

    if (statusEl) {
        statusEl.textContent = 'Saving...';
        statusEl.className = 'text-muted small ms-3';
    }

    // Collect form data
    const countyName = document.getElementById('locationCountyName')?.value?.trim() || '';
    const stateCode = document.getElementById('locationStateCode')?.value?.trim().toUpperCase() || '';
    const timezone = document.getElementById('locationTimezone')?.value?.trim() || '';
    const fipsCodesHidden = document.getElementById('locationFipsCodes')?.value || '';
    const zoneCodesText = document.getElementById('locationZoneCodes')?.value || '';
    const storageZoneCodesText = document.getElementById('locationStorageZoneCodes')?.value || '';
    const mapCenterLat = parseFloat(document.getElementById('locationMapLat')?.value) || 0;
    const mapCenterLng = parseFloat(document.getElementById('locationMapLng')?.value) || 0;
    const mapDefaultZoom = parseInt(document.getElementById('locationMapZoom')?.value, 10) || 9;

    // Parse FIPS codes from hidden input (comma-separated)
    const fipsCodes = fipsCodesHidden
        .split(',')
        .map(code => code.trim())
        .filter(code => code.length > 0);

    // Parse zone codes from textareas (newline-separated)
    const zoneCodes = parseNewlineValues(zoneCodesText);
    const storageZoneCodes = parseNewlineValues(storageZoneCodesText);

    const payload = {
        county_name: countyName,
        state_code: stateCode,
        timezone: timezone,
        fips_codes: fipsCodes,
        zone_codes: zoneCodes,
        storage_zone_codes: storageZoneCodes,
        map_center_lat: mapCenterLat,
        map_center_lng: mapCenterLng,
        map_default_zoom: mapDefaultZoom
    };

    try {
        const response = await fetch('/admin/location_settings', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': window.CSRF_TOKEN || ''
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (response.ok && result.success) {
            if (statusEl) {
                statusEl.textContent = '✓ Location settings saved successfully';
                statusEl.className = 'text-success small ms-3';
            }
            if (typeof showToast === 'function') {
                showToast('Location settings saved successfully', 'success');
            }
            // Reload location reference after save
            loadLocationReference();
            // Update cache
            if (result.settings) {
                window.locationSettingsCache = result.settings;
            }
        } else {
            const errorMsg = result.error || 'Failed to save location settings';
            if (statusEl) {
                statusEl.textContent = '✗ ' + errorMsg;
                statusEl.className = 'text-danger small ms-3';
            }
            if (typeof showToast === 'function') {
                showToast(errorMsg, 'danger');
            }
        }
    } catch (error) {
        console.error('Error saving location settings:', error);
        if (statusEl) {
            statusEl.textContent = '✗ Network error: ' + error.message;
            statusEl.className = 'text-danger small ms-3';
        }
        if (typeof showToast === 'function') {
            showToast('Network error: ' + error.message, 'danger');
        }
    } finally {
        // Re-enable submit button
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Save Location Settings';
        }
    }
}

/**
 * Initialize FIPS state dropdown with states from EAS_FIPS_TREE
 */
function initFipsStateDropdown() {
    const stateSelect = document.getElementById('locationFipsState');
    if (!stateSelect) {
        return;
    }

    // Clear existing options except the first placeholder
    while (stateSelect.options.length > 1) {
        stateSelect.remove(1);
    }

    // Add "Nationwide" special option at the top
    const nationwideOption = document.createElement('option');
    nationwideOption.value = '_NATIONWIDE_';
    nationwideOption.textContent = '★ NATIONWIDE (All US)';
    nationwideOption.classList.add('fw-bold');
    stateSelect.appendChild(nationwideOption);

    // Add separator
    const separator = document.createElement('option');
    separator.disabled = true;
    separator.textContent = '── States ──';
    stateSelect.appendChild(separator);

    // Add state options from EAS_FIPS_TREE
    const states = window.EAS_FIPS_TREE || [];
    states.forEach(state => {
        if (!state || !state.abbr || !state.name) {
            return;
        }
        const option = document.createElement('option');
        option.value = state.abbr;
        option.textContent = `${state.name} (${state.abbr})`;
        stateSelect.appendChild(option);
    });

    // Handle state selection change
    stateSelect.addEventListener('change', function() {
        populateCountyDropdown(this.value);
    });
}

/**
 * Initialize FIPS county dropdown event handlers
 */
function initFipsCountyDropdown() {
    const countySelect = document.getElementById('locationFipsCounty');
    if (!countySelect) {
        return;
    }
    // Enable/disable based on state selection is handled in populateCountyDropdown
}

/**
 * Populate county dropdown based on selected state
 * @param {string} stateAbbr - State abbreviation
 */
function populateCountyDropdown(stateAbbr) {
    const countySelect = document.getElementById('locationFipsCounty');
    if (!countySelect) {
        return;
    }

    // Clear existing options
    countySelect.innerHTML = '';

    if (!stateAbbr) {
        countySelect.innerHTML = '<option value="">Select a state first…</option>';
        countySelect.disabled = true;
        return;
    }

    // Handle special "Nationwide" selection
    if (stateAbbr === '_NATIONWIDE_') {
        countySelect.innerHTML = '<option value="000000">000000 ★ Nationwide (All United States)</option>';
        countySelect.disabled = false;
        countySelect.removeAttribute('disabled');
        return;
    }

    // Find state data
    const states = window.EAS_FIPS_TREE || [];
    const stateData = states.find(s => s && s.abbr === stateAbbr);

    if (!stateData || !stateData.counties || stateData.counties.length === 0) {
        countySelect.innerHTML = '<option value="">No counties found</option>';
        countySelect.disabled = true;
        return;
    }

    // Add placeholder option
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a county or entire state…';
    countySelect.appendChild(placeholder);

    // Add "Entire State" option at the top
    if (stateData.statewide_code) {
        const stateOption = document.createElement('option');
        stateOption.value = stateData.statewide_code;
        stateOption.textContent = `${stateData.statewide_code} ★ Entire ${stateData.name || stateAbbr}`;
        stateOption.classList.add('fw-bold');
        countySelect.appendChild(stateOption);
    }

    // Add separator
    const separator = document.createElement('option');
    separator.disabled = true;
    separator.textContent = '── Counties ──';
    countySelect.appendChild(separator);

    // Add county options
    let optionCount = 0;
    stateData.counties.forEach(county => {
        if (!county || !county.code || !county.name) {
            return;
        }
        const option = document.createElement('option');
        option.value = county.code;
        option.textContent = `${county.code} ${county.name}`;
        countySelect.appendChild(option);
        optionCount++;
    });

    // Enable the dropdown - use both methods for cross-browser compatibility
    if (optionCount > 0) {
        countySelect.disabled = false;
        countySelect.removeAttribute('disabled');
    } else {
        countySelect.innerHTML = '<option value="">No counties available</option>';
        countySelect.disabled = true;
    }
}

/**
 * Initialize add FIPS button handler
 */
function initAddFipsButton() {
    const addBtn = document.getElementById('locationAddFipsBtn');
    if (!addBtn) {
        return;
    }

    addBtn.addEventListener('click', function() {
        const countySelect = document.getElementById('locationFipsCounty');
        const selectedCode = countySelect?.value;
        const selectedText = countySelect?.options[countySelect.selectedIndex]?.textContent;

        if (!selectedCode) {
            if (typeof showToast === 'function') {
                showToast('Please select a county to add', 'warning');
            }
            return;
        }

        addFipsCode(selectedCode, selectedText);

        // Reset the county dropdown to placeholder
        if (countySelect) {
            countySelect.value = '';
        }
    });
}

/**
 * Add a FIPS code to the selection
 * @param {string} code - FIPS code
 * @param {string} label - Display label
 */
function addFipsCode(code, label) {
    // Check for duplicates
    if (window.locationFipsSelection.some(item => item.code === code)) {
        if (typeof showToast === 'function') {
            showToast('This county is already selected', 'warning');
        }
        return;
    }

    // Check max limit
    const maxCodes = window.LOCATION_FIPS_MAX || 31;
    if (window.locationFipsSelection.length >= maxCodes) {
        if (typeof showToast === 'function') {
            showToast(`Maximum of ${maxCodes} FIPS codes allowed`, 'warning');
        }
        return;
    }

    // Add to selection
    window.locationFipsSelection.push({ code, label });

    // Update UI and hidden input
    renderFipsSelection();
    updateFipsHiddenInput();
}

/**
 * Remove a FIPS code from the selection
 * @param {string} code - FIPS code to remove
 */
function removeFipsCode(code) {
    window.locationFipsSelection = window.locationFipsSelection.filter(item => item.code !== code);
    renderFipsSelection();
    updateFipsHiddenInput();
}

/**
 * Render the FIPS selection chips
 */
function renderFipsSelection() {
    const container = document.getElementById('locationSelectedFips');
    if (!container) {
        return;
    }

    if (window.locationFipsSelection.length === 0) {
        container.innerHTML = '<p class="text-muted small mb-0">No SAME / FIPS counties selected yet.</p>';
        return;
    }

    let html = '<div class="d-flex flex-wrap gap-2">';
    window.locationFipsSelection.forEach(item => {
        const lookup = window.EAS_FIPS_LOOKUP || {};
        const countyName = lookup[item.code] || item.label || item.code;
        html += `
            <span class="badge bg-primary d-flex align-items-center gap-2">
                <code>${item.code}</code>
                <span>${countyName}</span>
                <button type="button" class="btn-close btn-close-white" style="font-size: 0.6em;" onclick="removeFipsCode('${item.code}')" title="Remove"></button>
            </span>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}

/**
 * Update the hidden FIPS codes input
 */
function updateFipsHiddenInput() {
    const hiddenInput = document.getElementById('locationFipsCodes');
    if (hiddenInput) {
        hiddenInput.value = window.locationFipsSelection.map(item => item.code).join(',');
    }
}

/**
 * Load initial FIPS codes from the settings
 */
function loadInitialFipsCodes() {
    // Initialize the selection array if not exists
    if (!window.locationFipsSelection) {
        window.locationFipsSelection = [];
    }

    const hiddenInput = document.getElementById('locationFipsCodes');
    if (!hiddenInput || !hiddenInput.value) {
        // Try to load from cache
        const cache = window.locationSettingsCache || window.APP_LOCATION;
        if (cache && cache.fips_codes && Array.isArray(cache.fips_codes)) {
            const lookup = window.EAS_FIPS_LOOKUP || {};
            cache.fips_codes.forEach(code => {
                if (code) {
                    window.locationFipsSelection.push({
                        code: code,
                        label: lookup[code] || code
                    });
                }
            });
            renderFipsSelection();
            updateFipsHiddenInput();
        }
        return;
    }

    // Parse existing value
    const codes = hiddenInput.value.split(',').map(c => c.trim()).filter(c => c);
    const lookup = window.EAS_FIPS_LOOKUP || {};

    codes.forEach(code => {
        window.locationFipsSelection.push({
            code: code,
            label: lookup[code] || code
        });
    });

    renderFipsSelection();
}

/**
 * Initialize location reference refresh button
 */
function initLocationReferenceRefresh() {
    const refreshBtn = document.getElementById('refreshLocationReference');
    if (!refreshBtn) {
        return;
    }

    refreshBtn.addEventListener('click', function() {
        loadLocationReference(true);
    });
}

/**
 * Load location reference data from API
 * @param {boolean} showMessage - Whether to show a status message
 */
async function loadLocationReference(showMessage = false) {
    const statusEl = document.getElementById('locationReferenceStatus');
    const contentEl = document.getElementById('locationReferenceContent');

    if (statusEl && showMessage) {
        statusEl.textContent = 'Loading...';
    }

    try {
        const response = await fetch('/admin/location_reference', {
            headers: {
                'X-CSRF-Token': window.CSRF_TOKEN || ''
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        window.locationReferenceCache = data;

        if (contentEl) {
            renderLocationReference(data, contentEl);
        }

        if (statusEl) {
            statusEl.textContent = showMessage ? '✓ Reference data refreshed' : '';
        }
    } catch (error) {
        console.error('Error loading location reference:', error);
        if (statusEl) {
            statusEl.textContent = '✗ Failed to load reference data';
        }
        if (contentEl) {
            contentEl.innerHTML = '<p class="text-danger small mb-0">Failed to load location reference data.</p>';
        }
    }
}

/**
 * Render location reference data
 * @param {Object} data - Reference data from API
 * @param {HTMLElement} container - Container element
 */
function renderLocationReference(data, container) {
    if (!data) {
        container.innerHTML = '<p class="text-muted small mb-0">No reference data available.</p>';
        return;
    }

    let html = '<div class="row g-3">';

    // Location summary
    if (data.location) {
        html += `
            <div class="col-12">
                <div class="d-flex flex-wrap gap-3">
                    <span class="badge bg-secondary">
                        <i class="fas fa-map-marker-alt me-1"></i>
                        ${escapeHtml(data.location.county_name || 'Unknown')}, ${escapeHtml(data.location.state_code || '??')}
                    </span>
                    <span class="badge bg-info">
                        <i class="fas fa-clock me-1"></i>
                        ${escapeHtml(data.location.timezone || 'Unknown timezone')}
                    </span>
                </div>
            </div>
        `;
    }

    // FIPS codes summary
    if (data.fips) {
        const knownCount = data.fips.known?.length || 0;
        const missingCount = data.fips.missing?.length || 0;
        html += `
            <div class="col-md-6">
                <h6 class="fw-bold small mb-2">
                    <i class="fas fa-hashtag text-primary me-1"></i>
                    SAME / FIPS Codes (${knownCount} configured)
                </h6>
        `;
        if (knownCount > 0) {
            html += '<div class="d-flex flex-wrap gap-1">';
            data.fips.known.forEach(item => {
                const badge = item.is_statewide ? 'bg-warning text-dark' : 'bg-light text-dark border';
                html += `<span class="badge ${badge}" title="${escapeHtml(item.label || '')}">${escapeHtml(item.code)}</span>`;
            });
            html += '</div>';
        }
        if (missingCount > 0) {
            html += `<p class="text-warning small mt-2 mb-0"><i class="fas fa-exclamation-triangle me-1"></i> ${missingCount} code(s) not found in catalog</p>`;
        }
        html += '</div>';
    }

    // Zone codes summary
    if (data.zones) {
        const knownCount = data.zones.known?.length || 0;
        const missingCount = data.zones.missing?.length || 0;
        html += `
            <div class="col-md-6">
                <h6 class="fw-bold small mb-2">
                    <i class="fas fa-map me-1 text-success"></i>
                    NOAA Zone Codes (${knownCount} configured)
                </h6>
        `;
        if (knownCount > 0) {
            html += '<div class="d-flex flex-wrap gap-1">';
            data.zones.known.slice(0, 20).forEach(item => {
                const typeClass = item.zone_type === 'Z' ? 'bg-success' : 'bg-info';
                html += `<span class="badge ${typeClass}" title="${escapeHtml(item.label || '')}">${escapeHtml(item.code)}</span>`;
            });
            if (knownCount > 20) {
                html += `<span class="badge bg-secondary">+${knownCount - 20} more</span>`;
            }
            html += '</div>';
        }
        if (missingCount > 0) {
            html += `<p class="text-warning small mt-2 mb-0"><i class="fas fa-exclamation-triangle me-1"></i> ${missingCount} code(s) not found in zone catalog</p>`;
        }
        html += '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
}

/**
 * Initialize reset button handler
 */
function initResetButton() {
    const resetBtn = document.getElementById('resetLocationSettings');
    if (!resetBtn) {
        return;
    }

    resetBtn.addEventListener('click', function() {
        const cache = window.locationSettingsCache || window.APP_LOCATION;
        if (!cache) {
            if (typeof showToast === 'function') {
                showToast('No cached settings to restore', 'warning');
            }
            return;
        }

        // Reset form fields
        const countyNameInput = document.getElementById('locationCountyName');
        const stateCodeInput = document.getElementById('locationStateCode');
        const timezoneInput = document.getElementById('locationTimezone');
        const zoneCodesTextarea = document.getElementById('locationZoneCodes');
        const storageZoneCodesTextarea = document.getElementById('locationStorageZoneCodes');
        const mapLatInput = document.getElementById('locationMapLat');
        const mapLngInput = document.getElementById('locationMapLng');
        const mapZoomInput = document.getElementById('locationMapZoom');

        if (countyNameInput) countyNameInput.value = cache.county_name || '';
        if (stateCodeInput) stateCodeInput.value = cache.state_code || '';
        if (timezoneInput) timezoneInput.value = cache.timezone || 'America/New_York';
        if (zoneCodesTextarea) zoneCodesTextarea.value = (cache.zone_codes || []).join('\n');
        if (storageZoneCodesTextarea) storageZoneCodesTextarea.value = (cache.storage_zone_codes || []).join('\n');
        if (mapLatInput) mapLatInput.value = cache.map_center_lat || 0;
        if (mapLngInput) mapLngInput.value = cache.map_center_lng || 0;
        if (mapZoomInput) mapZoomInput.value = cache.map_default_zoom || 9;

        // Reset FIPS selection
        window.locationFipsSelection = [];
        const lookup = window.EAS_FIPS_LOOKUP || {};
        if (cache.fips_codes && Array.isArray(cache.fips_codes)) {
            cache.fips_codes.forEach(code => {
                if (code) {
                    window.locationFipsSelection.push({
                        code: code,
                        label: lookup[code] || code
                    });
                }
            });
        }
        renderFipsSelection();
        updateFipsHiddenInput();

        // Clear status
        const statusEl = document.getElementById('locationSettingsStatus');
        if (statusEl) {
            statusEl.textContent = '';
        }

        if (typeof showToast === 'function') {
            showToast('Form reset to saved values', 'info');
        }
    });
}

/**
 * Escape HTML special characters
 * @param {string} str - String to escape
 * @returns {string} - Escaped string
 */
function escapeHtml(str) {
    if (!str || typeof str !== 'string') {
        return '';
    }
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ==================== Zone Search Functionality ====================

let selectedZone = null;
let locationZoneSearchTimeout = null;

/**
 * Initialize zone search functionality
 */
function initZoneSearch() {
    const searchInput = document.getElementById('locationZoneSearch');
    const addToBroadcastBtn = document.getElementById('addToBroadcastZonesBtn');
    const addToStorageBtn = document.getElementById('addToStorageZonesBtn');
    const broadcastTextarea = document.getElementById('locationZoneCodes');
    const storageTextarea = document.getElementById('locationStorageZoneCodes');

    if (!searchInput) {
        return;
    }

    // Search input handler with debouncing
    searchInput.addEventListener('input', function(e) {
        clearTimeout(locationZoneSearchTimeout);
        const query = e.target.value.trim();

        if (query.length < 2) {
            document.getElementById('locationZoneSearchResults').innerHTML =
                '<p class="text-muted small mb-0">Enter at least 2 characters to search zones</p>';
            selectedZone = null;
            updateZoneAddButtons();
            return;
        }

        locationZoneSearchTimeout = setTimeout(() => searchZonesForLocation(query), 300);
    });

    // Add to broadcast zones button
    if (addToBroadcastBtn) {
        addToBroadcastBtn.addEventListener('click', function() {
            if (selectedZone && broadcastTextarea) {
                addZoneToTextarea(broadcastTextarea, selectedZone.zone_code);
                updateZoneCounts();
                if (typeof showToast === 'function') {
                    showToast(`Added ${selectedZone.zone_code} to broadcast zones`, 'success');
                }
            }
        });
    }

    // Add to storage zones button
    if (addToStorageBtn) {
        addToStorageBtn.addEventListener('click', function() {
            if (selectedZone && storageTextarea) {
                addZoneToTextarea(storageTextarea, selectedZone.zone_code);
                updateZoneCounts();
                if (typeof showToast === 'function') {
                    showToast(`Added ${selectedZone.zone_code} to storage zones`, 'success');
                }
            }
        });
    }

    // Update zone counts on textarea change
    if (broadcastTextarea) {
        broadcastTextarea.addEventListener('input', updateZoneCounts);
    }
    if (storageTextarea) {
        storageTextarea.addEventListener('input', updateZoneCounts);
    }

    // Initial zone count update
    updateZoneCounts();
}

/**
 * Search zones via API
 * @param {string} query - Search query
 */
async function searchZonesForLocation(query) {
    const resultsDiv = document.getElementById('locationZoneSearchResults');
    if (!resultsDiv) {
        return;
    }

    resultsDiv.innerHTML = '<p class="text-muted small mb-0"><i class="fas fa-spinner fa-spin"></i> Searching...</p>';

    try {
        const response = await fetch(`/admin/zones/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();

        if (response.ok && data.zones) {
            if (data.zones.length === 0) {
                resultsDiv.innerHTML = '<p class="text-muted small mb-0">No zones found</p>';
                selectedZone = null;
                updateZoneAddButtons();
            } else {
                renderZoneSearchResults(data.zones, resultsDiv);
            }
        } else {
            resultsDiv.innerHTML = '<p class="text-danger small mb-0">Error loading results</p>';
            selectedZone = null;
            updateZoneAddButtons();
        }
    } catch (error) {
        console.error('Zone search error:', error);
        resultsDiv.innerHTML = '<p class="text-danger small mb-0">Error: ' + escapeHtml(error.message) + '</p>';
        selectedZone = null;
        updateZoneAddButtons();
    }
}

/**
 * Render zone search results
 * @param {Array} zones - Array of zone objects
 * @param {HTMLElement} container - Container element
 */
function renderZoneSearchResults(zones, container) {
    let html = '<div class="list-group list-group-flush">';
    zones.slice(0, 20).forEach((zone, index) => {
        const isSelected = selectedZone && selectedZone.zone_code === zone.zone_code;
        const selectedClass = isSelected ? 'active' : '';
        const typeLabel = zone.zone_code.includes('C') ? 'County' : 'Forecast';
        const typeBadge = zone.zone_code.includes('C') ? 'bg-info' : 'bg-success';

        html += `
            <button type="button" class="list-group-item list-group-item-action py-2 ${selectedClass}"
                    onclick="selectZoneResult(${index})" data-zone-index="${index}">
                <div class="d-flex w-100 justify-content-between align-items-center">
                    <div>
                        <span class="badge bg-primary me-2">${escapeHtml(zone.zone_code)}</span>
                        <span class="badge ${typeBadge} me-2">${typeLabel}</span>
                        <strong>${escapeHtml(zone.name)}</strong>, ${escapeHtml(zone.state_code)}
                    </div>
                    <small class="text-muted">
                        ${zone.cwa ? 'CWA: ' + escapeHtml(zone.cwa) : ''}
                    </small>
                </div>
            </button>
        `;
    });

    if (zones.length > 20) {
        html += `<div class="list-group-item text-muted small">...and ${zones.length - 20} more results</div>`;
    }

    html += '</div>';
    container.innerHTML = html;

    // Store zones for selection
    window._locationZoneSearchResults = zones;
}

/**
 * Select a zone from search results
 * @param {number} index - Index of selected zone
 */
function selectZoneResult(index) {
    const zones = window._locationZoneSearchResults || [];
    if (index >= 0 && index < zones.length) {
        selectedZone = zones[index];

        // Update visual selection
        const buttons = document.querySelectorAll('#locationZoneSearchResults .list-group-item');
        buttons.forEach((btn, i) => {
            if (i === index) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        updateZoneAddButtons();
    }
}

/**
 * Update the enabled state of add zone buttons
 */
function updateZoneAddButtons() {
    const addToBroadcastBtn = document.getElementById('addToBroadcastZonesBtn');
    const addToStorageBtn = document.getElementById('addToStorageZonesBtn');

    if (addToBroadcastBtn) {
        addToBroadcastBtn.disabled = !selectedZone;
    }
    if (addToStorageBtn) {
        addToStorageBtn.disabled = !selectedZone;
    }
}

/**
 * Add a zone code to a textarea if not already present
 * @param {HTMLTextAreaElement} textarea - Target textarea
 * @param {string} zoneCode - Zone code to add
 */
function addZoneToTextarea(textarea, zoneCode) {
    if (!textarea || !zoneCode) {
        return;
    }

    const currentCodes = parseNewlineValues(textarea.value);
    const normalizedCode = zoneCode.trim().toUpperCase();

    if (currentCodes.includes(normalizedCode)) {
        if (typeof showToast === 'function') {
            showToast(`${normalizedCode} is already in the list`, 'warning');
        }
        return;
    }

    // Add the new code
    currentCodes.push(normalizedCode);
    textarea.value = currentCodes.join('\n');

    // Trigger change event
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Update zone count badges
 */
function updateZoneCounts() {
    const broadcastTextarea = document.getElementById('locationZoneCodes');
    const storageTextarea = document.getElementById('locationStorageZoneCodes');
    const broadcastCountEl = document.getElementById('broadcastZoneCount');
    const storageCountEl = document.getElementById('storageZoneCount');

    if (broadcastTextarea && broadcastCountEl) {
        const count = parseNewlineValues(broadcastTextarea.value).length;
        broadcastCountEl.textContent = count;
    }

    if (storageTextarea && storageCountEl) {
        const count = parseNewlineValues(storageTextarea.value).length;
        storageCountEl.textContent = count;
    }
}

// ==================== End Zone Search Functionality ====================

// ==================== EAS Settings Functionality ====================

let easSettingsCache = null;

/**
 * Initialize EAS settings form handlers
 */
function initEasSettings() {
    const form = document.getElementById('easSettingsForm');
    if (!form) {
        return;
    }

    // Build event filter checkbox grid before loading settings
    buildEasEventFilterUI();

    // Load initial EAS settings
    loadEasSettings();

    // Form submission handler
    form.addEventListener('submit', handleEasSettingsSubmit);

    // Reset button handler
    const resetBtn = document.getElementById('resetEasSettings');
    if (resetBtn) {
        resetBtn.addEventListener('click', function() {
            if (easSettingsCache) {
                populateEasForm(easSettingsCache);
                if (typeof showToast === 'function') {
                    showToast('Form reset to saved values', 'info');
                }
            }
        });
    }
}

/**
 * Load EAS settings from API
 */
async function loadEasSettings() {
    try {
        const response = await fetch('/admin/eas_settings', {
            headers: {
                'X-CSRF-Token': window.CSRF_TOKEN || ''
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        if (data.settings) {
            easSettingsCache = data.settings;
            populateEasForm(data.settings);
        }
    } catch (error) {
        console.error('Error loading EAS settings:', error);
    }
}

/**
 * Populate the EAS settings form with data
 * @param {Object} settings - EAS settings object
 */
function populateEasForm(settings) {
    const enabledCheckbox = document.getElementById('easBroadcastEnabled');
    const originatorSelect = document.getElementById('easOriginator');
    const stationIdInput = document.getElementById('easStationId');
    const sampleRateSelect = document.getElementById('easSampleRate');
    const attentionToneInput = document.getElementById('easAttentionTone');
    const audioPlayerInput = document.getElementById('easAudioPlayer');
    const outputDirInput = document.getElementById('easOutputDir');
    const authorizedEventsTextarea = document.getElementById('easAuthorizedEvents');

    if (enabledCheckbox) {
        enabledCheckbox.checked = settings.broadcast_enabled || false;
    }
    if (originatorSelect) {
        originatorSelect.value = settings.originator || 'WXR';
    }
    if (stationIdInput) {
        stationIdInput.value = settings.station_id || 'EASNODES';
    }
    if (sampleRateSelect) {
        sampleRateSelect.value = String(settings.sample_rate || 16000);
    }
    if (attentionToneInput) {
        attentionToneInput.value = settings.attention_tone_seconds || 8;
    }
    if (audioPlayerInput) {
        audioPlayerInput.value = settings.audio_player || 'aplay';
    }
    if (outputDirInput) {
        outputDirInput.value = settings.output_dir || 'static/eas_messages';
    }
    const endecFingerprintCheckbox = document.getElementById('easEndecFingerprint');
    if (endecFingerprintCheckbox) {
        endecFingerprintCheckbox.checked = settings.endec_fingerprint !== false;
    }
    const preAlertChimeSelect = document.getElementById('easPreAlertChime');
    if (preAlertChimeSelect) {
        preAlertChimeSelect.value = settings.pre_alert_chime || 'none';
    }
    const postAlertChimeSelect = document.getElementById('easPostAlertChime');
    if (postAlertChimeSelect) {
        postAlertChimeSelect.value = settings.post_alert_chime || 'none';
    }
    const preAlertChimeDuration = document.getElementById('easPreAlertChimeDuration');
    if (preAlertChimeDuration) {
        const _v = settings.pre_alert_chime_duration;
        preAlertChimeDuration.value = (_v === null || _v === undefined) ? '2.0' : Number(_v).toFixed(1);
    }
    const postAlertChimeDuration = document.getElementById('easPostAlertChimeDuration');
    if (postAlertChimeDuration) {
        const _v = settings.post_alert_chime_duration;
        postAlertChimeDuration.value = (_v === null || _v === undefined) ? '2.0' : Number(_v).toFixed(1);
    }
    const qc2ToneAFreq = document.getElementById('easQc2ToneAFreq');
    if (qc2ToneAFreq) {
        const _v = settings.qc2_tone_a_freq;
        qc2ToneAFreq.value = (_v === null || _v === undefined) ? '1000.0' : Number(_v).toFixed(1);
    }
    const qc2ToneBFreq = document.getElementById('easQc2ToneBFreq');
    if (qc2ToneBFreq) {
        const _v = settings.qc2_tone_b_freq;
        qc2ToneBFreq.value = (_v === null || _v === undefined) ? '1500.0' : Number(_v).toFixed(1);
    }
    const dtmfSequence = document.getElementById('easDtmfSequence');
    if (dtmfSequence) {
        dtmfSequence.value = settings.dtmf_sequence || '';
    }
    if (authorizedEventsTextarea) {
        authorizedEventsTextarea.value = (settings.authorized_event_codes || []).join('\n');
    }

    // Set event filter checkboxes
    const forwarded = new Set((settings.forwarded_event_codes || []).map(c => c.toUpperCase()));
    document.querySelectorAll('.eas-event-filter-check').forEach(cb => {
        cb.checked = forwarded.size === 0 ? false : forwarded.has(cb.value);
    });
    syncForwardedEventCodesHidden();
}

/**
 * Build the event filter checkbox grid from EAS_EVENT_CODES.
 * Groups events by product type: WRN (Warnings), WCH (Watches), ADV (Advisories), TEST (Tests).
 */
function buildEasEventFilterUI() {
    const container = document.getElementById('easEventFilterContainer');
    if (!container) return;

    const eventCodes = window.EAS_EVENT_CODES || [];
    if (!eventCodes.length) {
        container.innerHTML = '<p class="text-muted small mb-0">No event codes available.</p>';
        return;
    }

    const groups = {
        WRN: { label: 'Warnings', icon: 'fa-exclamation-circle text-danger', items: [] },
        WCH: { label: 'Watches', icon: 'fa-eye text-warning', items: [] },
        ADV: { label: 'Advisories & Statements', icon: 'fa-info-circle text-info', items: [] },
        TEST: { label: 'Tests', icon: 'fa-vial text-secondary', items: [] },
    };
    const other = { label: 'Other', icon: 'fa-bell text-muted', items: [] };

    eventCodes.forEach(entry => {
        const g = groups[entry.product];
        if (g) {
            g.items.push(entry);
        } else {
            other.items.push(entry);
        }
    });

    if (other.items.length) groups['OTHER'] = other;

    let html = '<div class="row g-3">';
    Object.values(groups).forEach(group => {
        if (!group.items.length) return;
        html += `
            <div class="col-12 col-lg-6">
                <h6 class="mb-2"><i class="fas ${group.icon} me-1"></i> ${group.label}</h6>
                <div class="row g-1">`;
        group.items.forEach(entry => {
            const id = `easEvent_${entry.code}`;
            html += `
                    <div class="col-6">
                        <div class="form-check">
                            <input class="form-check-input eas-event-filter-check" type="checkbox"
                                   id="${id}" value="${entry.code}">
                            <label class="form-check-label small" for="${id}" title="${entry.name}">
                                <code class="text-primary">${entry.code}</code> ${entry.name}
                            </label>
                        </div>
                    </div>`;
        });
        html += `
                </div>
            </div>`;
    });
    html += '</div>';

    container.innerHTML = html;

    // Wire up change events to keep hidden input in sync
    container.querySelectorAll('.eas-event-filter-check').forEach(cb => {
        cb.addEventListener('change', syncForwardedEventCodesHidden);
    });

    // Select All / Clear All buttons
    const selectAllBtn = document.getElementById('easEventSelectAll');
    const clearAllBtn = document.getElementById('easEventClearAll');
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            container.querySelectorAll('.eas-event-filter-check').forEach(cb => { cb.checked = true; });
            syncForwardedEventCodesHidden();
        });
    }
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', () => {
            container.querySelectorAll('.eas-event-filter-check').forEach(cb => { cb.checked = false; });
            syncForwardedEventCodesHidden();
        });
    }
}

/**
 * Sync the hidden forwarded_event_codes input with checked checkboxes.
 * An empty selection means "forward all" — we send an empty array.
 */
function syncForwardedEventCodesHidden() {
    const hidden = document.getElementById('easForwardedEventCodes');
    if (!hidden) return;
    const checked = Array.from(
        document.querySelectorAll('.eas-event-filter-check:checked')
    ).map(cb => cb.value);
    hidden.value = checked.join(',');
}

/**
 * Handle EAS settings form submission
 * @param {Event} e - Submit event
 */
async function handleEasSettingsSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const statusEl = document.getElementById('easSettingsStatus');
    const submitBtn = form.querySelector('button[type="submit"]');

    // Disable submit button during request
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    }

    if (statusEl) {
        statusEl.textContent = 'Saving...';
        statusEl.className = 'text-muted small ms-3';
    }

    // Collect form data (FIPS codes are now managed in Location Settings)
    const payload = {
        broadcast_enabled: document.getElementById('easBroadcastEnabled')?.checked || false,
        originator: document.getElementById('easOriginator')?.value || 'WXR',
        station_id: document.getElementById('easStationId')?.value?.trim().toUpperCase() || 'EASNODES',
        sample_rate: parseInt(document.getElementById('easSampleRate')?.value, 10) || 16000,
        attention_tone_seconds: parseInt(document.getElementById('easAttentionTone')?.value, 10) || 8,
        audio_player: document.getElementById('easAudioPlayer')?.value?.trim() || 'aplay',
        output_dir: document.getElementById('easOutputDir')?.value?.trim() || 'static/eas_messages',
        endec_fingerprint: document.getElementById('easEndecFingerprint')?.checked ?? true,
        pre_alert_chime: document.getElementById('easPreAlertChime')?.value || 'none',
        post_alert_chime: document.getElementById('easPostAlertChime')?.value || 'none',
        pre_alert_chime_duration: parseFloat(document.getElementById('easPreAlertChimeDuration')?.value) || 2.0,
        post_alert_chime_duration: parseFloat(document.getElementById('easPostAlertChimeDuration')?.value) || 2.0,
        qc2_tone_a_freq: parseFloat(document.getElementById('easQc2ToneAFreq')?.value) || 1000.0,
        qc2_tone_b_freq: parseFloat(document.getElementById('easQc2ToneBFreq')?.value) || 1500.0,
        dtmf_sequence: (document.getElementById('easDtmfSequence')?.value || '').toUpperCase(),
        authorized_event_codes: parseNewlineValues(document.getElementById('easAuthorizedEvents')?.value || ''),
        forwarded_event_codes: (document.getElementById('easForwardedEventCodes')?.value || '')
            .split(',').map(s => s.trim().toUpperCase()).filter(Boolean),
    };

    try {
        const response = await fetch('/admin/eas_settings', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': window.CSRF_TOKEN || ''
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (response.ok && result.success) {
            if (statusEl) {
                statusEl.textContent = '✓ EAS settings saved successfully';
                statusEl.className = 'text-success small ms-3';
            }
            if (typeof showToast === 'function') {
                showToast('EAS settings saved successfully', 'success');
            }
            // Update cache
            if (result.settings) {
                easSettingsCache = result.settings;
            }
        } else {
            const errorMsg = result.error || 'Failed to save EAS settings';
            if (statusEl) {
                statusEl.textContent = '✗ ' + errorMsg;
                statusEl.className = 'text-danger small ms-3';
            }
            if (typeof showToast === 'function') {
                showToast(errorMsg, 'danger');
            }
        }
    } catch (error) {
        console.error('Error saving EAS settings:', error);
        if (statusEl) {
            statusEl.textContent = '✗ Network error: ' + error.message;
            statusEl.className = 'text-danger small ms-3';
        }
        if (typeof showToast === 'function') {
            showToast('Network error: ' + error.message, 'danger');
        }
    } finally {
        // Re-enable submit button
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Save EAS Settings';
        }
    }
}

// ==================== End EAS Settings Functionality ====================

// Export functions to window for global access
window.handleLocationSettingsSubmit = handleLocationSettingsSubmit;
window.addFipsCode = addFipsCode;
window.removeFipsCode = removeFipsCode;
window.loadLocationReference = loadLocationReference;
window.initLocationSettings = initLocationSettings;
window.selectZoneResult = selectZoneResult;
window.updateZoneCounts = updateZoneCounts;
window.initEasSettings = initEasSettings;
window.loadEasSettings = loadEasSettings;

// Initialize on DOMContentLoaded
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize if not in setup mode
    if (typeof ADMIN_SETUP_MODE !== 'undefined' && ADMIN_SETUP_MODE) {
        return;
    }
    initLocationSettings();
    initZoneSearch();
    initEasSettings();
});
