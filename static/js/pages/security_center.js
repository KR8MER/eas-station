/*
 * Security Center tab controller.
 *
 * Drives three of the four Security Center tabs:
 *   - Malicious Logins : malicious attempt stats + table
 *   - Banned IPs       : allowlist/blocklist (IP filter) management
 *   - fail2ban         : firewall enforcement of the app ban list + SSH jail
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

    /* -------------------------------------------------------------- */
    /* Tab loading                                                     */
    /* -------------------------------------------------------------- */
    //
    // Each tab's data is fetched the first time that tab is shown, not on page
    // load. Loading all of them up front meant opening the page always paid for
    // the fail2ban status call (a dozen privileged `fail2ban-client` subprocess
    // round trips), the malicious-attempt query and the ban list — even for an
    // operator who only wanted the Traffic tab. On a Pi that was most of the
    // page's load time.

    const TAB_LOADERS = {
        'malicious-tab': loadAttempts,
        'bans-tab': loadIPFilters,
        'fail2ban-tab': loadFail2banStatus,
    };
    const loadedTabs = new Set();

    function loadTabOnce(tabId) {
        const loader = TAB_LOADERS[tabId];
        if (!loader || loadedTabs.has(tabId)) return;
        loadedTabs.add(tabId);
        loader();
    }

    document.addEventListener('DOMContentLoaded', function () {
        addFilterModal = new bootstrap.Modal(document.getElementById('addFilterModal'));

        // Fetch whichever tab a #hash selects (or the default active one).
        activateTabFromHash();
        window.addEventListener('hashchange', activateTabFromHash);

        // Bootstrap fires shown.bs.tab on the newly activated trigger.
        Object.keys(TAB_LOADERS).forEach(tabId => {
            const el = document.getElementById(tabId);
            if (el) {
                el.addEventListener('shown.bs.tab', () => loadTabOnce(tabId));
            }
        });

        const active = document.querySelector('#securityTabs .nav-link.active');
        if (active) loadTabOnce(active.id);
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
            if (el) {
                bootstrap.Tab.getOrCreateInstance(el).show();
                loadTabOnce(tabId);
            }
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
                    '<p class="text-center text-danger">Error loading the Global Ban List</p>';
            });
        loadSecurityOverview();
    }

    /* -------------------------------------------------------------- */
    /* Security overview: enforcement layers + metrics + sync health  */
    /* -------------------------------------------------------------- */

    function pill(ok, onText, offText) {
        return `<span class="badge ${ok ? 'bg-success' : 'bg-secondary'}">${ok ? onText : offText}</span>`;
    }

    function metricTile(value, label) {
        return '<div class="col-6 col-md">' +
            `<div class="border rounded p-2 h-100"><div class="h4 mb-0">${esc(String(value))}</div>` +
            `<div class="text-muted small">${esc(label)}</div></div></div>`;
    }

    function loadSecurityOverview() {
        const enf = document.getElementById('sec-enforcement');
        const met = document.getElementById('sec-metrics');
        const syncEl = document.getElementById('sec-sync');
        if (!enf && !met) return;
        fetch('/security/overview')
            .then(r => r.json())
            .then(data => {
                const e = data.enforcement || {};
                const m = data.metrics || {};
                const s = data.sync || {};
                if (enf) {
                    enf.innerHTML =
                        '<div class="col-6 col-md-3"><div class="text-muted small">Application gate</div>' +
                        pill(e.application, 'Enabled', 'Disabled') + '</div>' +
                        '<div class="col-6 col-md-3"><div class="text-muted small">Host firewall</div>' +
                        pill(e.host_firewall, 'Enabled', 'Disabled') + '</div>' +
                        '<div class="col-6 col-md-3"><div class="text-muted small">fail2ban service</div>' +
                        pill(e.fail2ban_service, 'Running', 'Stopped') + '</div>' +
                        '<div class="col-6 col-md-3"><div class="text-muted small">Firewall sync</div>' +
                        `<span class="badge ${s.status === 'ok' ? 'bg-success' : (s.status === 'disabled' ? 'bg-secondary' : 'bg-danger')}">` +
                        `${esc((s.status || 'unknown').toUpperCase())}</span></div>`;
                }
                if (met) {
                    met.innerHTML =
                        metricTile(m.failed_logins_24h ?? 0, 'Failed logins (24h)') +
                        metricTile(m.ips_banned_24h ?? 0, 'IPs banned (24h)') +
                        metricTile(m.active_bans ?? 0, 'Active bans') +
                        metricTile(m.ssh_attacks_blocked ?? 0, 'SSH attacks blocked') +
                        metricTile(m.mirrored_to_firewall ?? 0, 'Mirrored to firewall');
                }
                if (syncEl) {
                    if (s.status && s.status !== 'ok' && s.status !== 'disabled') {
                        const detail = s.detail
                            ? `<div class="mt-1"><small class="text-muted">fail2ban: </small>` +
                              `<code class="text-break-anywhere">${esc(s.detail)}</code></div>` : '';
                        syncEl.innerHTML = '<div class="alert alert-warning small mb-0">' +
                            '<div class="d-flex justify-content-between align-items-center flex-wrap gap-2">' +
                            `<span><i class="bi bi-exclamation-triangle-fill"></i> ${esc(s.message || '')}</span>` +
                            '<button class="btn btn-sm btn-danger" onclick="SC.resyncFirewall()">' +
                            '<i class="bi bi-arrow-left-right"></i> Resync firewall enforcement</button></div>' +
                            detail + '</div>';
                    } else if (s.message) {
                        syncEl.innerHTML = `<div class="text-muted small"><i class="bi bi-check-circle"></i> ${esc(s.message)}</div>`;
                    } else {
                        syncEl.innerHTML = '';
                    }
                }
            })
            .catch(error => {
                if (enf) enf.innerHTML = '<span class="text-danger small">Error loading enforcement status</span>';
                console.error('Error loading security overview:', error);
            });
    }

    // One-click "Resync firewall enforcement" used by the sync warning.
    function resyncFirewall() {
        fetch('/admin/fail2ban/resync', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                notify(data.success ? (data.message || 'Resynced.') : (data.error || 'Resync failed'), !data.success);
                loadSecurityOverview();
            })
            .catch(error => notify('Error resyncing: ' + error, true));
    }

    // Local flag SVG for an ISO 3166-1 alpha-2 code (bundled — no CDN calls).
    function flagImg(cc, title) {
        if (!cc || !/^[A-Za-z]{2}$/.test(cc)) return '';
        const c = cc.toLowerCase();
        return `<img src="/static/vendor/flags/${c}.svg" alt="${esc(cc.toUpperCase())}" ` +
            `title="${esc(title || cc.toUpperCase())}" class="ti-flag me-1" loading="lazy">`;
    }

    // "🏳 City, Region, Country" cell built from the geo block the API attaches.
    function locationCell(filter) {
        const loc = filter.location || {};
        const parts = [];
        if (loc.city) parts.push(loc.city);
        if (loc.region) parts.push(loc.region);
        if (loc.country) parts.push(loc.country);
        const text = parts.join(', ');
        const flag = flagImg(loc.country_code, loc.country);
        if (!flag && !text) return '<span class="text-muted">—</span>';
        return `${flag}<span class="text-break-anywhere">${esc(text || loc.country_code || '')}</span>`;
    }

    // Colored badge for the ban "source" (which detector/operator added it).
    function sourceBadge(filter) {
        const src = filter.source || 'manual';
        const label = filter.source_label || 'Manual';
        const cls = {
            manual: 'bg-secondary',
            login_brute_force: 'bg-warning text-dark',
            ssh_brute_force: 'bg-danger',
            malicious_request: 'bg-dark',
            flood: 'bg-info text-dark',
            api_abuse: 'bg-primary',
            stream_abuse: 'bg-primary',
        }[src] || 'bg-secondary';
        return `<span class="badge ${cls}">${esc(label)}</span>`;
    }

    function renderFilterRows(filters, isBlock) {
        return filters.map(filter => {
            const expires = filter.expires_at ? new Date(filter.expires_at).toLocaleString() : 'Never';
            const statusClass = filter.is_active ? (isBlock ? 'bg-danger' : 'bg-success') : 'bg-secondary';
            const sourceCell = isBlock
                ? `<td data-label="Source">${sourceBadge(filter)}</td>` : '';
            const expiresCell = isBlock ? `<td data-label="Expires">${esc(expires)}</td>` : '';
            return `
                <tr>
                    <td data-label="IP/Range" class="admin-mono-badge">${esc(filter.ip_address)}</td>
                    ${sourceCell}
                    <td data-label="Location">${locationCell(filter)}</td>
                    <td data-label="Description">${esc(filter.description || '-')}</td>
                    ${expiresCell}
                    <td data-label="Created">${esc(new Date(filter.created_at).toLocaleString())}</td>
                    <td data-label="Status"><span class="badge ${statusClass}">${filter.is_active ? 'Active' : 'Inactive'}</span></td>
                    <td data-label="Actions">
                        <button class="btn btn-sm btn-warning" onclick="SC.toggleFilter(${filter.id})"
                                title="${filter.is_active ? 'Disable this entry' : 'Enable this entry'}">
                            <i class="bi bi-toggle-${filter.is_active ? 'on' : 'off'}"></i>
                            ${filter.is_active ? 'Disable' : 'Enable'}
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="SC.deleteFilter(${filter.id})" title="Delete this entry">
                            <i class="bi bi-trash"></i> ${isBlock ? 'Remove' : 'Delete'}
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
            html += '<h6 class="text-danger"><i class="bi bi-ban"></i> Banned (blocklist)</h6>';
            html += '<div class="table-responsive mb-4"><table class="table eas-table table-sm">';
            html += '<thead><tr><th>IP/Range</th><th>Source</th><th>Location</th><th>Description</th><th>Expires</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>';
            html += `<tbody>${renderFilterRows(blocklist, true)}</tbody></table></div>`;
        }
        if (allowlist.length > 0) {
            html += '<h6 class="text-success"><i class="bi bi-check-circle"></i> Allowlist</h6>';
            html += '<div class="table-responsive"><table class="table eas-table table-sm">';
            html += '<thead><tr><th>IP/Range</th><th>Location</th><th>Description</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>';
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
        document.getElementById('allowlist-lockout-note').style.display =
            filterType === 'allowlist' ? 'block' : 'none';
        addFilterModal.show();
    }

    function submitIPFilter(confirmLockout) {
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
        if (confirmLockout) { formData.confirm_lockout = true; }

        fetch('/security/ip-filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
        })
            .then(response => response.json())
            .then(data => {
                // The server refuses an allowlist entry that would lock the
                // current admin out (allowlist-only login mode). Offer to retry
                // with explicit confirmation rather than silently failing.
                if (data.lockout_warning) {
                    // eslint-disable-next-line no-alert
                    if (window.confirm(data.message + '\n\nProceed anyway?')) {
                        submitIPFilter(true);
                    }
                    return;
                }
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
    /* fail2ban — host-firewall enforcement of the app ban list       */
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
        setChecked('f2b-protect-ssh', s.protect_ssh);
        setVal('f2b-ssh-maxretry', s.ssh_maxretry);
        setVal('f2b-ssh-bantime', s.ssh_bantime);
    }

    function renderFail2banStatus(data) {
        const statusEl = document.getElementById('f2b-status');
        if (!statusEl) return;

        const badge = (ok, yes, no) =>
            `<span class="badge bg-${ok ? 'success' : 'secondary'}">${ok ? yes : no}</span>`;

        let html = '<div class="d-flex gap-3 flex-wrap align-items-center">';
        html += `<div>Installed: ${badge(data.installed, 'Yes', 'No')}</div>`;
        html += `<div>Service: ${badge(data.active, 'Running', 'Stopped')}</div>`;
        html += `<div>Firewall enforcement: ${badge(data.enforcement_enabled, 'On', 'Off')}</div>`;
        html += '</div>';
        if (data.installed) {
            html += '<p class="text-muted small mb-0 mt-2">' +
                `Application ban list: <strong>${data.app_ban_count}</strong> active. ` +
                `Mirrored to host firewall: <strong>${data.firewall_ban_count}</strong>.</p>`;
            // The common "Mirrored: 0 while enforcement is On" case: the actuator
            // jail failed to load, so nothing reaches the firewall.
            if (data.enforcement_enabled && !data.actuator_jail_loaded) {
                const detail = data.actuator_error
                    ? '<div class="mt-1"><small>fail2ban error: </small>' +
                      `<code class="text-break-anywhere">${esc(data.actuator_error)}</code></div>` : '';
                html += '<div class="alert alert-warning small mb-0 mt-2">' +
                    '<i class="bi bi-exclamation-triangle-fill"></i> Firewall enforcement is on, but the ' +
                    '<code>eas-station</code> firewall jail isn\'t loaded — so bans aren\'t reaching the host ' +
                    'firewall. Click <strong>Save &amp; Apply Configuration</strong> below to (re)create it.' +
                    detail + '</div>';
            } else if (data.enforcement_enabled && (data.firewall_pending ?? 0) > 0) {
                html += '<div class="text-muted small mb-0 mt-1">' +
                    'Some bans aren\'t mirrored yet — click <strong>Resync bans</strong> to push them now.</div>';
            } else if (data.enforcement_enabled && data.app_ban_count > data.firewall_ban_count) {
                // The list is fully mirrored; the remaining difference is CIDR
                // ranges / loopback, which the firewall jail can't hold. Explain
                // it so the gap doesn't read as an unresolved sync problem.
                const n = data.app_ban_count - data.firewall_ban_count;
                html += '<div class="text-muted small mb-0 mt-1">' +
                    `<i class="bi bi-info-circle"></i> ${n} ban-list entr${n === 1 ? 'y' : 'ies'} ` +
                    `(IP range${n === 1 ? '' : 's'} or loopback) ${n === 1 ? 'is' : 'are'} ` +
                    'enforced at the application layer only and not mirrored to the firewall.</div>';
            }
        } else {
            html += '<div class="alert alert-warning small mb-0 mt-2">' +
                '<i class="bi bi-exclamation-triangle-fill"></i> fail2ban ships pre-installed, but ' +
                'it isn\'t present on this host. Run the EAS Station updater ' +
                '(<code class="text-break-anywhere">sudo bash update.sh</code>) to restore it, then ' +
                'reload this page. Web bans stay enforced at the application layer regardless.</div>';
        }
        statusEl.innerHTML = html;

        // SSH jail bans (separate concern — host SSH, not the web ban list).
        const sshCard = document.getElementById('f2b-ssh-card');
        const sshList = document.getElementById('f2b-ssh-banned-list');
        if (sshCard && sshList) {
            const show = !!(data.settings && data.settings.protect_ssh) || data.ssh_jail_loaded;
            sshCard.style.display = show ? '' : 'none';
            const banned = data.ssh_banned || [];
            if (!banned.length) {
                sshList.innerHTML = '<p class="text-muted mb-0">No SSH bans.</p>';
            } else {
                let t = '<div class="table-responsive"><table class="table eas-table table-sm mb-0"><thead><tr>' +
                    '<th>IP/Range</th><th>Source</th><th>Location</th><th>Description</th>' +
                    '<th>Created</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
                banned.forEach(b => {
                    const created = b.created_at ? new Date(b.created_at).toLocaleString() : '—';
                    t += '<tr>' +
                        `<td data-label="IP/Range" class="admin-mono-badge">${esc(b.ip_address)}</td>` +
                        `<td data-label="Source">${sourceBadge(b)}</td>` +
                        `<td data-label="Location">${locationCell(b)}</td>` +
                        `<td data-label="Description">${esc(b.description || '-')}</td>` +
                        `<td data-label="Created">${esc(created)}</td>` +
                        `<td data-label="Status"><span class="badge bg-danger">Active</span></td>` +
                        '<td data-label="Actions"><button class="btn btn-sm btn-outline-success" ' +
                        `onclick="SC.sshUnban('${esc(b.ip_address)}')"><i class="bi bi-unlock"></i> Unban</button></td>` +
                        '</tr>';
                });
                t += '</tbody></table></div>';
                sshList.innerHTML = t;
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

    function resyncFail2ban() {
        fetch(`${F2B_API}/resync`, { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    notify(data.message || 'Resynced.');
                    loadFail2banStatus();
                } else {
                    notify(data.error || 'Resync failed', true);
                }
            })
            .catch(error => notify('Error resyncing: ' + error, true));
    }

    function numVal(id) {
        const el = document.getElementById(id);
        return el ? parseInt(el.value, 10) : null;
    }

    function saveFail2banConfig() {
        const payload = {
            enabled: document.getElementById('f2b-enabled').checked,
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

    function sshUnban(ip) {
        fetch(`${F2B_API}/ssh-unban`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip_address: ip }),
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
        loadSecurityOverview: loadSecurityOverview,
        resyncFirewall: resyncFirewall,
        loadFail2banStatus: loadFail2banStatus,
        serviceAction: serviceAction,
        resyncFail2ban: resyncFail2ban,
        saveFail2banConfig: saveFail2banConfig,
        sshUnban: sshUnban,
    };
})();
