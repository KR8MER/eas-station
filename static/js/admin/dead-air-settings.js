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
 * Dead-air alarm live status, on the Audio Ingestion page.
 *
 * Detection policy (thresholds, hold-off, whether alarming is even enabled)
 * is per-source now -- configured in that source's Add/Edit dialog, not
 * here. This script only polls the aggregate "is anything silent right
 * now" status so the card header stays live. The physical indication (rack
 * buzzer pin, tower-light colour) is configured on the Hardware page, and
 * the acknowledge control lives on the Audio Health dashboard where an
 * operator would be looking when something is wrong.
 */
(function () {
    'use strict';

    const status = document.getElementById('deadAirLiveStatus');
    if (!status) return;

    async function pollStatus() {
        try {
            const resp = await fetch('/api/audio/dead-air/status', {
                headers: { Accept: 'application/json' }, cache: 'no-store',
            });
            const data = await resp.json();
            status.textContent = '';
            if (!data.ok || !data.enabled) {
                return;
            }
            status.className = 'small text-muted';
            if (data.active) {
                // Source names come from operator input via Redis, so they
                // are appended as text rather than interpolated into HTML.
                const badge = document.createElement('span');
                badge.className = 'badge bg-danger';
                const bIcon = document.createElement('i');
                bIcon.className = 'fas fa-volume-mute me-1';
                badge.appendChild(bIcon);
                badge.appendChild(document.createTextNode('DEAD AIR'));
                status.appendChild(badge);

                const names = document.createElement('span');
                names.className = 'text-muted ms-1';
                names.textContent = Object.keys(data.sources || {}).join(', ');
                status.appendChild(names);
            } else {
                const okSpan = document.createElement('span');
                okSpan.className = 'text-success';
                const oIcon = document.createElement('i');
                oIcon.className = 'fas fa-check-circle me-1';
                okSpan.appendChild(oIcon);
                okSpan.appendChild(document.createTextNode(
                    'Audio present on all monitored sources'
                ));
                status.appendChild(okSpan);
            }
        } catch (err) {
            status.textContent = '';
        }
    }

    pollStatus();
    window.setInterval(pollStatus, 10000);
})();
