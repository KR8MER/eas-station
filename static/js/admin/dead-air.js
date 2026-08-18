/*
 * EAS Station - Emergency Alert System
 * Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
 *
 * This file is part of EAS Station.
 *
 * EAS Station is dual-licensed software:
 * - GNU Affero General Public License v3 (AGPL-3.0) for open-source use
 * - Commercial License for proprietary use
 *
 * IMPORTANT: This software cannot be rebranded or have attribution removed.
 * See NOTICE file for complete terms.
 *
 * Repository: https://github.com/KR8MER/eas-station
 */

/**
 * Dead-air (silence) monitoring controls on the Hardware Settings page.
 *
 * Kept as a sibling module rather than appended to hardware-settings.js,
 * which is already well past the size guidance in AGENTS.md.
 *
 * Two jobs:
 *   1. Poll the live dead-air state so the operator can see whether a
 *      source is currently silent without leaving the settings page.
 *   2. Drive the Acknowledge button, which silences the rack buzzer for
 *      the current episode while deliberately leaving the tower light lit
 *      -- standard alarm-panel behaviour, since acknowledging means the
 *      fault was noticed, not fixed.
 */
(function () {
    'use strict';

    const POLL_MS = 5000;
    const ackBtn = document.getElementById('deadAirAckBtn');
    const enableToggle = document.getElementById('dead_air_enabled');
    if (!ackBtn) return;

    // Status pill injected next to the button so the page shows live state
    // without needing a full settings reload.
    const status = document.createElement('div');
    status.className = 'small mt-2';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    ackBtn.parentNode.appendChild(status);

    function render(data) {
        if (!data || data.ok === false) {
            status.innerHTML =
                '<span class="text-muted"><i class="fas fa-question-circle me-1"></i>'
                + 'State unavailable</span>';
            ackBtn.disabled = true;
            return;
        }
        if (!data.enabled) {
            status.innerHTML =
                '<span class="text-muted"><i class="fas fa-circle-notch me-1"></i>'
                + 'Not monitoring any source yet</span>';
            ackBtn.disabled = true;
            return;
        }
        if (!data.active) {
            status.innerHTML =
                '<span class="text-success"><i class="fas fa-check-circle me-1"></i>'
                + 'Audio present on all monitored sources</span>';
            ackBtn.disabled = true;
            return;
        }

        const names = Object.keys(data.sources || {});
        const detail = names.length
            ? names.map((n) => {
                const src = data.sources[n] || {};
                const secs = Number(src.duration_seconds);
                const held = Number.isFinite(secs) && secs > 0
                    ? ` for ${secs >= 60
                        ? `${Math.round(secs / 60)} min`
                        : `${Math.round(secs)} s`}`
                    : '';
                return `${n}: ${src.detail || 'silent'}${held}`;
            }).join('<br>')
            : 'silent';

        status.innerHTML =
            `<span class="text-danger fw-semibold"><i class="fas fa-volume-mute me-1"></i>`
            + `DEAD AIR</span><br><span class="text-muted">${detail}</span>`
            + (data.acknowledged
                ? '<br><span class="text-warning"><i class="fas fa-bell-slash me-1"></i>'
                  + 'Buzzer acknowledged &mdash; light stays lit until audio returns</span>'
                : '');
        ackBtn.disabled = false;
        ackBtn.innerHTML = data.acknowledged
            ? '<i class="fas fa-bell me-1"></i>Un-acknowledge (let it sound)'
            : '<i class="fas fa-bell-slash me-1"></i>Acknowledge / silence buzzer';
        ackBtn.dataset.acknowledged = data.acknowledged ? 'true' : 'false';
    }

    async function poll() {
        try {
            const resp = await fetch('/admin/hardware/dead-air/status', {
                headers: { Accept: 'application/json' },
                cache: 'no-store',
            });
            render(await resp.json());
        } catch (err) {
            render(null);
        }
    }

    ackBtn.addEventListener('click', async function () {
        const wasAcked = ackBtn.dataset.acknowledged === 'true';
        ackBtn.disabled = true;
        try {
            const resp = await fetch('/admin/hardware/dead-air/acknowledge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ acknowledged: !wasAcked }),
            });
            const data = await resp.json();
            if (data.ok) {
                if (window.showToast) {
                    window.showToast(
                        wasAcked
                            ? 'Dead-air alarm un-acknowledged'
                            : 'Dead-air alarm acknowledged — buzzer silenced',
                        wasAcked ? 'info' : 'warning'
                    );
                }
            } else if (window.showToast) {
                window.showToast(data.error || 'Acknowledge failed', 'danger');
            }
        } catch (err) {
            if (window.showToast) {
                window.showToast('Acknowledge failed: ' + err.message, 'danger');
            }
        }
        poll();
    });

    // Only poll while the feature is switched on, so a station that does
    // not use dead-air monitoring is not making a request every 5 s.
    let timer = null;
    function syncPolling() {
        const on = !enableToggle || enableToggle.checked;
        if (on && !timer) {
            poll();
            timer = window.setInterval(poll, POLL_MS);
        } else if (!on && timer) {
            window.clearInterval(timer);
            timer = null;
            status.innerHTML =
                '<span class="text-muted">Dead-air monitoring is off</span>';
            ackBtn.disabled = true;
        }
    }
    if (enableToggle) enableToggle.addEventListener('change', syncPolling);
    syncPolling();
})();
