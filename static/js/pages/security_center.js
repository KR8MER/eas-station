/*
 * Security Center tab controller.
 *
 * Drives three of the four Security Center tabs:
 *   - Malicious Logins : malicious attempt stats + table
 *   - Banned IPs       : allowlist/blocklist (IP filter) management
 *   - fail2ban         : install/configure/apply host-level jails + unban
 *
 * The Traffic tab is the full traffic dashboard, rendered natively from
 * templates/security/_traffic_content.html with its own scripts loaded just
 * before this file. To guarantee there is never a global-scope collision with
 * that (large) dashboard code, everything here lives inside an IIFE and only
 * the handlers referenced by inline onclick= are exported on window.SC.
 */
(function () {
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

    function esc(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : text;
        return div.innerHTML;
    }

    document.addEventListener('DOMContentLoaded', function () {
        addFilterModal = new bootstrap.Modal(document.getElementById('addFilterModal'));

        loadAttempts();
        loadIPFilters();
        loadFail2banStatus();

        // Honour a #hash so the legacy /security/malicious-logins redirect (and
        // any deep link) opens the right tab.
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

    /* -------------------------------------------------------------- */
    /* Malicious login attempts                                       */
    /* -------------------------------------------------------------- */

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
                    <td data-label="Timestamp">${esc(timestamp)}</td>
                    <td data-label="IP Address" class="admin-mono-badge">${esc(log.ip_address || 'N/A')}</td>
                    <td data-label="Username Attempted"><code>${esc(log.username || 'N/A')}</code></td>
                    <td data-label="Type"><span class="admin-badge admin-badge-danger">${esc(reason)}</span></td>
                    <td data-label="Details"><div class="admin-output-box admin-output-box-compact">${esc(detailsStr)}</div></td>
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
                    <strong class="admin-mono-badge">${esc(ip)}</strong><br>
                    <small class="text-muted">
                        Last: ${esc(new Date(stats.last_attempt).toLocaleString())}
                        | Usernames: ${esc((stats.usernames || []).join(', '))}
                    </small>
                </div>
                <div>
                    <span class="admin-badge admin-badge-danger me-2">${stats.count} attempts</span>
                    <button class="btn btn-sm btn-danger" onclick="SC.banIPFromStats('${esc(ip)}')" title="Ban this IP">
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
            html += `<li class="page-item"><a class="page-link" href="#" onclick="SC.changePage(${currentPage - 1}); return false;">Previous</a></li>`;
        }
        for (let i = Math.max(1, currentPage - 2); i <= Math.min(data.pages, currentPage + 2); i++) {
            html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="SC.changePage(${i}); return false;">${i}</a></li>`;
        }
        if (currentPage < data.pages) {
            html += `<li class="page-item"><a class="page-link" href="#" onclick="SC.changePage(${currentPage + 1}); return false;">Next</a></li>`;
        }
        html += '</ul></nav>';
        controls.innerHTML = html;
    }

    function changePage(page) {
        currentPage = page;
        loadAttempts();
    }

    /* -------------------------------------------------------------- */
    /* IP filter (ban) management                                     */
    /* -------------------------------------------------------------- */

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
                ? `<td data-label="Reason"><span class="badge bg-danger">${esc(filter.reason)}</span></td>` : '';
            const expiresCell = isBlock ? `<td data-label="Expires">${esc(expires)}</td>` : '';
            return `
                <tr>
                    <td data-label="IP/Range" class="admin-mono-badge">${esc(filter.ip_address)}</td>
                    ${reasonCell}
                    <td data-label="Description">${esc(filter.description || '-')}</td>
                    ${expiresCell}
                    <td data-label="Created">${esc(new Date(filter.created_at).toLocaleString())}</td>
                    <td data-label="Status"><span class="badge ${statusClass}">${filter.is_active ? 'Active' : 'Inactive'}</span></td>
                    <td>
                        <button class="btn btn-sm btn-warning" onclick="SC.toggleFilter(${filter.id})" title="Toggle active">
                            <i class="bi bi-toggle-${filter.is_active ? 'on' : 'off'}"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="SC.deleteFilter(${filter.id})" title="Delete">
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

    /* -------------------------------------------------------------- */
    /* fail2ban configuration                                         */
    /* -------------------------------------------------------------- */

    const F2B_API = '/admin/fail2ban';

    function setVal(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value;
    }

    function setChecked(id, value) {
        const el = document.getElementById(id);
        if (el) el.checked = !!value;
    }

    function applySettingsToForm(s) {
        if (!s) return;
        setChecked('f2b-enabled', s.enabled);
        setVal('f2b-maxretry', s.maxretry);
        setVal('f2b-bantime', s.bantime);
        setVal('f2b-findtime', s.findtime);
        setChecked('f2b-protect-auth', s.protect_auth);
        setVal('f2b-auth-maxretry', s.auth_maxretry);
        setVal('f2b-auth-bantime', s.auth_bantime);
        setChecked('f2b-protect-ssh', s.protect_ssh);
        setVal('f2b-ssh-maxretry', s.ssh_maxretry);
        setVal('f2b-ssh-bantime', s.ssh_bantime);
    }

    function renderFail2banStatus(data) {
        const statusEl = document.getElementById('f2b-status');
        const installBtn = document.getElementById('f2b-install-btn');
        if (!statusEl) return;

        const badge = (ok, yes, no) =>
            `<span class="badge bg-${ok ? 'success' : 'secondary'}">${ok ? yes : no}</span>`;

        let html = '<div class="d-flex gap-3 flex-wrap align-items-center">';
        html += `<div>Installed: ${badge(data.installed, 'Yes', 'No')}</div>`;
        html += `<div>Service: ${badge(data.active, 'Running', 'Stopped')}</div>`;
        if (data.loaded_jails && data.loaded_jails.length) {
            html += `<div>Active jails: <code class="text-break-anywhere">${esc(data.loaded_jails.join(', '))}</code></div>`;
        }
        html += '</div>';
        if (!data.installed) {
            html += '<p class="text-muted small mb-0 mt-2">fail2ban is not installed on this host. ' +
                'Click <strong>Install fail2ban</strong>, then configure the jails below.</p>';
        }
        statusEl.innerHTML = html;

        if (installBtn) installBtn.style.display = data.installed ? 'none' : '';

        // Render banned IPs
        const listEl = document.getElementById('f2b-banned-list');
        if (listEl) {
            const banned = data.banned || {};
            const rows = [];
            Object.keys(banned).forEach(jail => {
                (banned[jail] || []).forEach(ip => rows.push({ jail, ip }));
            });
            if (!rows.length) {
                listEl.innerHTML = '<p class="text-muted mb-0">No host-level bans, or fail2ban is not active.</p>';
            } else {
                let t = '<div class="table-responsive"><table class="table eas-table mb-0"><thead><tr>' +
                    '<th>IP Address</th><th>Jail</th><th class="text-end">Action</th></tr></thead><tbody>';
                rows.forEach(r => {
                    t += `<tr><td class="text-break-anywhere">${esc(r.ip)}</td>` +
                        `<td><code class="text-break-anywhere">${esc(r.jail)}</code></td>` +
                        `<td class="text-end"><button class="btn btn-sm btn-outline-success" ` +
                        `onclick="SC.unbanIP('${esc(r.ip)}','${esc(r.jail)}')">` +
                        '<i class="bi bi-unlock"></i> Unban</button></td></tr>';
                });
                t += '</tbody></table></div>';
                listEl.innerHTML = t;
            }
        }
    }

    function loadFail2banStatus() {
        fetch(`${F2B_API}/status`)
            .then(r => r.json())
            .then(data => {
                applySettingsToForm(data.settings);
                renderFail2banStatus(data);
            })
            .catch(error => notify('Error loading fail2ban status: ' + error, true));
    }

    function installFail2ban() {
        notify('Installing fail2ban… this may take a minute.');
        fetch(`${F2B_API}/install`, { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    notify(data.message || 'fail2ban installed.');
                    loadFail2banStatus();
                } else {
                    notify(data.error || 'Install failed', true);
                }
            })
            .catch(error => notify('Error installing fail2ban: ' + error, true));
    }

    function serviceAction(action) {
        fetch(`${F2B_API}/service`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    notify(data.message || `fail2ban ${action}ed.`);
                    loadFail2banStatus();
                } else {
                    notify(data.error || 'Service action failed', true);
                }
            })
            .catch(error => notify('Error: ' + error, true));
    }

    function numVal(id) {
        const el = document.getElementById(id);
        return el ? parseInt(el.value, 10) : null;
    }

    function saveFail2banConfig() {
        const payload = {
            enabled: document.getElementById('f2b-enabled').checked,
            maxretry: numVal('f2b-maxretry'),
            bantime: numVal('f2b-bantime'),
            findtime: numVal('f2b-findtime'),
            protect_auth: document.getElementById('f2b-protect-auth').checked,
            auth_maxretry: numVal('f2b-auth-maxretry'),
            auth_bantime: numVal('f2b-auth-bantime'),
            protect_ssh: document.getElementById('f2b-protect-ssh').checked,
            ssh_maxretry: numVal('f2b-ssh-maxretry'),
            ssh_bantime: numVal('f2b-ssh-bantime'),
        };
        fetch(`${F2B_API}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    notify(data.message || 'Configuration saved.');
                    loadFail2banStatus();
                } else {
                    notify(data.error || 'Save failed', true);
                }
            })
            .catch(error => notify('Error saving configuration: ' + error, true));
    }

    function unbanIP(ip, jail) {
        fetch(`${F2B_API}/unban`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip_address: ip, jail: jail }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    notify(data.message || `Unbanned ${ip}.`);
                    loadFail2banStatus();
                } else {
                    notify(data.error || 'Unban failed', true);
                }
            })
            .catch(error => notify('Error unbanning IP: ' + error, true));
    }

    function manualBan() {
        const ipEl = document.getElementById('f2b-ban-ip');
        const ip = ipEl ? ipEl.value.trim() : '';
        if (!ip) {
            notify('Enter an IP address to ban.', true);
            return;
        }
        fetch(`${F2B_API}/ban`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip_address: ip }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    notify(data.message || `Banned ${ip}.`);
                    if (ipEl) ipEl.value = '';
                    loadFail2banStatus();
                } else {
                    notify(data.error || 'Ban failed', true);
                }
            })
            .catch(error => notify('Error banning IP: ' + error, true));
    }

    // Export only the handlers referenced by inline onclick=.
    window.SC = {
        loadAttempts: loadAttempts,
        changePage: changePage,
        loadIPFilters: loadIPFilters,
        showAddFilterModal: showAddFilterModal,
        submitIPFilter: submitIPFilter,
        banIPFromStats: banIPFromStats,
        deleteFilter: deleteFilter,
        toggleFilter: toggleFilter,
        cleanupExpiredFilters: cleanupExpiredFilters,
        loadFail2banStatus: loadFail2banStatus,
        installFail2ban: installFail2ban,
        serviceAction: serviceAction,
        saveFail2banConfig: saveFail2banConfig,
        unbanIP: unbanIP,
        manualBan: manualBan,
    };
})();
