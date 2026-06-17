/*
 * Security Center page controller.
 *
 * Drives the four tabs of the unified Security Center:
 *   - Traffic        : lazy-loads the existing dashboard in an iframe
 *   - Malicious Logins: malicious attempt stats + table
 *   - Banned IPs      : allowlist/blocklist (IP filter) management
 *   - fail2ban        : recommended jail/filter configuration
 *
 * All endpoints already existed under /security/* and /api/traffic/*; this
 * file simply orchestrates them on one page. The traffic dashboard keeps its
 * own (heavyweight, chart-driven) JS isolated inside the iframe so there are
 * no global-scope collisions with the code below.
 */
'use strict';

let currentPage = 1;
let addFilterModal = null;

function notify(message, isError) {
    if (typeof window.showToast === 'function') {
        window.showToast(message, isError ? 'error' : 'success');
    } else {
        // eslint-disable-next-line no-alert
        alert(message);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', function () {
    addFilterModal = new bootstrap.Modal(document.getElementById('addFilterModal'));

    // The Traffic tab is active on first paint — load its iframe immediately.
    loadTrafficFrame();
    // Lazy-load the iframe the first time the tab is shown (covers deep-links
    // that open another tab first, e.g. #malicious).
    const trafficTab = document.getElementById('traffic-tab');
    if (trafficTab) {
        trafficTab.addEventListener('shown.bs.tab', loadTrafficFrame);
    }

    loadAttempts();
    loadIPFilters();
    populateFail2banConfig();

    // Honour a #hash so legacy /security/malicious-logins redirects land on
    // the right tab.
    activateTabFromHash();
    window.addEventListener('hashchange', activateTabFromHash);
});

function activateTabFromHash() {
    const map = {
        '#traffic': 'traffic-tab',
        '#malicious': 'malicious-tab',
        '#bans': 'bans-tab',
        '#fail2ban': 'fail2ban-tab',
    };
    const tabId = map[window.location.hash];
    if (tabId) {
        const el = document.getElementById(tabId);
        if (el) bootstrap.Tab.getOrCreateInstance(el).show();
    }
}

function loadTrafficFrame() {
    const frame = document.getElementById('trafficFrame');
    if (frame && !frame.src && frame.dataset.src) {
        frame.src = frame.dataset.src;
    }
}

/* ------------------------------------------------------------------ */
/* Malicious login attempts                                            */
/* ------------------------------------------------------------------ */

function loadAttempts() {
    const days = document.getElementById('days-filter').value;
    const perPage = document.getElementById('per-page-filter').value;

    fetch(`/security/malicious-login-attempts?page=${currentPage}&days=${days}&per_page=${perPage}`)
        .then(response => response.json())
        .then(data => {
            displayAttempts(data.logs);
            displayStatistics(data);
            displayIPStats(data.ip_statistics);
            updatePagination(data);
        })
        .catch(error => {
            console.error('Error loading attempts:', error);
            document.getElementById('attempts-tbody').innerHTML =
                '<tr><td colspan="5" class="text-center text-danger">Error loading attempts</td></tr>';
        });
}

function displayAttempts(logs) {
    const tbody = document.getElementById('attempts-tbody');
    if (!logs || logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No malicious attempts found</td></tr>';
        return;
    }
    tbody.innerHTML = logs.map(log => {
        const timestamp = new Date(log.timestamp).toLocaleString();
        const reason = (log.details && log.details.reason) || 'unknown';
        const detailsStr = JSON.stringify(log.details, null, 2);
        return `
            <tr>
                <td data-label="Timestamp">${escapeHtml(timestamp)}</td>
                <td data-label="IP Address" class="admin-mono-badge">${escapeHtml(log.ip_address || 'N/A')}</td>
                <td data-label="Username Attempted"><code>${escapeHtml(log.username || 'N/A')}</code></td>
                <td data-label="Type"><span class="admin-badge admin-badge-danger">${escapeHtml(reason)}</span></td>
                <td data-label="Details"><div class="admin-output-box admin-output-box-compact">${escapeHtml(detailsStr)}</div></td>
            </tr>`;
    }).join('');
}

function displayStatistics(data) {
    document.getElementById('total-attempts').textContent = data.total || 0;
    document.getElementById('unique-ips').textContent = Object.keys(data.ip_statistics || {}).length;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayAttempts = (data.logs || []).filter(log => new Date(log.timestamp) >= today).length;
    document.getElementById('today-attempts').textContent = todayAttempts;
}

function displayIPStats(ipStats) {
    const container = document.getElementById('ip-statistics');
    if (!ipStats || Object.keys(ipStats).length === 0) {
        container.innerHTML = '<p class="text-center text-muted">No IP statistics available</p>';
        return;
    }
    const sorted = Object.entries(ipStats).sort((a, b) => b[1].count - a[1].count).slice(0, 10);
    container.innerHTML = sorted.map(([ip, stats]) => `
        <div class="ip-stat-item">
            <div>
                <strong class="admin-mono-badge">${escapeHtml(ip)}</strong><br>
                <small class="text-muted">
                    Last: ${escapeHtml(new Date(stats.last_attempt).toLocaleString())}
                    | Usernames: ${escapeHtml((stats.usernames || []).join(', '))}
                </small>
            </div>
            <div>
                <span class="admin-badge admin-badge-danger me-2">${stats.count} attempts</span>
                <button class="btn btn-sm btn-danger" onclick="banIPFromStats('${escapeHtml(ip)}')" title="Ban this IP">
                    <i class="bi bi-ban"></i> Ban
                </button>
            </div>
        </div>`).join('');
}

function updatePagination(data) {
    document.getElementById('pagination-info').textContent =
        `Showing ${data.logs.length} of ${data.total} attempts`;
    const controls = document.getElementById('pagination-controls');
    if (data.pages <= 1) { controls.innerHTML = ''; return; }

    let html = '<nav><ul class="pagination pagination-sm mb-0">';
    if (currentPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="changePage(${currentPage - 1}); return false;">Previous</a></li>`;
    }
    for (let i = Math.max(1, currentPage - 2); i <= Math.min(data.pages, currentPage + 2); i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="changePage(${i}); return false;">${i}</a></li>`;
    }
    if (currentPage < data.pages) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="changePage(${currentPage + 1}); return false;">Next</a></li>`;
    }
    html += '</ul></nav>';
    controls.innerHTML = html;
}

function changePage(page) {
    currentPage = page;
    loadAttempts();
}

/* ------------------------------------------------------------------ */
/* IP filter (ban) management                                          */
/* ------------------------------------------------------------------ */

function loadIPFilters() {
    fetch('/security/ip-filters')
        .then(response => response.json())
        .then(data => displayIPFilters(data.filters))
        .catch(error => {
            console.error('Error loading IP filters:', error);
            document.getElementById('ip-filters-list').innerHTML =
                '<p class="text-center text-danger">Error loading IP filters</p>';
        });
}

function renderFilterRows(filters, isBlock) {
    return filters.map(filter => {
        const expires = filter.expires_at ? new Date(filter.expires_at).toLocaleString() : 'Never';
        const statusClass = filter.is_active ? (isBlock ? 'bg-danger' : 'bg-success') : 'bg-secondary';
        const reasonCell = isBlock
            ? `<td data-label="Reason"><span class="badge bg-danger">${escapeHtml(filter.reason)}</span></td>` : '';
        const expiresCell = isBlock ? `<td data-label="Expires">${escapeHtml(expires)}</td>` : '';
        return `
            <tr>
                <td data-label="IP/Range" class="admin-mono-badge">${escapeHtml(filter.ip_address)}</td>
                ${reasonCell}
                <td data-label="Description">${escapeHtml(filter.description || '-')}</td>
                ${expiresCell}
                <td data-label="Created">${escapeHtml(new Date(filter.created_at).toLocaleString())}</td>
                <td data-label="Status"><span class="badge ${statusClass}">${filter.is_active ? 'Active' : 'Inactive'}</span></td>
                <td>
                    <button class="btn btn-sm btn-warning" onclick="toggleFilter(${filter.id})" title="Toggle active">
                        <i class="bi bi-toggle-${filter.is_active ? 'on' : 'off'}"></i>
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteFilter(${filter.id})" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>`;
    }).join('');
}

function displayIPFilters(filters) {
    const container = document.getElementById('ip-filters-list');
    if (!filters || filters.length === 0) {
        container.innerHTML = '<p class="text-center text-muted">No IP filters configured</p>';
        return;
    }
    const allowlist = filters.filter(f => f.filter_type === 'allowlist');
    const blocklist = filters.filter(f => f.filter_type === 'blocklist');
    let html = '';

    if (blocklist.length > 0) {
        html += '<h6 class="text-danger"><i class="bi bi-ban"></i> Blocklist (banned)</h6>';
        html += '<div class="table-responsive mb-4"><table class="table eas-table table-sm">';
        html += '<thead><tr><th>IP/Range</th><th>Reason</th><th>Description</th><th>Expires</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>';
        html += `<tbody>${renderFilterRows(blocklist, true)}</tbody></table></div>`;
    }
    if (allowlist.length > 0) {
        html += '<h6 class="text-success"><i class="bi bi-check-circle"></i> Allowlist</h6>';
        html += '<div class="table-responsive"><table class="table eas-table table-sm">';
        html += '<thead><tr><th>IP/Range</th><th>Description</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>';
        html += `<tbody>${renderFilterRows(allowlist, false)}</tbody></table></div>`;
    }
    container.innerHTML = html;
}

function showAddFilterModal(filterType) {
    document.getElementById('filter-type').value = filterType;
    document.getElementById('filter-ip').value = '';
    document.getElementById('filter-description').value = '';
    document.getElementById('filter-expires').value = '';
    document.getElementById('addFilterModalTitle').textContent =
        filterType === 'allowlist' ? 'Add to Allowlist' : 'Ban an IP Address';
    document.getElementById('expires-field').style.display =
        filterType === 'blocklist' ? 'block' : 'none';
    addFilterModal.show();
}

function submitIPFilter() {
    const formData = {
        ip_address: document.getElementById('filter-ip').value.trim(),
        filter_type: document.getElementById('filter-type').value,
        description: document.getElementById('filter-description').value,
    };
    if (!formData.ip_address) { notify('IP address is required', true); return; }

    const expiresValue = document.getElementById('filter-expires').value;
    if (expiresValue && formData.filter_type === 'blocklist') {
        formData.expires_in_hours = parseInt(expiresValue, 10);
    }

    fetch('/security/ip-filters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
    })
        .then(response => response.json())
        .then(data => {
            if (data.error) { notify('Error: ' + data.error, true); return; }
            addFilterModal.hide();
            loadIPFilters();
            notify('IP filter saved');
        })
        .catch(error => notify('Error saving filter: ' + error, true));
}

function banIPFromStats(ip) {
    // eslint-disable-next-line no-alert
    const description = prompt(`Enter a description for banning ${ip}:`, 'Manual ban from malicious-login stats');
    if (!description) return;

    fetch('/security/ip-filters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip_address: ip, filter_type: 'blocklist', description: description }),
    })
        .then(response => response.json())
        .then(data => {
            if (data.error) { notify('Error: ' + data.error, true); return; }
            loadIPFilters();
            notify(`IP ${ip} has been banned`);
        })
        .catch(error => notify('Error banning IP: ' + error, true));
}

function deleteFilter(filterId) {
    // eslint-disable-next-line no-alert
    if (!confirm('Delete this IP filter?')) return;
    fetch(`/security/ip-filters/${filterId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.error) { notify('Error: ' + data.error, true); return; }
            loadIPFilters();
            notify('IP filter deleted');
        })
        .catch(error => notify('Error deleting filter: ' + error, true));
}

function toggleFilter(filterId) {
    fetch(`/security/ip-filters/${filterId}/toggle`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.error) { notify('Error: ' + data.error, true); return; }
            loadIPFilters();
        })
        .catch(error => notify('Error toggling filter: ' + error, true));
}

function cleanupExpiredFilters() {
    fetch('/security/ip-filters/cleanup', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            loadIPFilters();
            notify(`Cleaned up ${data.cleaned_up || 0} expired filter(s)`);
        })
        .catch(error => notify('Error cleaning up filters: ' + error, true));
}

/* ------------------------------------------------------------------ */
/* fail2ban configuration                                              */
/* ------------------------------------------------------------------ */

function populateFail2banConfig() {
    const jailConfig = `[eas-station-malicious]
enabled = true
port = http,https
filter = eas-station-malicious
logpath = /var/log/eas-station/security.log
maxretry = 1
bantime = 3600
findtime = 600`;

    const filterConfig = `[Definition]
failregex = ^.*MALICIOUS_LOGIN from <HOST>.*$
ignoreregex =`;

    document.getElementById('jail-config').textContent = jailConfig;
    document.getElementById('filter-config').textContent = filterConfig;
}

function copyToClipboard(elementId) {
    const text = document.getElementById(elementId).textContent;
    navigator.clipboard.writeText(text).then(() => notify('Copied to clipboard'));
}
