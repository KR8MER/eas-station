/**
 * EAS Station™ - Pending Alerts (gated-alerts hold-off timer) admin page.
 *
 * Renders the pending queue from a websocket push (falling back to polling
 * via EASWebSocket), and drives a local 1Hz countdown per row from the
 * pushed hold_until timestamp -- never polls the server once a second just
 * for the ticking number.
 */
(function (window, document) {
    'use strict';

    let currentAlerts = [];

    function formatRemaining(holdUntilIso) {
        if (!holdUntilIso) return '—';
        const holdUntil = new Date(holdUntilIso).getTime();
        if (Number.isNaN(holdUntil)) return '—';
        const remainingMs = holdUntil - Date.now();
        if (remainingMs <= 0) return 'releasing…';
        const totalSeconds = Math.ceil(remainingMs / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
    }

    function renderRow(alert) {
        const config = document.getElementById('pendingAlertsConfig');
        const canApprove = !!config && config.dataset.canApprove === 'true';
        const canCancel = !!config && config.dataset.canCancel === 'true';
        const actions = [];
        if (canApprove) {
            actions.push(
                `<button type="button" class="btn btn-sm btn-outline-success me-1" onclick="approvePendingAlert(${alert.id})">` +
                `<i class="fas fa-check"></i> Approve</button>`
            );
        }
        if (canCancel) {
            actions.push(
                `<button type="button" class="btn btn-sm btn-outline-danger" onclick="cancelPendingAlert(${alert.id})">` +
                `<i class="fas fa-ban"></i> Cancel</button>`
            );
        }
        return (
            `<tr data-gate-id="${alert.id}" data-hold-until="${window.escapeHtml(alert.hold_until || '')}">` +
            `<td>${window.escapeHtml(alert.event || alert.event_code || '—')}</td>` +
            `<td><span class="badge bg-${alert.source === 'cap' ? 'info' : 'secondary'}">${window.escapeHtml((alert.source || '').toUpperCase())}</span></td>` +
            `<td>${window.escapeHtml(alert.severity || '—')} / ${window.escapeHtml(alert.urgency || '—')}</td>` +
            `<td class="text-break-anywhere">${window.escapeHtml(alert.headline || '—')}</td>` +
            `<td class="countdown-cell">${window.escapeHtml(formatRemaining(alert.hold_until))}</td>` +
            `<td class="text-end">${actions.join('')}</td>` +
            `</tr>`
        );
    }

    function renderTable() {
        const tbody = document.getElementById('pendingTableBody');
        const wrap = document.getElementById('pendingTableWrap');
        const empty = document.getElementById('emptyState');
        const countBadge = document.getElementById('pendingCount');
        if (!tbody) return;

        if (countBadge) countBadge.textContent = String(currentAlerts.length);

        if (currentAlerts.length === 0) {
            if (wrap) wrap.style.display = 'none';
            if (empty) empty.style.display = '';
            tbody.innerHTML = '';
            return;
        }
        if (wrap) wrap.style.display = '';
        if (empty) empty.style.display = 'none';
        tbody.innerHTML = currentAlerts.map(renderRow).join('');
    }

    function tickCountdowns() {
        document.querySelectorAll('#pendingTableBody tr[data-hold-until]').forEach((row) => {
            const holdUntil = row.getAttribute('data-hold-until');
            const cell = row.querySelector('.countdown-cell');
            if (cell && holdUntil) {
                cell.textContent = formatRemaining(holdUntil);
            }
        });
    }

    function handlePendingAlertsUpdate(payload) {
        if (!payload || !Array.isArray(payload.alerts)) return;
        currentAlerts = payload.alerts;
        renderTable();
    }

    window.approvePendingAlert = async function (gateId) {
        try {
            const response = await fetch(`/admin/pending-alerts/${gateId}/approve`, { method: 'POST' });
            const data = await response.json();
            if (response.ok && data.success) {
                window.showToast(data.message || 'Alert approved', 'success');
            } else {
                window.showToast(data.error || 'Failed to approve alert', 'danger');
            }
        } catch (error) {
            console.error('Error approving pending alert:', error);
            window.showToast('Error approving alert', 'danger');
        }
    };

    window.cancelPendingAlert = async function (gateId) {
        if (!window.confirm('Cancel this alert? It will not be broadcast, even after the hold-off timer expires.')) {
            return;
        }
        try {
            const response = await fetch(`/admin/pending-alerts/${gateId}/cancel`, { method: 'POST' });
            const data = await response.json();
            if (response.ok && data.success) {
                window.showToast(data.message || 'Alert cancelled', 'success');
            } else {
                window.showToast(data.error || 'Failed to cancel alert', 'danger');
            }
        } catch (error) {
            console.error('Error cancelling pending alert:', error);
            window.showToast('Error cancelling alert', 'danger');
        }
    };

    function seedFromServerRenderedRows() {
        currentAlerts = Array.from(document.querySelectorAll('#pendingTableBody tr[data-gate-id]')).map((row) => ({
            id: parseInt(row.getAttribute('data-gate-id'), 10),
            hold_until: row.getAttribute('data-hold-until'),
            event: row.children[0] ? row.children[0].textContent.trim() : '',
            source: (row.children[1] ? row.children[1].textContent.trim() : '').toLowerCase(),
            headline: row.children[3] ? row.children[3].textContent.trim() : '',
        }));
    }

    function init() {
        seedFromServerRenderedRows();
        setInterval(tickCountdowns, 1000);

        if (!window.EASWebSocket || typeof window.EASWebSocket.subscribe !== 'function') {
            return;
        }
        const fallback = window.EASWebSocket.createPollingFallback(
            '/admin/pending-alerts/api/list',
            handlePendingAlertsUpdate,
        );
        window.EASWebSocket.subscribe('pending_alerts_update', handlePendingAlertsUpdate, {
            fallbackFn: fallback,
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})(window, document);
