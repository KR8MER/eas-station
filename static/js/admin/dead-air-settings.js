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
        formError: document.getElementById('deadAirFormError'),
    };

    // The numeric inputs are populated by load(), not server-rendered. If
    // the load fails and the operator hits Save, Number('') is 0 and the
    // API clamps that to each field's minimum -- silently rewriting a 20 s
    // hold-off to 1 s. So Save stays disabled until a load succeeds.
    let loaded = false;
    els.save.disabled = true;

    function apply(data) {
        if (!data || data.ok === false) return;
        els.enabled.checked = !!data.enabled;
        els.duration.value = data.duration_seconds;
        els.level.value = data.level_threshold_db;
        els.flatness.value = data.flatness_threshold_pct;
        els.openCarrier.checked = !!data.detect_open_carrier;
        loaded = true;
        if (els.formError) els.formError.textContent = '';
        syncDisabled();
    }

    // Grey out the thresholds when monitoring is off, so the form reads as
    // one decision rather than five independent ones.
    function syncDisabled() {
        const on = els.enabled.checked;
        [els.duration, els.level, els.flatness, els.openCarrier].forEach((el) => {
            el.disabled = !on || !loaded;
        });
        els.save.disabled = !loaded;
    }
    els.enabled.addEventListener('change', syncDisabled);

    async function load() {
        try {
            const resp = await fetch('/api/audio/dead-air/settings', {
                headers: { Accept: 'application/json' }, cache: 'no-store',
            });
            apply(await resp.json());
        } catch (err) {
            loaded = false;
            syncDisabled();
            if (els.formError) {
                els.formError.textContent =
                    'Could not load dead-air settings — saving is disabled '
                    + 'so blank values cannot overwrite what is stored. Reload to retry.';
            }
        }
    }

    els.save.addEventListener('click', async function () {
        if (!loaded) return;   // never post blanks over stored settings
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
            if (!data.ok) { /* keep the operator's edits on screen to retry */ }
        } catch (err) {
            if (window.showToast) {
                window.showToast('Save failed: ' + err.message, 'danger');
            }
        }
        els.save.disabled = !loaded;
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
            els.status.textContent = '';
            els.status.className = 'small text-muted';
            if (data.active) {
                // Source names come from operator input via Redis, so they
                // are appended as text rather than interpolated into HTML.
                const badge = document.createElement('span');
                badge.className = 'badge bg-danger';
                const bIcon = document.createElement('i');
                bIcon.className = 'fas fa-volume-mute me-1';
                badge.appendChild(bIcon);
                badge.appendChild(document.createTextNode('DEAD AIR'));
                els.status.appendChild(badge);

                const names = document.createElement('span');
                names.className = 'text-muted ms-1';
                names.textContent = Object.keys(data.sources || {}).join(', ');
                els.status.appendChild(names);
            } else {
                const okSpan = document.createElement('span');
                okSpan.className = 'text-success';
                const oIcon = document.createElement('i');
                oIcon.className = 'fas fa-check-circle me-1';
                okSpan.appendChild(oIcon);
                okSpan.appendChild(document.createTextNode(
                    'Audio present on all monitored sources'
                ));
                els.status.appendChild(okSpan);
            }
        } catch (err) {
            els.status.textContent = '';
        }
    }

    load();
    pollStatus();
    window.setInterval(pollStatus, 10000);
})();
