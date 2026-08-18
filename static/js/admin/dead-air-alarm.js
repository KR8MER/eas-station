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

    function heldFor(seconds) {
        const secs = Number(seconds);
        if (!Number.isFinite(secs) || secs <= 0) return '';
        return secs >= 60
            ? ` for ${Math.round(secs / 60)} min`
            : ` for ${Math.round(secs)} s`;
    }

    // Source names and detail strings are operator-supplied and reach here
    // through Redis, so they are built as text nodes rather than
    // interpolated into innerHTML. A source named with markup would
    // otherwise execute in another operator's session.
    function describeInto(el, sources) {
        el.textContent = '';
        const names = Object.keys(sources || {});
        if (!names.length) {
            el.textContent = 'A monitored source is silent.';
            return;
        }
        names.forEach((name, i) => {
            if (i) el.appendChild(document.createElement('br'));
            const strong = document.createElement('strong');
            strong.textContent = name;
            el.appendChild(strong);
            const src = sources[name] || {};
            el.appendChild(document.createTextNode(
                `: ${src.detail || 'silent'}${heldFor(src.duration_seconds)}`
            ));
        });
    }

    function setButton(label, iconClass) {
        ackBtn.textContent = '';
        const icon = document.createElement('i');
        icon.className = `${iconClass} me-1`;
        ackBtn.appendChild(icon);
        ackBtn.appendChild(document.createTextNode(label));
    }

    function render(data) {
        if (!data || data.ok === false || !data.active) {
            banner.style.display = 'none';
            return;
        }
        banner.style.display = '';
        describeInto(detail, data.sources);

        if (data.acknowledged) {
            detail.appendChild(document.createElement('br'));
            const note = document.createElement('span');
            note.className = 'text-warning';
            const icon = document.createElement('i');
            icon.className = 'fas fa-bell-slash me-1';
            note.appendChild(icon);
            note.appendChild(document.createTextNode(
                'Buzzer acknowledged \u2014 indication stays until audio returns'
            ));
            detail.appendChild(note);
        }

        // Carry the episode so acknowledging cannot land on a newer outage
        // than the one this page is showing.
        ackBtn.dataset.episode = data.episode || '';
        ackBtn.dataset.acknowledged = data.acknowledged ? 'true' : 'false';

        // Acknowledging needs system.configure; a viewer still sees the
        // alarm but is not offered a control that would only 403.
        if (data.can_acknowledge === false) {
            ackBtn.style.display = 'none';
            return;
        }
        ackBtn.style.display = '';
        if (data.acknowledged) {
            setButton('Un-acknowledge (let it sound)', 'fas fa-bell');
        } else {
            setButton('Acknowledge / silence buzzer', 'fas fa-bell-slash');
        }
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
                body: JSON.stringify({
                    acknowledged: !wasAcked,
                    episode: ackBtn.dataset.episode || undefined,
                }),
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
