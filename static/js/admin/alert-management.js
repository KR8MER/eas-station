/**
* Admin Panel - Alert Management Module
* Handles alert editing, deletion, filtering, search, and bulk operations
*/

// Global state for alert management
let adminAlerts = [];
let adminAlertFilters = { includeExpired: false, search: '' };
let alertSearchTimeout = null;
let editingAlertId = null;
let editAlertModal;
let alertManagementInitialized = false;

// Initialize when the Alerts sub-tab is shown
const alertsSubTab = document.getElementById('alerts-subtab');
if (alertsSubTab) {
    alertsSubTab.addEventListener('shown.bs.tab', function () {
        if (!alertManagementInitialized) {
            alertManagementInitialized = true;
            initializeAlertManagement();
        } else {
            loadAdminAlerts();
        }
    });
}

// Alert management initialization and data loading
function initializeAlertManagement() {
    loadAdminAlerts();
    const searchInput = document.getElementById('alertSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', onAlertSearchChanged);
    }
    const includeExpiredToggle = document.getElementById('includeExpiredAlertsToggle');
    if (includeExpiredToggle) {
        includeExpiredToggle.addEventListener('change', (event) => {
            adminAlertFilters.includeExpired = !!event.target.checked;
            loadAdminAlerts();
        });
    }
    const refreshButton = document.getElementById('refreshAlertListButton');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => loadAdminAlerts(true));
    }
    const editForm = document.getElementById('editAlertForm');
    if (editForm) {
        editForm.addEventListener('submit', submitAlertEdit);
    }
    const editModalElement = document.getElementById('editAlertModal');
    if (editModalElement) {
        // Move to <body> so Bootstrap modal z-index renders above the sticky navbar
        // stacking context created by its backdrop-filter property.
        document.body.appendChild(editModalElement);
        editAlertModal = new bootstrap.Modal(editModalElement);
        editModalElement.addEventListener('hidden.bs.modal', resetAlertEditForm);
    }
}
function onAlertSearchChanged(event) {
    const value = event.target ? event.target.value.trim() : '';
    adminAlertFilters.search = value;
    if (alertSearchTimeout) {
        clearTimeout(alertSearchTimeout);
    }
    alertSearchTimeout = setTimeout(() => {
        loadAdminAlerts();
    }, 400);
}
async function loadAdminAlerts(showRefreshNotice = false) {
    const listContainer = document.getElementById('adminAlertList');
    const metaContainer = document.getElementById('adminAlertListMeta');
    if (listContainer) {
        listContainer.innerHTML = `
        <div class="text-center py-4">
        <div class="loading-spinner"></div>
        <span class="ms-2">Loading alerts...</span>
        </div>
        `;
    }
    if (metaContainer) {
        metaContainer.textContent = '';
    }
    const params = new URLSearchParams();
    if (adminAlertFilters.includeExpired) {
        params.set('include_expired', 'true');
    }
    if (adminAlertFilters.search) {
        params.set('search', adminAlertFilters.search);
    }
    const queryString = params.toString();
    const url = queryString ? `/admin/alerts?${queryString}` : '/admin/alerts';
    try {
        const response = await fetch(url);
        const result = await response.json();
        if (!response.ok || (result && result.error)) {
            throw new Error((result && result.error) || 'Failed to load alerts.');
        }
        adminAlerts = Array.isArray(result.alerts) ? result.alerts : [];
        renderAdminAlertList(result);
        if (showRefreshNotice) {
            showStatus('✅ Alert list refreshed.', 'success', 2500);
        }
    } catch (error) {
        if (listContainer) {
            listContainer.innerHTML = `<div class="alert alert-danger">Failed to load alerts: ${escapeHtml(error.message)}</div>`;
        }
        if (metaContainer) {
            metaContainer.textContent = '';
        }
        showStatus(`❌ Failed to load alerts: ${error.message}`, 'danger');
    }
}
function renderAdminAlertList(payload) {
    const listContainer = document.getElementById('adminAlertList');
    const metaContainer = document.getElementById('adminAlertListMeta');
    if (!listContainer) {
        return;
    }
    const alerts = Array.isArray(adminAlerts) ? adminAlerts : [];
    if (metaContainer) {
        const total = typeof payload.total === 'number' ? payload.total : alerts.length;
        const returned = typeof payload.returned === 'number' ? payload.returned : alerts.length;
        const descriptor = payload.include_expired ? 'including expired alerts' : 'active alerts only';
        const countText = total !== returned ? `${returned} of ${total}` : `${returned}`;
        metaContainer.textContent = alerts.length ? `${countText} displayed (${descriptor})` : '';
    }
    if (!alerts.length) {
        listContainer.innerHTML = '<div class="alert alert-info">No alerts found for the selected filters.</div>';
        return;
    }
    const rows = alerts.map(renderAdminAlertRow).join('');
    listContainer.innerHTML = `
    <div class="table-responsive">
    <table class="table table-sm table-striped align-middle mb-0">
    <thead>
    <tr>
    <th>Event</th>
    <th class="text-nowrap">Issued</th>
    <th class="text-nowrap">Expires</th>
    <th class="text-nowrap">Status</th>
    <th class="text-end">Actions</th>
    </tr>
    </thead>
    <tbody>${rows}</tbody>
    </table>
    </div>
    `;
}
function renderAdminAlertRow(alert) {
    const eventLabel = escapeHtml(alert.event || 'Unknown');
    const identifier = escapeHtml(alert.identifier || '');
    const headline = alert.headline ? `<div class="small text-muted">${escapeHtml(alert.headline)}</div>` : '';
    const areaDesc = alert.area_desc
    ? `<div class="small text-muted" title="${escapeHtml(alert.area_desc)}">${escapeHtml(alert.area_desc.length > 140 ? `${alert.area_desc.slice(0, 137)}…` : alert.area_desc)}</div>`
    : '';
    const metadataBadges = [
    renderSeverityBadge(alert.severity),
    renderUrgencyBadge(alert.urgency),
    renderCertaintyBadge(alert.certainty)
    ].filter(Boolean).join(' ');
    return `
    <tr>
    <td>
    <div class="fw-semibold">${eventLabel}</div>
    ${headline}
    <div class="small text-muted">ID: <code>${identifier}</code></div>
    ${areaDesc}
    ${metadataBadges ? `<div class="small mt-1">${metadataBadges}</div>` : ''}
    </td>
    <td class="text-nowrap">${formatDateTimeDisplay(alert.sent)}</td>
    <td class="text-nowrap">${formatDateTimeDisplay(alert.expires)}</td>
    <td class="text-nowrap">${renderStatusBadge(alert.status)}</td>
    <td class="text-end text-nowrap">
    <button class="btn btn-sm btn-outline-primary me-2" type="button" onclick="openEditAlert(${alert.id})">
    <i class="fas fa-edit"></i> Edit
    </button>
    <button class="btn btn-sm btn-outline-danger" type="button" onclick="promptDeleteAlert(${alert.id})">
    <i class="fas fa-trash-alt"></i>
    </button>
    </td>
    </tr>
    `;
}
function renderSeverityBadge(severity) {
    if (!severity) {
        return '';
    }
    const normalized = severity.toLowerCase();
    let badgeClass = 'bg-secondary';
    if (normalized === 'extreme') {
        badgeClass = 'bg-danger';
    } else if (normalized === 'severe') {
        badgeClass = 'bg-warning text-dark';
    } else if (normalized === 'moderate') {
        badgeClass = 'bg-info text-dark';
    } else if (normalized === 'minor') {
        badgeClass = 'bg-success';
    }
    return `<span class="badge ${badgeClass} me-1">${escapeHtml(severity)}</span>`;
}
function renderUrgencyBadge(urgency) {
    if (!urgency) {
        return '';
    }
    const normalized = urgency.toLowerCase();
    let badgeClass = 'bg-secondary';
    if (normalized === 'immediate') {
        badgeClass = 'bg-danger';
    } else if (normalized === 'expected') {
        badgeClass = 'bg-warning text-dark';
    } else if (normalized === 'future') {
        badgeClass = 'bg-info text-dark';
    }
    return `<span class="badge ${badgeClass} me-1">${escapeHtml(urgency)}</span>`;
}
function renderCertaintyBadge(certainty) {
    if (!certainty) {
        return '';
    }
    const normalized = certainty.toLowerCase();
    let badgeClass = 'bg-secondary';
    if (normalized === 'observed') {
        badgeClass = 'bg-primary';
    } else if (normalized === 'likely') {
        badgeClass = 'bg-success';
    } else if (normalized === 'possible') {
        badgeClass = 'bg-warning text-dark';
    }
    return `<span class="badge ${badgeClass}">${escapeHtml(certainty)}</span>`;
}
function renderStatusBadge(status) {
    if (!status) {
        return '<span class="badge bg-secondary">Unknown</span>';
    }
    const normalized = status.toLowerCase();
    let badgeClass = 'bg-secondary';
    if (normalized === 'expired') {
        badgeClass = 'bg-dark';
    } else if (normalized === 'actual' || normalized === 'active') {
        badgeClass = 'bg-success';
    } else if (normalized === 'test') {
        badgeClass = 'bg-info text-dark';
    }
    return `<span class="badge ${badgeClass}">${escapeHtml(status)}</span>`;
}

// Alert editing and deletion
function openEditAlert(alertId) {
    const target = adminAlerts.find(alert => alert.id === alertId);
    if (!target) {
        showStatus('Selected alert could not be found. Refresh the list and try again.', 'warning');
        return;
    }
    editingAlertId = alertId;
    const identifierLabel = document.getElementById('editAlertIdentifier');
    if (identifierLabel) {
        identifierLabel.textContent = target.identifier || '';
    }
    setInputValue('editAlertEvent', target.event);
    setInputValue('editAlertStatus', target.status);
    setInputValue('editAlertSeverity', target.severity);
    setInputValue('editAlertUrgency', target.urgency);
    setInputValue('editAlertCertainty', target.certainty);
    setInputValue('editAlertCategory', target.category);
    setInputValue('editAlertHeadline', target.headline);
    setInputValue('editAlertDescription', target.description);
    setInputValue('editAlertInstruction', target.instruction);
    setInputValue('editAlertAreaDesc', target.area_desc);
    const expiresInput = document.getElementById('editAlertExpires');
    if (expiresInput) {
        expiresInput.value = isoToLocalInputValue(target.expires);
    }
    if (editAlertModal) {
        editAlertModal.show();
    }
}
function resetAlertEditForm() {
    editingAlertId = null;
    const form = document.getElementById('editAlertForm');
    if (form) {
        form.reset();
    }
    const identifierLabel = document.getElementById('editAlertIdentifier');
    if (identifierLabel) {
        identifierLabel.textContent = '';
    }
}
function promptDeleteAlert(alertId) {
    const target = adminAlerts.find(alert => alert.id === alertId);
    if (!target) {
        showStatus('Selected alert could not be found. Refresh the list and try again.', 'warning');
        return;
    }
    const identifierLabel = target.identifier ? `"${target.identifier}"` : `ID ${alertId}`;
    showConfirmation({
        title: 'Delete Alert',
        message: `Delete alert ${escapeHtml(identifierLabel)}?`,
        warning: 'This will permanently remove the alert, its intersections, and related LED messages.',
        type: 'danger',
        confirmText: 'Delete Alert',
        onConfirm: () => deleteAlert(alertId)
    });
}
async function deleteAlert(alertId) {
    try {
        const response = await fetch(`/admin/alerts/${alertId}`, { method: 'DELETE' });
        const result = await response.json();
        if (!response.ok || (result && result.error)) {
            throw new Error((result && result.error) || 'Failed to delete alert.');
        }
        showStatus(result.message || 'Alert deleted.', 'success');
        await loadAdminAlerts();
    } catch (error) {
        showStatus(`❌ Failed to delete alert: ${error.message}`, 'danger');
    }
}
async function submitAlertEdit(event) {
    event.preventDefault();
    if (!editingAlertId) {
        showStatus('No alert selected for editing.', 'warning');
        return;
    }
    const eventValue = (document.getElementById('editAlertEvent')?.value || '').trim();
    const statusValue = (document.getElementById('editAlertStatus')?.value || '').trim();
    if (!eventValue) {
        showStatus('Event name is required.', 'warning');
        return;
    }
    if (!statusValue) {
        showStatus('Status is required.', 'warning');
        return;
    }
    const payload = {
        event: eventValue,
        status: statusValue,
        severity: (document.getElementById('editAlertSeverity')?.value || '').trim() || null,
        urgency: (document.getElementById('editAlertUrgency')?.value || '').trim() || null,
        certainty: (document.getElementById('editAlertCertainty')?.value || '').trim() || null,
        category: (document.getElementById('editAlertCategory')?.value || '').trim() || null,
        headline: (document.getElementById('editAlertHeadline')?.value || '').trim() || null,
        description: (document.getElementById('editAlertDescription')?.value || '').trim() || null,
        instruction: (document.getElementById('editAlertInstruction')?.value || '').trim() || null,
        area_desc: (document.getElementById('editAlertAreaDesc')?.value || '').trim() || null,
    };
    const expiresValue = document.getElementById('editAlertExpires')?.value || '';
    if (expiresValue) {
        const isoValue = localInputToIso(expiresValue);
        if (!isoValue) {
            showStatus('Expiration time could not be parsed. Please provide a valid date and time.', 'warning');
            return;
        }
        payload.expires = isoValue;
    } else {
        payload.expires = null;
    }
    try {
        const response = await fetch(`/admin/alerts/${editingAlertId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || (result && result.error)) {
            throw new Error((result && result.error) || 'Failed to update alert.');
        }
        showStatus(result.message || 'Alert updated successfully.', 'success');
        if (editAlertModal) {
            editAlertModal.hide();
        }
        await loadAdminAlerts();
    } catch (error) {
        showStatus(`❌ Failed to update alert: ${error.message}`, 'danger');
    }
}
// File upload handling
// Note: this handles the Data tab's boundary-upload form despite living in
// alert-management.js -- historical, not a naming mistake worth chasing
// down right now. Guarded (unlike alert-management's own init below, this
// runs unconditionally at script-parse time) so this file can be loaded on
// pages that don't have the boundary-upload markup, like the standalone
// Alert Management page.
const boundaryUploadForm = document.getElementById('uploadForm');
if (boundaryUploadForm) {
boundaryUploadForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    let selection;
    try {
        selection = getSelectedBoundaryType('boundaryType', 'customBoundaryType');
    } catch (error) {
        showStatus(error.message, 'warning');
        return;
    }
    if (!selection.type) {
        showStatus('Please select a boundary type before uploading.', 'warning');
        return;
    }
    const formData = new FormData(this);
    formData.set('boundary_type', selection.type);
    const submitBtn = this.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="loading-spinner"></span> Uploading...';
    submitBtn.disabled = true;
    try {
        const response = await fetch('/admin/upload_boundaries', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        if (response.ok) {
            showStatus(`✅ ${result.success}`, 'success');
            this.reset();
            initializeCustomTypeControls();
            loadBoundaries();
        } else {
            showStatus(`❌ ${result.error}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Upload error: ${error.message}`, 'danger');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
});
}

// Shapefile upload handling
const shapefileUploadForm = document.getElementById('shapefileUploadForm');
if (shapefileUploadForm) {
shapefileUploadForm.addEventListener('submit', async function(e) {
    e.preventDefault();

    const boundaryType = document.getElementById('shapefileBoundaryType').value;
    if (!boundaryType) {
        showShapefileStatus('Please select a boundary type.', 'warning');
        return;
    }

    const formData = new FormData(this);
    const submitBtn = this.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="loading-spinner"></span> Converting...';
    submitBtn.disabled = true;

    try {
        const response = await fetch('/admin/upload_shapefile', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (response.ok) {
            showShapefileStatus(
            `✅ ${result.success}<br>` +
            `<small>Added ${result.boundaries_added} features to database</small>`,
            'success'
            );
            this.reset();
            loadBoundaries();
        } else {
            showShapefileStatus(`❌ ${result.error}`, 'danger');
        }
    } catch (error) {
        showShapefileStatus(`❌ Upload error: ${error.message}`, 'danger');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
});
}

// Load shapefiles available on server

// Expired alerts management
async function markExpiredAlerts() {
    try {
        const response = await fetch('/admin/mark_expired', { method: 'POST' });
        const result = await response.json();
        if (response.ok) {
            showStatus(`✅ ${result.message}`, 'success');
            if (result.note) {
                showStatus(`ℹ️ ${result.note}`, 'info', 3000);
            }
        } else {
            showStatus(`❌ ${result.error}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
}
async function clearExpiredAlerts() {
    try {
        // First request to get confirmation details
        const response = await fetch('/admin/clear_expired', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const result = await response.json();
        if (result.requires_confirmation) {
            showConfirmation({
                title: '⚠️ PERMANENT DELETION WARNING',
                message: result.message,
                warning: result.warning,
                type: 'danger',
                confirmText: 'DELETE PERMANENTLY',
                onConfirm: async () => {
                    try {
                        const confirmResponse = await fetch('/admin/clear_expired', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ confirmed: true })
                        });
                        const confirmResult = await confirmResponse.json();
                        if (confirmResponse.ok) {
                            showStatus(`✅ ${confirmResult.message}`, 'success');
                            if (confirmResult.warning) {
                                showStatus(`⚠️ ${confirmResult.warning}`, 'warning', 5000);
                            }
                        } else {
                            showStatus(`❌ ${confirmResult.error}`, 'danger');
                        }
                    } catch (error) {
                        showStatus(`❌ Error: ${error.message}`, 'danger');
                    }
                }
            });
        } else {
            showStatus(`ℹ️ ${result.message}`, 'info');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
}
// Boundary Management Functions


// Export functions to window for global access
window.initializeAlertManagement = initializeAlertManagement;
window.loadAdminAlerts = loadAdminAlerts;
window.openEditAlert = openEditAlert;
window.deleteAlert = deleteAlert;
window.promptDeleteAlert = promptDeleteAlert;
window.markExpiredAlerts = markExpiredAlerts;
window.clearExpiredAlerts = clearExpiredAlerts;
