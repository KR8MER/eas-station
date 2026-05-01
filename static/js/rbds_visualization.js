/**
 * RBDS Visualization Module
 * -------------------------
 * Shared front-end helpers that turn the ~50-field RBDS metadata blob
 * into a structured, accessible visualization. Used by:
 *   - templates/admin/radio.html             (receiver tile in audio monitor)
 *   - templates/audio_monitoring.html        (full station + decoder card)
 *   - templates/admin/radio_diagnostics.html (decoder health card)
 *
 * All output strings are HTML — every dynamic value is escaped through
 * RBDSViz.escapeHtml() before interpolation. Container.innerHTML = output is
 * the only supported sink.
 *
 * Accessibility notes:
 *   - The heartbeat dot has role="status" + aria-label + an .sr-only text
 *     alternative so screen readers announce decoder state.
 *   - Every coloured badge carries an icon + visible text so colour is never
 *     the sole indicator of meaning (WCAG 1.4.1).
 *   - Collapsible details sections use native <details>/<summary> for full
 *     keyboard support without extra ARIA wiring.
 *   - Tables include <caption class="sr-only"> + <th scope="col"> headers.
 *   - The EWS banner uses role="alert" + aria-live="assertive".
 *   - The PS "LCD" panel includes aria-label so it isn't read as garbage.
 */
(function (global) {
    'use strict';

    // ---- Utilities --------------------------------------------------------

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function isPresent(v) {
        return v !== null && v !== undefined && v !== '';
    }

    function hex(n, width) {
        if (!isPresent(n)) return '';
        return '0x' + Number(n).toString(16).toUpperCase().padStart(width || 0, '0');
    }

    // ---- Heartbeat (decoder liveness) -------------------------------------
    // Returns {state: 'live'|'stale'|'idle', label, srText, secondsAgo}
    // - live: data within last 10s (green)
    // - stale: data within last 60s (amber)
    // - idle: older or absent (grey)
    function heartbeatState(lastSeenUnix) {
        if (!isPresent(lastSeenUnix)) {
            return {
                state: 'idle',
                label: 'No data',
                srText: 'RBDS decoder has not reported any data.',
                secondsAgo: null,
            };
        }
        const seconds = Math.max(0, (Date.now() / 1000) - Number(lastSeenUnix));
        if (seconds < 10) {
            return {
                state: 'live',
                label: 'Live',
                srText: `RBDS data is live. Last group ${seconds.toFixed(0)} seconds ago.`,
                secondsAgo: seconds,
            };
        }
        if (seconds < 60) {
            return {
                state: 'stale',
                label: 'Stale',
                srText: `RBDS data is stale. Last group ${seconds.toFixed(0)} seconds ago.`,
                secondsAgo: seconds,
            };
        }
        return {
            state: 'idle',
            label: 'Idle',
            srText: `RBDS decoder is idle. Last group ${Math.floor(seconds)} seconds ago.`,
            secondsAgo: seconds,
        };
    }

    function heartbeatHTML(lastSeenUnix) {
        const hb = heartbeatState(lastSeenUnix);
        return (
            `<span class="rbds-heartbeat rbds-heartbeat--${hb.state}" ` +
            `role="status" aria-label="${escapeHtml(hb.srText)}">` +
            `<span class="rbds-heartbeat__dot" aria-hidden="true"></span>` +
            `<span class="rbds-heartbeat__label" aria-hidden="true">${escapeHtml(hb.label)}</span>` +
            `<span class="sr-only">${escapeHtml(hb.srText)}</span>` +
            `</span>`
        );
    }

    // ---- PTY category styling ---------------------------------------------
    // Maps the NRSC-4-B program type name to a category {variant, icon, label}.
    // Variant is used as a CSS class suffix: rbds-pty--<variant>. The icon and
    // visible text label always travel together so colour is never the only
    // signal of meaning.
    const PTY_CATEGORIES = {
        // Emergency
        'Emergency':         { variant: 'emergency', icon: 'fas fa-tower-broadcast' },
        'Emergency Test':    { variant: 'emergency', icon: 'fas fa-vial' },
        'Weather':           { variant: 'weather',   icon: 'fas fa-cloud-bolt' },
        // News & talk
        'News':              { variant: 'news',      icon: 'fas fa-newspaper' },
        'Information':       { variant: 'news',      icon: 'fas fa-circle-info' },
        'Sports':            { variant: 'sports',    icon: 'fas fa-baseball' },
        'Talk':              { variant: 'talk',      icon: 'fas fa-comments' },
        'Personality':       { variant: 'talk',      icon: 'fas fa-user-tie' },
        'Public':            { variant: 'talk',      icon: 'fas fa-bullhorn' },
        'College':           { variant: 'talk',      icon: 'fas fa-graduation-cap' },
        'Spanish Talk':      { variant: 'talk',      icon: 'fas fa-comments' },
        // Music
        'Rock':              { variant: 'music',     icon: 'fas fa-guitar' },
        'Classic Rock':      { variant: 'music',     icon: 'fas fa-guitar' },
        'Adult Hits':        { variant: 'music',     icon: 'fas fa-music' },
        'Soft Rock':         { variant: 'music',     icon: 'fas fa-music' },
        'Top 40':            { variant: 'music',     icon: 'fas fa-music' },
        'Country':           { variant: 'music',     icon: 'fas fa-music' },
        'Oldies':            { variant: 'music',     icon: 'fas fa-record-vinyl' },
        'Soft':              { variant: 'music',     icon: 'fas fa-music' },
        'Nostalgia':         { variant: 'music',     icon: 'fas fa-record-vinyl' },
        'Jazz':              { variant: 'music',     icon: 'fas fa-music' },
        'Classical':         { variant: 'music',     icon: 'fas fa-music' },
        'Rhythm & Blues':    { variant: 'music',     icon: 'fas fa-music' },
        'Soft R&B':          { variant: 'music',     icon: 'fas fa-music' },
        'Spanish Music':     { variant: 'music',     icon: 'fas fa-music' },
        'Hip Hop':           { variant: 'music',     icon: 'fas fa-music' },
        'Language':          { variant: 'music',     icon: 'fas fa-globe' },
        // Religious
        'Religious Music':   { variant: 'religion',  icon: 'fas fa-place-of-worship' },
        'Religious Talk':    { variant: 'religion',  icon: 'fas fa-place-of-worship' },
        // Default
        'No program type':   { variant: 'neutral',   icon: 'fas fa-circle-question' },
        'Unassigned':        { variant: 'neutral',   icon: 'fas fa-circle-question' },
    };

    function ptyStyle(name) {
        if (!isPresent(name)) return null;
        const trimmed = String(name).trim();
        return PTY_CATEGORIES[trimmed] || { variant: 'neutral', icon: 'fas fa-tag' };
    }

    function ptyBadgeHTML(metadata) {
        const name = metadata.rbds_program_type_name;
        const code = metadata.rbds_pty;
        if (!isPresent(name) && !isPresent(code)) return '';
        const display = isPresent(name) ? name : `PTY ${code}`;
        const style = ptyStyle(name) || { variant: 'neutral', icon: 'fas fa-tag' };
        const codeSuffix = isPresent(code)
            ? ` <span class="rbds-pty__code" aria-hidden="true">(${Number(code)})</span>`
            : '';
        const ariaLabel = isPresent(code)
            ? `Programme type: ${display}, code ${code}.`
            : `Programme type: ${display}.`;
        return (
            `<span class="rbds-pty rbds-pty--${style.variant}" aria-label="${escapeHtml(ariaLabel)}">` +
            `<i class="${escapeHtml(style.icon)}" aria-hidden="true"></i>` +
            `<span>${escapeHtml(display)}</span>` +
            codeSuffix +
            `</span>`
        );
    }

    // ---- Service flag chips (TP/TA/Stereo/M-S/Dynamic PTY/TMC) ------------

    function flagChip(opts) {
        // opts: {variant, icon, label, srLabel, active}
        const variant = opts.variant || 'neutral';
        const activeCls = opts.active ? ' rbds-flag--active' : '';
        const inactiveCls = opts.active === false ? ' rbds-flag--inactive' : '';
        return (
            `<span class="rbds-flag rbds-flag--${variant}${activeCls}${inactiveCls}" ` +
            `aria-label="${escapeHtml(opts.srLabel || opts.label)}">` +
            (opts.icon ? `<i class="${escapeHtml(opts.icon)}" aria-hidden="true"></i>` : '') +
            `<span>${escapeHtml(opts.label)}</span>` +
            `</span>`
        );
    }

    function flagsRowHTML(metadata) {
        const chips = [];

        if (isPresent(metadata.rbds_tp)) {
            chips.push(flagChip({
                variant: 'info',
                icon: 'fas fa-traffic-light',
                label: metadata.rbds_tp ? 'TP' : 'TP off',
                srLabel: metadata.rbds_tp
                    ? 'Traffic Programme: yes, station broadcasts traffic information.'
                    : 'Traffic Programme: no.',
                active: !!metadata.rbds_tp,
            }));
        }
        if (isPresent(metadata.rbds_ta)) {
            chips.push(flagChip({
                variant: 'warning',
                icon: 'fas fa-triangle-exclamation',
                label: metadata.rbds_ta ? 'TA active' : 'TA off',
                srLabel: metadata.rbds_ta
                    ? 'Traffic Announcement currently active.'
                    : 'No active Traffic Announcement.',
                active: !!metadata.rbds_ta,
            }));
        }
        if (isPresent(metadata.rbds_di_stereo)) {
            chips.push(flagChip({
                variant: 'audio',
                icon: metadata.rbds_di_stereo ? 'fas fa-headphones' : 'fas fa-volume-low',
                label: metadata.rbds_di_stereo ? 'Stereo' : 'Mono',
                srLabel: metadata.rbds_di_stereo
                    ? 'Audio mode: stereo.'
                    : 'Audio mode: mono.',
                active: !!metadata.rbds_di_stereo,
            }));
        }
        if (isPresent(metadata.rbds_ms)) {
            chips.push(flagChip({
                variant: 'audio',
                icon: metadata.rbds_ms ? 'fas fa-music' : 'fas fa-microphone',
                label: metadata.rbds_ms ? 'Music' : 'Speech',
                srLabel: metadata.rbds_ms
                    ? 'Music/Speech switch: music.'
                    : 'Music/Speech switch: speech.',
                active: !!metadata.rbds_ms,
            }));
        }
        if (metadata.rbds_di_dynamic_pty === true) {
            chips.push(flagChip({
                variant: 'neutral',
                icon: 'fas fa-arrows-rotate',
                label: 'Dynamic PTY',
                srLabel: 'Programme type may change dynamically.',
                active: true,
            }));
        }
        if (metadata.rbds_tmc_present === true) {
            chips.push(flagChip({
                variant: 'neutral',
                icon: 'fas fa-road',
                label: 'TMC',
                srLabel: 'Traffic Message Channel data present.',
                active: true,
            }));
        }
        if (metadata.rbds_di_artificial_head === true) {
            chips.push(flagChip({
                variant: 'neutral',
                icon: 'fas fa-user-large',
                label: 'Artificial Head',
                srLabel: 'Recorded with binaural artificial-head technique.',
                active: true,
            }));
        }
        if (metadata.rbds_di_compressed === true) {
            chips.push(flagChip({
                variant: 'neutral',
                icon: 'fas fa-compress',
                label: 'Compressed',
                srLabel: 'Audio dynamic range is compressed.',
                active: true,
            }));
        }

        if (!chips.length) return '';
        return `<div class="rbds-flags" role="group" aria-label="RBDS service flags">${chips.join('')}</div>`;
    }

    // ---- EWS Emergency Warning banner -------------------------------------

    function buildEWSBanner(metadata) {
        const channel = metadata.rbds_ews_channel;
        if (!isPresent(channel) || Number(channel) === 0) return '';
        const wordC = isPresent(metadata.rbds_ews_message_c)
            ? hex(metadata.rbds_ews_message_c, 4) : null;
        const wordD = isPresent(metadata.rbds_ews_message_d)
            ? hex(metadata.rbds_ews_message_d, 4) : null;
        const channelId = isPresent(metadata.rbds_ews_channel_identifier)
            ? hex(metadata.rbds_ews_channel_identifier, 3) : null;
        return (
            `<div class="rbds-ews-banner alert alert-danger d-flex align-items-start gap-2" ` +
            `role="alert" aria-live="assertive">` +
            `<i class="fas fa-tower-broadcast fa-2x flex-shrink-0" aria-hidden="true"></i>` +
            `<div class="flex-grow-1">` +
            `<strong class="d-block mb-1">Emergency Warning System (EWS) active</strong>` +
            `<div class="small">` +
            `<span class="me-3"><span class="text-muted">Channel:</span> ` +
            `<span class="font-monospace fw-bold">${escapeHtml(channel)}</span></span>` +
            (channelId
                ? `<span class="me-3"><span class="text-muted">Identifier:</span> ` +
                  `<span class="font-monospace">${escapeHtml(channelId)}</span></span>`
                : '') +
            (wordC
                ? `<span class="me-3"><span class="text-muted">Word C:</span> ` +
                  `<span class="font-monospace">${escapeHtml(wordC)}</span></span>`
                : '') +
            (wordD
                ? `<span class="me-3"><span class="text-muted">Word D:</span> ` +
                  `<span class="font-monospace">${escapeHtml(wordD)}</span></span>`
                : '') +
            `</div>` +
            `<div class="small text-muted mt-1">RBDS-borne emergency message detected. ` +
            `Words C and D are country-specific bitmasks; consult the broadcaster's EWS ` +
            `coding tables to interpret.</div>` +
            `</div></div>`
        );
    }

    // ---- RT+ "now playing" strip -------------------------------------------

    function buildNowPlaying(metadata) {
        const tags = metadata.rbds_rt_plus_tags;
        const text = metadata.rbds_radio_text;

        if (Array.isArray(tags) && tags.length > 0) {
            const paused = metadata.rbds_rt_plus_item_running === false;
            const rows = tags.map(tag => {
                const label = tag.content_type_name || `TYPE_${tag.content_type}`;
                return (
                    `<div class="rbds-rtplus__row">` +
                    `<span class="rbds-rtplus__label">${escapeHtml(label)}</span>` +
                    `<span class="rbds-rtplus__value">${escapeHtml(tag.text || '')}</span>` +
                    `</div>`
                );
            }).join('');
            return (
                `<div class="rbds-rtplus" aria-label="Now playing (RT+) information">` +
                `<div class="rbds-rtplus__head">` +
                `<i class="fas fa-circle-play" aria-hidden="true"></i>` +
                `<span>Now Playing</span>` +
                (paused ? `<span class="rbds-rtplus__paused" aria-label="Track playback paused">paused</span>` : '') +
                `</div>` +
                rows +
                `</div>`
            );
        }
        if (isPresent(text)) {
            return (
                `<p class="rbds-rt" aria-label="Radio Text">` +
                `<i class="fas fa-quote-left" aria-hidden="true"></i> ` +
                `<em>${escapeHtml(text)}</em>` +
                `</p>`
            );
        }
        return '';
    }

    // ---- Alternative Frequencies pills ------------------------------------

    function buildAFList(metadata) {
        const af = metadata.rbds_af_list;
        if (!Array.isArray(af) || af.length === 0) return '';
        const tuned = metadata.rbds_af_tuning_frequency;
        const expected = metadata.rbds_af_method_a_count;
        const completion = isPresent(expected)
            ? `<span class="rbds-af__count" aria-label="${escapeHtml(`${af.length} of ${expected} alternative frequencies received`)}">${escapeHtml(af.length)} / ${escapeHtml(expected)}</span>`
            : '';
        const pills = af.map(f => {
            const isTuned = isPresent(tuned) && f === tuned;
            const cls = isTuned ? 'rbds-af-pill rbds-af-pill--tuned' : 'rbds-af-pill';
            const aria = isTuned ? `${f} megahertz, currently tuned` : `${f} megahertz`;
            return `<span class="${cls}" aria-label="${escapeHtml(aria)}">${escapeHtml(f)}<span aria-hidden="true"> MHz</span></span>`;
        }).join('');
        // Extra AF method indicators (Method B + LF/MF follow-on)
        const extraChips = [];
        if (metadata.rbds_af_method_b) {
            const tunedTxt = isPresent(metadata.rbds_af_tuning_frequency)
                ? ` @ ${metadata.rbds_af_tuning_frequency} MHz` : '';
            extraChips.push(
                `<span class="rbds-flag rbds-flag--info rbds-flag--active" ` +
                `aria-label="Alternative frequencies signalled using Method B${tunedTxt}">` +
                `<i class="fas fa-shuffle" aria-hidden="true"></i>` +
                `<span>Method B${escapeHtml(tunedTxt)}</span></span>`
            );
        }
        if (metadata.rbds_af_follow_on_indicator) {
            extraChips.push(
                `<span class="rbds-flag rbds-flag--info rbds-flag--active" ` +
                `aria-label="LF or MF follow-on frequencies present">` +
                `<i class="fas fa-tower-broadcast" aria-hidden="true"></i>` +
                `<span>LF/MF follow-on</span></span>`
            );
        }
        const chipsRow = extraChips.length
            ? `<div class="rbds-af__flags d-flex flex-wrap gap-1 mt-1">${extraChips.join('')}</div>`
            : '';
        return (
            `<section class="rbds-af" aria-label="Alternative frequencies">` +
            `<h6 class="rbds-section-h"><i class="fas fa-tower-cell" aria-hidden="true"></i> Alternative Frequencies ${completion}</h6>` +
            `<div class="rbds-af__list">${pills}</div>` +
            chipsRow +
            `</section>`
        );
    }

    // ---- Station Identity table -------------------------------------------

    function buildIdentityTable(metadata) {
        const rows = [];
        function add(label, value) {
            if (!isPresent(value)) return;
            rows.push(
                `<tr><th scope="row" class="text-muted">${escapeHtml(label)}</th>` +
                `<td>${value}</td></tr>`
            );
        }
        add('PI Code', isPresent(metadata.rbds_pi_code)
            ? `<code>${escapeHtml(metadata.rbds_pi_code)}</code>` : null);
        if (isPresent(metadata.rbds_pi_country_code)) {
            add('Country code', `<code>${escapeHtml(hex(metadata.rbds_pi_country_code))}</code>`);
        }
        if (isPresent(metadata.rbds_pi_area_code)) {
            add('Area code', `<code>${escapeHtml(hex(metadata.rbds_pi_area_code))}</code>`);
        }
        if (isPresent(metadata.rbds_pi_program_ref)) {
            add('Programme ref', `<code>${escapeHtml(hex(metadata.rbds_pi_program_ref, 2))}</code>`);
        }
        if (isPresent(metadata.rbds_ecc)) {
            add('Extended country (ECC)', `<code>${escapeHtml(hex(metadata.rbds_ecc, 2))}</code>`);
        }
        if (isPresent(metadata.rbds_pty_name)) {
            add('Programme type name (PTYN)', escapeHtml(metadata.rbds_pty_name));
        }
        add('Language', isPresent(metadata.rbds_language_name)
            ? escapeHtml(metadata.rbds_language_name) : null);
        if (isPresent(metadata.rbds_language_code)) {
            add('Language code', `<code>${escapeHtml(hex(metadata.rbds_language_code, 2))}</code>`);
        }
        if (isPresent(metadata.rbds_linkage_set_number)) {
            add('Linkage set', `<code>${escapeHtml(hex(metadata.rbds_linkage_set_number, 3))}</code>`);
        }
        if (isPresent(metadata.rbds_linkage_actuator)) {
            add('Linkage actuator', metadata.rbds_linkage_actuator
                ? '<span class="rbds-flag rbds-flag--warning rbds-flag--active"><i class="fas fa-bolt" aria-hidden="true"></i><span>Active</span></span>'
                : '<span class="rbds-flag rbds-flag--neutral rbds-flag--inactive"><i class="fas fa-circle" aria-hidden="true"></i><span>Inactive</span></span>');
        }
        if (isPresent(metadata.rbds_linkage_soft_coupling)) {
            add('Soft coupling', metadata.rbds_linkage_soft_coupling
                ? '<span class="rbds-flag rbds-flag--info rbds-flag--active"><i class="fas fa-link" aria-hidden="true"></i><span>Yes</span></span>'
                : '<span class="rbds-flag rbds-flag--neutral rbds-flag--inactive"><i class="fas fa-link-slash" aria-hidden="true"></i><span>No</span></span>');
        }
        if (isPresent(metadata.rbds_clock_time_local)) {
            add('Broadcast clock', `<span class="font-monospace">${escapeHtml(metadata.rbds_clock_time_local)}</span>`);
        } else if (isPresent(metadata.rbds_clock_time_utc)) {
            add('Broadcast clock (UTC)', `<span class="font-monospace">${escapeHtml(metadata.rbds_clock_time_utc)}</span>`);
        }
        if (isPresent(metadata.rbds_pin_day) && isPresent(metadata.rbds_pin_hour) && isPresent(metadata.rbds_pin_minute)) {
            const hh = String(metadata.rbds_pin_hour).padStart(2, '0');
            const mm = String(metadata.rbds_pin_minute).padStart(2, '0');
            add('Programme item (PIN)', `Day ${escapeHtml(metadata.rbds_pin_day)} at ${escapeHtml(hh)}:${escapeHtml(mm)}`);
        }

        if (!rows.length) return '';
        return (
            `<section class="rbds-identity" aria-label="Station identity details">` +
            `<h6 class="rbds-section-h"><i class="fas fa-id-card" aria-hidden="true"></i> Station Identity</h6>` +
            `<table class="table table-sm rbds-identity__table">` +
            `<caption class="sr-only">Detailed station identity decoded from RBDS.</caption>` +
            `<tbody>${rows.join('')}</tbody>` +
            `</table>` +
            `</section>`
        );
    }

    // ---- EON (Enhanced Other Networks) ------------------------------------

    function buildEON(metadata) {
        const list = metadata.rbds_eon_list;
        if (!Array.isArray(list) || list.length === 0) return '';
        const rows = list.map(e => {
            const af = (Array.isArray(e.af) && e.af.length)
                ? e.af.map(f => `${escapeHtml(f)} MHz`).join(', ')
                : '—';
            const linkage = isPresent(e.linkage) ? hex(e.linkage, 4) : '—';
            const pinTxt = isPresent(e.pin_day)
                ? `Day ${escapeHtml(e.pin_day)} ${String(e.pin_hour).padStart(2, '0')}:${String(e.pin_minute).padStart(2, '0')}`
                : '—';
            return (
                `<tr>` +
                `<td><code>${escapeHtml(e.pi || '')}</code></td>` +
                `<td>${escapeHtml((e.ps || '').trim())}</td>` +
                `<td>${e.tp ? '<i class="fas fa-check text-success" aria-label="Yes"></i>' : '<span aria-label="No">—</span>'}</td>` +
                `<td>${e.ta ? '<i class="fas fa-triangle-exclamation text-warning" aria-label="Active"></i>' : '<span aria-label="Inactive">—</span>'}</td>` +
                `<td>${isPresent(e.pty) ? escapeHtml(e.pty) : '—'}</td>` +
                `<td class="font-monospace small">${af}</td>` +
                `<td class="font-monospace small">${escapeHtml(linkage)}</td>` +
                `<td class="font-monospace small">${pinTxt}</td>` +
                `</tr>`
            );
        }).join('');
        return (
            `<details class="rbds-eon">` +
            `<summary><i class="fas fa-diagram-project" aria-hidden="true"></i> Linked Networks (EON) — ${list.length}</summary>` +
            `<div class="table-responsive">` +
            `<table class="table table-sm rbds-eon__table">` +
            `<caption class="sr-only">Enhanced Other Networks linked stations.</caption>` +
            `<thead><tr>` +
            `<th scope="col">PI</th><th scope="col">PS</th><th scope="col">TP</th>` +
            `<th scope="col">TA</th><th scope="col">PTY</th><th scope="col">AF</th>` +
            `<th scope="col">Linkage</th><th scope="col">PIN</th>` +
            `</tr></thead>` +
            `<tbody>${rows}</tbody>` +
            `</table></div>` +
            `</details>`
        );
    }

    // ---- Open Data Applications (ODA) ------------------------------------

    function buildODA(metadata) {
        const assignments = metadata.rbds_oda_assignments;
        const apps = metadata.rbds_oda_apps;
        const payloads = metadata.rbds_oda_payloads;
        const hasAssignments = Array.isArray(assignments) && assignments.length > 0;
        const hasApps = !hasAssignments && Array.isArray(apps) && apps.length > 0;
        const hasPayloads = Array.isArray(payloads) && payloads.length > 0;
        if (!hasAssignments && !hasApps && !hasPayloads) return '';

        let body = '';
        if (hasAssignments) {
            const rows = assignments.map(a => (
                `<tr>` +
                `<td><code>${escapeHtml(a.group || '')}</code></td>` +
                `<td><code>${escapeHtml(a.aid_hex || '')}</code></td>` +
                `<td>${escapeHtml(a.name || '')}</td>` +
                `</tr>`
            )).join('');
            body += (
                `<div class="table-responsive">` +
                `<table class="table table-sm rbds-oda__table">` +
                `<caption class="sr-only">ODA application identifier assignments.</caption>` +
                `<thead><tr><th scope="col">Group</th><th scope="col">AID</th><th scope="col">Name</th></tr></thead>` +
                `<tbody>${rows}</tbody>` +
                `</table></div>`
            );
        } else if (hasApps) {
            const pills = apps.map(id =>
                `<span class="rbds-af-pill"><code>${escapeHtml(hex(id, 4))}</code></span>`
            ).join('');
            body += `<div class="rbds-af__list">${pills}</div>`;
        }
        if (hasPayloads) {
            const rows = payloads.map(p => (
                `<tr>` +
                `<td><code>${escapeHtml(p.aid_hex || '')}</code></td>` +
                `<td><code>${escapeHtml(p.group || '')}</code></td>` +
                `<td class="font-monospace">${escapeHtml(p.count)}</td>` +
                `<td><code>${escapeHtml(hex(p.last_b_low, 2))}</code></td>` +
                `<td><code>${escapeHtml(hex(p.last_c, 4))}</code></td>` +
                `<td><code>${escapeHtml(hex(p.last_d, 4))}</code></td>` +
                `</tr>`
            )).join('');
            body += (
                `<h6 class="rbds-section-h mt-2"><i class="fas fa-database" aria-hidden="true"></i> Raw ODA payloads (no decoder)</h6>` +
                `<div class="table-responsive">` +
                `<table class="table table-sm rbds-oda__table">` +
                `<caption class="sr-only">Raw ODA payloads observed without a decoder.</caption>` +
                `<thead><tr>` +
                `<th scope="col">AID</th><th scope="col">Group</th><th scope="col">Count</th>` +
                `<th scope="col">Last B[4:0]</th><th scope="col">Last C</th><th scope="col">Last D</th>` +
                `</tr></thead>` +
                `<tbody>${rows}</tbody>` +
                `</table></div>`
            );
        }

        return (
            `<details class="rbds-eon">` +
            `<summary><i class="fas fa-puzzle-piece" aria-hidden="true"></i> Open Data Applications (ODA)</summary>` +
            `<div class="rbds-details__body">${body}</div>` +
            `</details>`
        );
    }

    // ---- Slow Labelling (Group 1A variants) -------------------------------

    function buildSlowLabelling(metadata) {
        const raw = metadata.rbds_slow_labelling_raw;
        if (!raw || typeof raw !== 'object' || Object.keys(raw).length === 0) return '';
        const rows = Object.entries(raw)
            .sort((a, b) => parseInt(a[0], 10) - parseInt(b[0], 10))
            .map(([variant, value]) => {
                let decoded = '—';
                if (variant === '0' && isPresent(metadata.rbds_language_name)) {
                    decoded = `language ${escapeHtml(metadata.rbds_language_name)}`;
                } else if (variant === '1' && isPresent(metadata.rbds_paging_tmc_id)) {
                    decoded = `TMC id <code>${escapeHtml(hex(metadata.rbds_paging_tmc_id, 3))}</code>`;
                } else if (variant === '2' && isPresent(metadata.rbds_paging_operator_code)) {
                    decoded = `paging op <code>${escapeHtml(hex(metadata.rbds_paging_operator_code, 3))}</code>`;
                } else if (variant === '3' && isPresent(metadata.rbds_language_name)) {
                    decoded = `language ${escapeHtml(metadata.rbds_language_name)}`;
                } else if (variant === '4' && isPresent(metadata.rbds_ecc)) {
                    decoded = `ECC <code>${escapeHtml(hex(metadata.rbds_ecc, 2))}</code>`;
                } else if (variant === '5' && isPresent(metadata.rbds_linkage_set_number)) {
                    decoded = `LSN <code>${escapeHtml(hex(metadata.rbds_linkage_set_number, 3))}</code>`;
                } else if (variant === '6') {
                    decoded = 'broadcaster-use';
                } else if (variant === '7' && isPresent(metadata.rbds_ews_channel_identifier)) {
                    decoded = `EWS chan-id <code>${escapeHtml(hex(metadata.rbds_ews_channel_identifier, 3))}</code>`;
                }
                return (
                    `<tr>` +
                    `<td><code>${escapeHtml(variant)}</code></td>` +
                    `<td><code>${escapeHtml(hex(value, 4))}</code></td>` +
                    `<td>${decoded}</td>` +
                    `</tr>`
                );
            }).join('');
        return (
            `<details class="rbds-eon">` +
            `<summary><i class="fas fa-tags" aria-hidden="true"></i> Slow Labelling (Group 1A variants)</summary>` +
            `<div class="rbds-details__body">` +
            `<div class="table-responsive">` +
            `<table class="table table-sm rbds-oda__table">` +
            `<caption class="sr-only">Slow labelling variants observed in Group 1A.</caption>` +
            `<thead><tr><th scope="col">Variant</th><th scope="col">Raw Block D</th><th scope="col">Decoded</th></tr></thead>` +
            `<tbody>${rows}</tbody>` +
            `</table></div>` +
            `</div></details>`
        );
    }

    // ---- Radio Paging (Group 7A and 13A) ----------------------------------

    function buildPagingTables(metadata) {
        const basic = metadata.rbds_paging_messages;
        const enhanced = metadata.rbds_enhanced_paging_messages;
        const hasBasic = Array.isArray(basic) && basic.length > 0;
        const hasEnhanced = Array.isArray(enhanced) && enhanced.length > 0;
        if (!hasBasic && !hasEnhanced) return '';
        const fmtTime = (ts) => {
            if (!isPresent(ts)) return '';
            return new Date(Number(ts) * 1000).toLocaleTimeString();
        };
        let body = '';
        if (hasBasic) {
            const rows = basic.slice().reverse().map(m => (
                `<tr>` +
                `<td class="font-monospace small">${escapeHtml(fmtTime(m.unix_ts))}</td>` +
                `<td><code>${escapeHtml(m.paging_segment)}</code></td>` +
                `<td>${m.a_b_flag ? 'B' : 'A'}</td>` +
                `<td><code>${escapeHtml(hex(m.block_c, 4))}</code></td>` +
                `<td><code>${escapeHtml(hex(m.block_d, 4))}</code></td>` +
                `</tr>`
            )).join('');
            body += (
                `<h6 class="rbds-section-h"><i class="fas fa-pager" aria-hidden="true"></i> Radio Paging (Group 7A) — last ${escapeHtml(basic.length)}</h6>` +
                `<div class="table-responsive">` +
                `<table class="table table-sm rbds-oda__table">` +
                `<caption class="sr-only">Recent Group 7A radio paging messages.</caption>` +
                `<thead><tr>` +
                `<th scope="col">Time</th><th scope="col">Seg</th><th scope="col">A/B</th>` +
                `<th scope="col">Block C</th><th scope="col">Block D</th>` +
                `</tr></thead>` +
                `<tbody>${rows}</tbody>` +
                `</table></div>`
            );
        }
        if (hasEnhanced) {
            const rows = enhanced.slice().reverse().map(m => (
                `<tr>` +
                `<td class="font-monospace small">${escapeHtml(fmtTime(m.unix_ts))}</td>` +
                `<td><code>${escapeHtml(hex(m.block_b_low, 2))}</code></td>` +
                `<td><code>${escapeHtml(hex(m.block_c, 4))}</code></td>` +
                `<td><code>${escapeHtml(hex(m.block_d, 4))}</code></td>` +
                `</tr>`
            )).join('');
            body += (
                `<h6 class="rbds-section-h mt-2"><i class="fas fa-pager" aria-hidden="true"></i> Enhanced Paging (Group 13A) — last ${escapeHtml(enhanced.length)}</h6>` +
                `<div class="table-responsive">` +
                `<table class="table table-sm rbds-oda__table">` +
                `<caption class="sr-only">Recent Group 13A enhanced paging messages.</caption>` +
                `<thead><tr>` +
                `<th scope="col">Time</th><th scope="col">B[4:0]</th>` +
                `<th scope="col">Block C</th><th scope="col">Block D</th>` +
                `</tr></thead>` +
                `<tbody>${rows}</tbody>` +
                `</table></div>`
            );
        }
        return (
            `<details class="rbds-eon">` +
            `<summary><i class="fas fa-pager" aria-hidden="true"></i> Radio Paging</summary>` +
            `<div class="rbds-details__body">${body}</div>` +
            `</details>`
        );
    }

    // ---- Transparent Data Channel (TDC) -----------------------------------

    function buildTDC(metadata) {
        const channels = metadata.rbds_tdc_channels;
        const fallback = metadata.rbds_tdc_data;
        const hasChannels = channels && typeof channels === 'object' && Object.keys(channels).length > 0;
        if (!hasChannels && !isPresent(fallback)) return '';
        let body = '';
        if (hasChannels) {
            body = Object.entries(channels)
                .sort((a, b) => parseInt(a[0], 10) - parseInt(b[0], 10))
                .map(([ch, hexStr]) => (
                    `<div class="d-flex justify-content-between mb-1 small">` +
                    `<span class="text-muted">Channel ${escapeHtml(ch)}</span>` +
                    `<span class="text-muted">${escapeHtml(((hexStr || '').length / 2))} bytes</span>` +
                    `</div>` +
                    `<div class="font-monospace small text-break bg-light p-1 rounded mb-1" style="max-height:60px;overflow-y:auto;">${escapeHtml(hexStr)}</div>`
                )).join('');
        } else {
            body = `<div class="font-monospace small text-break bg-light p-1 rounded mb-1" style="max-height:60px;overflow-y:auto;">${escapeHtml(fallback)}</div>`;
        }
        return (
            `<details class="rbds-eon">` +
            `<summary><i class="fas fa-microchip" aria-hidden="true"></i> Transparent Data Channel (TDC)</summary>` +
            `<div class="rbds-details__body">${body}</div>` +
            `</details>`
        );
    }

    // ---- In-House Application Data ----------------------------------------

    function buildInHouse(metadata) {
        const data = metadata.rbds_in_house_data;
        if (!Array.isArray(data) || data.length === 0) return '';
        const words = data.map(w => Number(w).toString(16).toUpperCase().padStart(4, '0')).join(' ');
        return (
            `<details class="rbds-eon">` +
            `<summary><i class="fas fa-warehouse" aria-hidden="true"></i> In-House Application Data</summary>` +
            `<div class="rbds-details__body">` +
            `<div class="font-monospace small text-break bg-light p-1 rounded mb-1">${escapeHtml(words)}</div>` +
            `</div></details>`
        );
    }

    // ---- Fast Switching (Group 15B) ---------------------------------------

    function buildFastSwitching(metadata) {
        const tp = metadata.rbds_fast_tp;
        const ta = metadata.rbds_fast_ta;
        const ms = metadata.rbds_fast_ms;
        const di = metadata.rbds_fast_di_bits;
        if (!isPresent(tp) && !isPresent(ta) && !isPresent(ms) && !isPresent(di)) return '';
        const chips = [];
        if (isPresent(tp)) {
            chips.push(flagChip({
                variant: 'info',
                icon: 'fas fa-traffic-light',
                label: tp ? 'TP' : 'TP off',
                srLabel: tp ? 'Fast Traffic Programme: yes.' : 'Fast Traffic Programme: no.',
                active: !!tp,
            }));
        }
        if (isPresent(ta)) {
            chips.push(flagChip({
                variant: 'warning',
                icon: 'fas fa-triangle-exclamation',
                label: ta ? 'TA active' : 'TA off',
                srLabel: ta ? 'Fast Traffic Announcement: active.' : 'Fast Traffic Announcement: off.',
                active: !!ta,
            }));
        }
        if (isPresent(ms)) {
            chips.push(flagChip({
                variant: 'neutral',
                icon: ms ? 'fas fa-music' : 'fas fa-microphone',
                label: ms ? 'Music' : 'Speech',
                srLabel: ms ? 'Fast M/S: music.' : 'Fast M/S: speech.',
                active: !!ms,
            }));
        }
        if (isPresent(di)) {
            chips.push(
                `<span class="rbds-flag rbds-flag--neutral" aria-label="Fast DI bits ${escapeHtml(hex(di))}">` +
                `<i class="fas fa-bars" aria-hidden="true"></i>` +
                `<span>DI <code>${escapeHtml(hex(di))}</code></span></span>`
            );
        }
        return (
            `<section class="rbds-fast" aria-label="Fast switching information (Group 15B)">` +
            `<h6 class="rbds-section-h"><i class="fas fa-bolt" aria-hidden="true"></i> Fast Switching (Group 15B)</h6>` +
            `<div class="d-flex flex-wrap gap-1">${chips.join('')}</div>` +
            `</section>`
        );
    }

    // ---- Main station card -----------------------------------------------
    // Returns the HTML for the structured RBDS panel, or '' if no useful data.
    // Options:
    //   compact: true => skip details accordion (used in receiver tile)
    //   showEWS: false => skip EWS banner (caller renders it elsewhere)
    function buildStationCard(metadata, options) {
        if (!metadata) return '';
        options = options || {};
        const compact = !!options.compact;
        const includeEWS = options.showEWS !== false;

        const lockState = metadata.rbds_lock_state;
        const hasAny = (
            isPresent(metadata.rbds_ps_name) || isPresent(metadata.rbds_pi_code) ||
            isPresent(metadata.rbds_radio_text) || isPresent(metadata.rbds_pty) ||
            isPresent(metadata.rbds_call_sign) || isPresent(metadata.rbds_program_type_name) ||
            isPresent(metadata.rbds_clock_time_local) || isPresent(metadata.rbds_ews_channel)
        );

        // Don't render if there's nothing decoded AND no lock-state hint
        if (!hasAny && !['LOCKING', 'LOCKED', 'DISABLED'].includes(lockState)) {
            return '';
        }

        // Lock-state badge
        let lockBadge = '';
        if (lockState === 'LOCKED') {
            lockBadge = `<span class="rbds-lock rbds-lock--locked" aria-label="Decoder locked"><i class="fas fa-link" aria-hidden="true"></i> Locked</span>`;
        } else if (lockState === 'LOCKING') {
            lockBadge = `<span class="rbds-lock rbds-lock--locking" aria-label="Decoder acquiring sync"><i class="fas fa-sync fa-spin" aria-hidden="true"></i> Acquiring</span>`;
        } else if (lockState === 'DISABLED') {
            lockBadge = `<span class="rbds-lock rbds-lock--disabled" aria-label="RBDS decoding disabled"><i class="fas fa-power-off" aria-hidden="true"></i> Disabled</span>`;
        }

        // Header bits
        const heartbeat = heartbeatHTML(metadata.rbds_last_seen);
        const callSign = isPresent(metadata.rbds_call_sign)
            ? `<strong class="rbds-call">${escapeHtml(metadata.rbds_call_sign)}</strong>` : '';
        const piCode = isPresent(metadata.rbds_pi_code)
            ? `<code class="rbds-pi" aria-label="Programme ID code ${escapeHtml(metadata.rbds_pi_code)}">${escapeHtml(metadata.rbds_pi_code)}</code>` : '';

        // PS LCD panel — always rendered if RBDS section is shown so the
        // user has a clear placeholder when no PS has decoded yet.
        const psName = isPresent(metadata.rbds_ps_name) ? metadata.rbds_ps_name : '';
        const psDisplay = psName ? psName : '— — — — — — — —';
        const psAria = psName
            ? `Programme service name: ${psName}`
            : 'Programme service name not yet decoded';
        const psPanel = (
            `<div class="rbds-ps" aria-label="${escapeHtml(psAria)}">` +
            `<span class="rbds-ps__label" aria-hidden="true">PS</span>` +
            `<span class="rbds-ps__lcd${psName ? '' : ' rbds-ps__lcd--empty'}" aria-hidden="true">${escapeHtml(psDisplay)}</span>` +
            `</div>`
        );

        const ptyBadge = ptyBadgeHTML(metadata);
        const flagsRow = flagsRowHTML(metadata);
        const nowPlaying = buildNowPlaying(metadata);
        const ewsBanner = includeEWS ? buildEWSBanner(metadata) : '';

        // Hint when no decoded content yet
        let hint = '';
        if (!hasAny) {
            if (lockState === 'DISABLED') {
                hint = `<p class="rbds-hint"><i class="fas fa-power-off" aria-hidden="true"></i> RBDS decoding is turned off for this receiver. Enable it in the receiver settings to see PS, PI, RT and other RBDS data.</p>`;
            } else if (lockState === 'LOCKED') {
                hint = `<p class="rbds-hint"><i class="fas fa-clock" aria-hidden="true"></i> Decoder locked — waiting for the station to transmit RBDS groups.</p>`;
            } else {
                hint = `<p class="rbds-hint"><i class="fas fa-sync fa-spin" aria-hidden="true"></i> Decoder is acquiring sync; PS, PI and RT will appear once enough valid groups arrive.</p>`;
            }
        }

        // Details accordion (full mode only)
        let details = '';
        if (!compact) {
            const identity = buildIdentityTable(metadata);
            const af = buildAFList(metadata);
            const fastSw = buildFastSwitching(metadata);
            const eon = buildEON(metadata);
            const oda = buildODA(metadata);
            const slow = buildSlowLabelling(metadata);
            const paging = buildPagingTables(metadata);
            const tdc = buildTDC(metadata);
            const inHouse = buildInHouse(metadata);
            if (identity || af || fastSw || eon || oda || slow || paging || tdc || inHouse) {
                details = (
                    `<details class="rbds-details">` +
                    `<summary><i class="fas fa-list" aria-hidden="true"></i> RBDS Details</summary>` +
                    `<div class="rbds-details__body">` +
                    identity + af + fastSw + eon + oda + slow + paging + tdc + inHouse +
                    `</div>` +
                    `</details>`
                );
            }
        }

        const updatedFooter = (() => {
            const seen = metadata.rbds_last_seen;
            const updated = metadata.rbds_last_updated;
            if (!isPresent(seen) && !isPresent(updated)) return '';
            const parts = [];
            if (isPresent(seen)) {
                parts.push(`<span><i class="fas fa-satellite-dish" aria-hidden="true"></i> Last group: ${escapeHtml(new Date(Number(seen) * 1000).toLocaleTimeString())}</span>`);
            }
            if (isPresent(updated)) {
                parts.push(`<span><i class="fas fa-rotate" aria-hidden="true"></i> Content changed: ${escapeHtml(new Date(Number(updated) * 1000).toLocaleTimeString())}</span>`);
            }
            return `<footer class="rbds-station__footer">${parts.join('')}</footer>`;
        })();

        return (
            ewsBanner +
            `<section class="rbds-station" aria-label="RBDS station information">` +
            `<header class="rbds-station__head">` +
            `<div class="rbds-station__id">` +
            `<i class="fas fa-broadcast-tower rbds-station__icon" aria-hidden="true"></i>` +
            `<span class="rbds-station__title">RBDS / RDS</span>` +
            (callSign ? ` <span class="rbds-station__call">${callSign}</span>` : '') +
            (piCode ? ` <span class="rbds-station__pi">${piCode}</span>` : '') +
            `</div>` +
            `<div class="rbds-station__status">${lockBadge}${heartbeat}</div>` +
            `</header>` +
            `<div class="rbds-station__body">` +
            psPanel +
            (ptyBadge ? `<div class="rbds-station__pty">${ptyBadge}</div>` : '') +
            (nowPlaying ? `<div class="rbds-station__rt">${nowPlaying}</div>` : '') +
            (flagsRow ? flagsRow : '') +
            hint +
            details +
            `</div>` +
            updatedFooter +
            `</section>`
        );
    }

    // ---- Decoder Health card (group counts + sync stats) ------------------

    function buildDecoderHealthCard(metadata) {
        if (!metadata) return '';
        const total = Number(metadata.rbds_blocks_total || 0);
        const counts = metadata.rbds_group_type_counts;
        const hasCounts = counts && typeof counts === 'object' && Object.keys(counts).length > 0;

        if (!total && !hasCounts && !isPresent(metadata.rbds_last_seen)) {
            return '';
        }

        // Group-type segmented bar
        let groupBar = '';
        if (hasCounts) {
            const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
            const grandTotal = entries.reduce((s, [, n]) => s + Number(n || 0), 0);
            // Friendly descriptions for common group types
            const GROUP_DESC = {
                '0A': 'Programme service name + AF',
                '0B': 'Programme service name (no AF)',
                '1A': 'Slow labelling, programme item',
                '1B': 'Programme item number',
                '2A': 'Radio text (long)',
                '2B': 'Radio text (short)',
                '3A': 'ODA application identifiers',
                '4A': 'Clock time and date',
                '7A': 'Radio paging',
                '8A': 'Traffic Message Channel',
                '10A': 'Programme type name',
                '13A': 'Enhanced radio paging',
                '14A': 'Enhanced Other Networks',
                '14B': 'Enhanced Other Networks (TA flag)',
                '15B': 'Fast switching information',
            };
            const COLOR_CYCLE = ['rbds-gt--a', 'rbds-gt--b', 'rbds-gt--c', 'rbds-gt--d', 'rbds-gt--e', 'rbds-gt--f'];
            const segments = entries.map(([gt, n], idx) => {
                const pct = grandTotal ? (100 * n / grandTotal) : 0;
                const desc = GROUP_DESC[gt] || 'Group type';
                return (
                    `<span class="rbds-gt-seg ${COLOR_CYCLE[idx % COLOR_CYCLE.length]}" ` +
                    `style="flex: ${pct.toFixed(2)} 1 0;" ` +
                    `title="${escapeHtml(`${gt} — ${desc}: ${n} groups (${pct.toFixed(1)}%)`)}" ` +
                    `aria-label="${escapeHtml(`Group ${gt}, ${desc}, ${n} groups, ${pct.toFixed(1)} percent.`)}">` +
                    `<span class="sr-only">${escapeHtml(`${gt}: ${n}`)}</span>` +
                    `</span>`
                );
            }).join('');
            const legend = entries.map(([gt, n], idx) => {
                const desc = GROUP_DESC[gt] || 'Group type';
                return (
                    `<li class="rbds-gt-legend__item">` +
                    `<span class="rbds-gt-legend__sw ${COLOR_CYCLE[idx % COLOR_CYCLE.length]}" aria-hidden="true"></span>` +
                    `<code class="rbds-gt-legend__code">${escapeHtml(gt)}</code>` +
                    `<span class="rbds-gt-legend__desc">${escapeHtml(desc)}</span>` +
                    `<span class="rbds-gt-legend__count">${escapeHtml(n)}</span>` +
                    `</li>`
                );
            }).join('');
            groupBar = (
                `<div class="rbds-health__section" aria-label="Group type traffic">` +
                `<h6 class="rbds-section-h"><i class="fas fa-chart-bar" aria-hidden="true"></i> Group Type Traffic</h6>` +
                `<div class="rbds-gt-bar" role="img" aria-label="${escapeHtml(`Distribution across ${entries.length} group types, total ${grandTotal} groups`)}">${segments}</div>` +
                `<ul class="rbds-gt-legend">${legend}</ul>` +
                `</div>`
            );
        }

        // Sync / BLER block
        let syncBlock = '';
        if (total > 0) {
            const ok = Number(metadata.rbds_blocks_ok || 0);
            const fec1 = Number(metadata.rbds_blocks_fec_single || 0);
            const fecB = Number(metadata.rbds_blocks_fec_burst || 0);
            const bad = Number(metadata.rbds_blocks_uncorrected || 0);
            const pct = (n) => total ? (100 * n / total) : 0;
            const rawBler = isPresent(metadata.rbds_raw_bler) ? (Number(metadata.rbds_raw_bler) * 100).toFixed(2) + '%' : '—';
            const netBler = isPresent(metadata.rbds_net_bler) ? (Number(metadata.rbds_net_bler) * 100).toFixed(2) + '%' : '—';

            const stack = (
                `<div class="rbds-bler-bar" role="img" ` +
                `aria-label="${escapeHtml(`Block error breakdown: ${pct(ok).toFixed(1)} percent clean, ${pct(fec1).toFixed(1)} percent corrected single bit, ${pct(fecB).toFixed(1)} percent corrected burst, ${pct(bad).toFixed(1)} percent uncorrected.`)}">` +
                `<span class="rbds-bler-seg rbds-bler-seg--ok"   style="flex: ${pct(ok).toFixed(2)} 1 0;"   title="Clean ${ok}"></span>` +
                `<span class="rbds-bler-seg rbds-bler-seg--fec1" style="flex: ${pct(fec1).toFixed(2)} 1 0;" title="FEC-1 ${fec1}"></span>` +
                `<span class="rbds-bler-seg rbds-bler-seg--fecb" style="flex: ${pct(fecB).toFixed(2)} 1 0;" title="FEC-burst ${fecB}"></span>` +
                `<span class="rbds-bler-seg rbds-bler-seg--bad"  style="flex: ${pct(bad).toFixed(2)} 1 0;"  title="Uncorrected ${bad}"></span>` +
                `</div>`
            );

            const syncedFor = isPresent(metadata.rbds_sync_acquired_unix)
                ? `${Math.max(0, Math.floor((Date.now() / 1000) - Number(metadata.rbds_sync_acquired_unix)))} s`
                : '—';
            const drops = isPresent(metadata.rbds_sync_lost_count) ? metadata.rbds_sync_lost_count : '—';
            const dropped = isPresent(metadata.rbds_chunks_dropped) ? metadata.rbds_chunks_dropped : '—';

            syncBlock = (
                `<div class="rbds-health__section" aria-label="Decoder synchronisation health">` +
                `<h6 class="rbds-section-h"><i class="fas fa-heart-pulse" aria-hidden="true"></i> Sync &amp; Block Error Rate</h6>` +
                stack +
                `<div class="rbds-bler-legend" aria-hidden="true">` +
                `<span class="rbds-bler-legend__item"><span class="rbds-bler-sw rbds-bler-seg--ok"></span> Clean ${escapeHtml(ok)} (${pct(ok).toFixed(1)}%)</span>` +
                `<span class="rbds-bler-legend__item"><span class="rbds-bler-sw rbds-bler-seg--fec1"></span> FEC-1 ${escapeHtml(fec1)} (${pct(fec1).toFixed(1)}%)</span>` +
                `<span class="rbds-bler-legend__item"><span class="rbds-bler-sw rbds-bler-seg--fecb"></span> FEC-burst ${escapeHtml(fecB)} (${pct(fecB).toFixed(1)}%)</span>` +
                `<span class="rbds-bler-legend__item"><span class="rbds-bler-sw rbds-bler-seg--bad"></span> Uncorrected ${escapeHtml(bad)} (${pct(bad).toFixed(1)}%)</span>` +
                `</div>` +
                `<dl class="rbds-stats" aria-label="Synchronisation statistics">` +
                `<div><dt>Raw BLER</dt><dd class="font-monospace">${escapeHtml(rawBler)}</dd></div>` +
                `<div><dt>Net BLER (after FEC)</dt><dd class="font-monospace">${escapeHtml(netBler)}</dd></div>` +
                `<div><dt>Blocks / Groups</dt><dd class="font-monospace">${escapeHtml(total)} / ${escapeHtml(metadata.rbds_groups_decoded || 0)}</dd></div>` +
                `<div><dt>Synced for</dt><dd class="font-monospace">${escapeHtml(syncedFor)}</dd></div>` +
                `<div><dt>Sync drops</dt><dd class="font-monospace">${escapeHtml(drops)}</dd></div>` +
                `<div><dt>Queue chunks dropped</dt><dd class="font-monospace ${Number(dropped) > 0 ? 'text-warning' : ''}">${escapeHtml(dropped)}</dd></div>` +
                `</dl>` +
                `</div>`
            );
        }

        const heartbeat = (
            `<div class="rbds-health__heartbeat">${heartbeatHTML(metadata.rbds_last_seen)}</div>`
        );

        return (
            `<section class="rbds-health" aria-label="RBDS decoder health">` +
            heartbeat +
            groupBar +
            syncBlock +
            `</section>`
        );
    }

    // ---- Public API -------------------------------------------------------

    const RBDSViz = {
        escapeHtml,
        isPresent,
        heartbeatState,
        heartbeatHTML,
        ptyStyle,
        ptyBadgeHTML,
        flagsRowHTML,
        buildEWSBanner,
        buildNowPlaying,
        buildAFList,
        buildIdentityTable,
        buildEON,
        buildODA,
        buildSlowLabelling,
        buildPagingTables,
        buildTDC,
        buildInHouse,
        buildFastSwitching,
        buildStationCard,
        buildDecoderHealthCard,
    };

    global.RBDSViz = RBDSViz;
})(typeof window !== 'undefined' ? window : this);
