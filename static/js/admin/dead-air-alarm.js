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
 * Dead-air alarm banner on the Audio Health dashboard.
 *
 * Acknowledging is an operational action taken while an alarm is
 * sounding, not configuration -- which is why it lives on the dashboard
 * an operator is already looking at rather than buried in a settings
 * form. The detection policy is edited on the Audio Ingestion page; the
 * buzzer pin and tower-light colour on the Hardware page.
 */
(function () {
    'use strict';

    const POLL_MS = 5000;
    const banner = document.getElementById('deadAirAlarm');
    const detail = document.getElementById('deadAirAlarmDetail');
    const ackBtn = document.getElementById('deadAirAckBtn');
    if (!banner || !ackBtn) return;

    function describe(sources) {
        const names = Object.keys(sources || {});
        if (!names.length) return 'A monitored source is silent.';
        return names.map((name) => {
            const src = sources[name] || {};
            const secs = Number(src.duration_seconds);
            const held = Number.isFinite(secs) && secs > 0
                ? ` for ${secs >= 60
                    ? `${Math.round(secs / 60)} min`
                    : `${Math.round(secs)} s`}`
                : '';
            return `<strong>${name}</strong>: ${src.detail || 'silent'}${held}`;
        }).join('<br>');
    }

    function render(data) {
        if (!data || data.ok === false || !data.active) {
            banner.style.display = 'none';
            return;
        }
        banner.style.display = '';
        detail.innerHTML = describe(data.sources)
            + (data.acknowledged
                ? '<br><span class="text-warning"><i class="fas fa-bell-slash me-1"></i>'
                  + 'Buzzer acknowledged &mdash; indication stays until audio returns</span>'
                : '');
        ackBtn.dataset.acknowledged = data.acknowledged ? 'true' : 'false';
        ackBtn.innerHTML = data.acknowledged
            ? '<i class="fas fa-bell me-1"></i>Un-acknowledge (let it sound)'
            : '<i class="fas fa-bell-slash me-1"></i>Acknowledge / silence buzzer';
    }

    async function poll() {
        try {
            const resp = await fetch('/api/audio/dead-air/status', {
                headers: { Accept: 'application/json' }, cache: 'no-store',
            });
            render(await resp.json());
        } catch (err) {
            /* transient; the next tick retries */
        }
    }

    ackBtn.addEventListener('click', async function () {
        const wasAcked = ackBtn.dataset.acknowledged === 'true';
        ackBtn.disabled = true;
        try {
            const resp = await fetch('/api/audio/dead-air/acknowledge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ acknowledged: !wasAcked }),
            });
            const data = await resp.json();
            if (window.showToast) {
                window.showToast(
                    data.ok
                        ? (wasAcked
                            ? 'Dead-air alarm un-acknowledged'
                            : 'Dead-air alarm acknowledged — buzzer silenced')
                        : (data.error || 'Acknowledge failed'),
                    data.ok ? (wasAcked ? 'info' : 'warning') : 'danger'
                );
            }
        } catch (err) {
            if (window.showToast) {
                window.showToast('Acknowledge failed: ' + err.message, 'danger');
            }
        }
        ackBtn.disabled = false;
        poll();
    });

    poll();
    window.setInterval(poll, POLL_MS);
})();
