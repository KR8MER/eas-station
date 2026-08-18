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
 * Dead-air detection policy on the Audio Ingestion page.
 *
 * Owns only the detection half -- thresholds and hold-off. The physical
 * indication (rack buzzer pin, tower-light colour) is configured on the
 * Hardware page, and the acknowledge control lives on the Audio Health
 * dashboard where an operator would be looking when something is wrong.
 */
(function () {
    'use strict';

    const card = document.getElementById('deadAirCard');
    if (!card) return;

    const els = {
        enabled: document.getElementById('deadAirEnabled'),
        duration: document.getElementById('deadAirDuration'),
        level: document.getElementById('deadAirLevel'),
        flatness: document.getElementById('deadAirFlatness'),
        openCarrier: document.getElementById('deadAirOpenCarrier'),
        save: document.getElementById('deadAirSaveBtn'),
        status: document.getElementById('deadAirLiveStatus'),
    };

    function apply(data) {
        if (!data || data.ok === false) return;
        els.enabled.checked = !!data.enabled;
        els.duration.value = data.duration_seconds;
        els.level.value = data.level_threshold_db;
        els.flatness.value = data.flatness_threshold_pct;
        els.openCarrier.checked = !!data.detect_open_carrier;
        syncDisabled();
    }

    // Grey out the thresholds when monitoring is off, so the form reads as
    // one decision rather than five independent ones.
    function syncDisabled() {
        const on = els.enabled.checked;
        [els.duration, els.level, els.flatness, els.openCarrier].forEach((el) => {
            el.disabled = !on;
        });
    }
    els.enabled.addEventListener('change', syncDisabled);

    async function load() {
        try {
            const resp = await fetch('/api/audio/dead-air/settings', {
                headers: { Accept: 'application/json' }, cache: 'no-store',
            });
            apply(await resp.json());
        } catch (err) {
            /* leave the server-rendered defaults in place */
        }
    }

    els.save.addEventListener('click', async function () {
        els.save.disabled = true;
        try {
            const resp = await fetch('/api/audio/dead-air/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled: els.enabled.checked,
                    duration_seconds: Number(els.duration.value),
                    level_threshold_db: Number(els.level.value),
                    flatness_threshold_pct: Number(els.flatness.value),
                    detect_open_carrier: els.openCarrier.checked,
                }),
            });
            const data = await resp.json();
            if (data.ok) {
                apply(data);
                if (window.showToast) {
                    window.showToast(
                        'Dead-air detection settings saved — applied within 30 seconds',
                        'success'
                    );
                }
            } else if (window.showToast) {
                window.showToast(data.error || 'Save failed', 'danger');
            }
        } catch (err) {
            if (window.showToast) {
                window.showToast('Save failed: ' + err.message, 'danger');
            }
        }
        els.save.disabled = false;
    });

    // A compact live indicator in the card header, so the operator can see
    // whether the policy they are editing is currently firing.
    async function pollStatus() {
        if (!els.status) return;
        try {
            const resp = await fetch('/api/audio/dead-air/status', {
                headers: { Accept: 'application/json' }, cache: 'no-store',
            });
            const data = await resp.json();
            if (!data.ok || !data.enabled) {
                els.status.textContent = '';
                return;
            }
            if (data.active) {
                const names = Object.keys(data.sources || {});
                els.status.innerHTML =
                    '<span class="badge bg-danger"><i class="fas fa-volume-mute me-1"></i>'
                    + `DEAD AIR</span> <span class="text-muted">${names.join(', ')}</span>`;
            } else {
                els.status.innerHTML =
                    '<span class="text-success"><i class="fas fa-check-circle me-1"></i>'
                    + 'Audio present on all monitored sources</span>';
            }
        } catch (err) {
            els.status.textContent = '';
        }
    }

    load();
    pollStatus();
    window.setInterval(pollStatus, 10000);
})();
