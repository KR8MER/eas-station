/**
 * Admin Panel — Hardware Settings page
 *
 * Drives the tabbed Hardware Settings page: tab switching, GPS live
 * polling and HAT diagnostics, LED connection-type toggling, Zigbee
 * auto-detect, NeoPixel brightness preview, form save and service
 * restart. Reads endpoint URLs from window.HWSettingsConfig (injected
 * by the template).
 */

if (typeof window.HWSettingsConfig === 'undefined') {
    window.HWSettingsConfig = { restartUrl: '/admin/hardware/restart', updateUrl: '/admin/hardware' };
}

(function() {
    // Tab switching
    var tabs = document.querySelectorAll('.hw-tabs .nav-link[data-tab]');
    var panels = document.querySelectorAll('.hw-panel');

    function activateTab(target) {
        if (!target) return;
        tabs.forEach(function(t) {
            t.classList.toggle('active', t.getAttribute('data-tab') === target);
        });
        panels.forEach(function(p) { p.classList.remove('active'); });
        var panel = document.getElementById('panel-' + target);
        if (panel) panel.classList.add('active');

        if (target === 'led') updateLEDConnectionVisibility();
        if (target === 'gps') {
            startGpsPolling();
        } else {
            stopGpsPolling();
        }
    }

    tabs.forEach(function(tab) {
        tab.addEventListener('click', function() {
            activateTab(this.getAttribute('data-tab'));
        });
    });

    // "Configure →" buttons in the Overview panel jump to a specific device tab.
    document.querySelectorAll('.hw-overview-go[data-go-to]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            activateTab(this.getAttribute('data-go-to'));
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    });

    // LED connection type toggle
    function updateLEDConnectionVisibility() {
        var networkRadio = document.getElementById('led_network');
        var networkSettings = document.getElementById('led-network-settings');
        var serialSettings = document.getElementById('led-serial-settings');
        if (!networkRadio || !networkSettings || !serialSettings) return;

        if (networkRadio.checked) {
            networkSettings.style.display = '';
            serialSettings.style.display = 'none';
        } else {
            networkSettings.style.display = 'none';
            serialSettings.style.display = '';
        }
    }

    document.querySelectorAll('input[name="led_connection_type"]').forEach(function(radio) {
        radio.addEventListener('change', updateLEDConnectionVisibility);
    });
    updateLEDConnectionVisibility();

    // I2C address: normalize to 0x hex on blur; accepts decimal or hex input
    var i2cInput = document.getElementById('oled_i2c_address');
    if (i2cInput) {
        i2cInput.addEventListener('blur', function() {
            var val = this.value.trim();
            var num;
            if (/^0x[\da-fA-F]+$/i.test(val)) {
                num = parseInt(val, 16);
            } else if (/^\d+$/.test(val)) {
                num = parseInt(val, 10);
            } else {
                return;
            }
            if (!isNaN(num) && num >= 0 && num <= 127) {
                this.value = '0x' + num.toString(16).padStart(2, '0');
            }
        });
    }
})();

// ── GPS Live Panel ────────────────────────────────────────────────────
var _gpsPollTimer  = null;
var _gpsRendered   = false;   // true once the panel shell has been inserted
var _gpsHandlersAttached = false; // event-delegation wiring done once
var METERS_TO_FEET = 3.28084;
var KNOTS_TO_MPH   = 1.15078;
// Approx UERE for consumer GPS (5 m); used to translate HDOP into a rough
// horizontal-accuracy estimate. Real receivers vary, so we label it "~".
var GPS_UERE_M = 5.0;
// Recognised NMEA sentence types — used for the per-type filter chips and
// the rate display in the diagnostics section.
var NMEA_TYPES = ['GGA', 'RMC', 'GSV', 'GSA', 'GLL', 'VTG'];

/* Mutable client-side state preserved across polls. */
var _gpsState = {
    nmeaFilter: { types: null, text: '', paused: false, pauseSnapshot: null },
    posHistory: [],          // {lat, lon, t} — last ~30 fixes for stability calc
    posHistoryMax: 30,
    lastCounts: null,        // sentence_counts from previous poll
    lastCountsAt: 0,         // performance.now() at lastCounts time
    rates: {}                // smoothed Hz per sentence type
};

function startGpsPolling() {
    stopGpsPolling();
    refreshGpsStatus();
    _gpsPollTimer = setInterval(refreshGpsStatus, 2000);
    var badge = document.getElementById('gps-live-badge');
    if (badge) badge.classList.add('is-visible');
}

function stopGpsPolling() {
    if (_gpsPollTimer) { clearInterval(_gpsPollTimer); _gpsPollTimer = null; }
    var badge = document.getElementById('gps-live-badge');
    if (badge) badge.classList.remove('is-visible');
}

/* One-time panel shell — all dynamic content sits behind stable element IDs.
   The NMEA filter controls live in the shell (not inside a patched slot) so
   their DOM state — chip on/off, search text, pause toggle — survives the
   2-second poll cycle. Only `gps-nmea-rows` is replaced each refresh. */
function _buildGpsPanelShell() {
    var chips = NMEA_TYPES.map(function (t) {
        return '<button type="button" class="gps-nmea-chip on" data-nmea-filter="' + t + '">' + t + '</button>';
    }).join('');
    return '<div class="gps-live-panel" id="gps-panel-root">'
        + '<div class="gps-live-header">'
        +   '<span id="gps-hdr-badge"></span>'
        +   '<span id="gps-hdr-vis-used" style="color:var(--text-muted)"></span>'
        +   '<span id="gps-hdr-port"     style="color:var(--text-muted)"></span>'
        +   '<span id="gps-hdr-constellations" style="display:inline-flex;flex-wrap:wrap;gap:4px"></span>'
        +   '<span class="ms-auto" style="display:inline-flex;align-items:center;gap:4px">'
        +     '<span id="gps-hdr-pps"></span>'
        +     '<span id="gps-hdr-tsync"></span>'
        +   '</span>'
        + '</div>'
        + '<div id="gps-error-hint"></div>'
        + '<div class="gps-live-body">'
        +   '<div class="gps-sky-col">'
        +     '<canvas id="gps-sky-canvas" width="240" height="240" style="display:block"></canvas>'
        +     '<div id="gps-sky-overlay"></div>'
        +   '</div>'
        +   '<div class="gps-sat-col"><div id="gps-sat-table-wrap"></div></div>'
        + '</div>'
        + '<div id="gps-nmea-wrap">'
        +   '<div class="gps-nmea-controls">'
        +     '<span class="gps-nmea-label">Recent NMEA</span>'
        +     chips
        +     '<input type="text" class="gps-nmea-search" id="gps-nmea-search" placeholder="filter…" />'
        +     '<button type="button" class="gps-nmea-pause" id="gps-nmea-pause">&#10074;&#10074; Pause</button>'
        +   '</div>'
        +   '<div class="gps-nmea-rows" id="gps-nmea-rows"></div>'
        + '</div>'
        + '<div class="gps-fix-footer" id="gps-footer"></div>'
        + '<details class="gps-diag" id="gps-diag">'
        +   '<summary>Diagnostics</summary>'
        +   '<div class="gps-diag-body" id="gps-diag-body"></div>'
        + '</details>'
        + '</div>';
}

/* One-time event-delegation hookup for the NMEA filter UI and the diagnostics
   copy buttons. The targets are recreated on every poll, so we listen on the
   stable shell root and dispatch by data-attribute. */
function _attachGpsHandlers() {
    if (_gpsHandlersAttached) return;
    var root = document.getElementById('gps-panel-root');
    if (!root) return;

    // Initialise filter set with all known types enabled
    if (_gpsState.nmeaFilter.types === null) {
        _gpsState.nmeaFilter.types = {};
        NMEA_TYPES.forEach(function (t) { _gpsState.nmeaFilter.types[t] = true; });
    }

    root.addEventListener('click', function (ev) {
        var chip = ev.target.closest('[data-nmea-filter]');
        if (chip) {
            var t = chip.getAttribute('data-nmea-filter');
            _gpsState.nmeaFilter.types[t] = !_gpsState.nmeaFilter.types[t];
            chip.classList.toggle('on', !!_gpsState.nmeaFilter.types[t]);
            _renderNmeaRows();
            return;
        }
        if (ev.target.id === 'gps-nmea-pause') {
            var f = _gpsState.nmeaFilter;
            f.paused = !f.paused;
            ev.target.classList.toggle('paused', f.paused);
            ev.target.innerHTML = f.paused ? '▶ Resume' : '❚❚ Pause';
            // Snapshot the buffer at pause time so the displayed rows freeze
            f.pauseSnapshot = f.paused ? (_gpsState.lastSentences || []).slice() : null;
            _renderNmeaRows();
            return;
        }
        var copy = ev.target.closest('[data-copy]');
        if (copy) {
            var text = copy.getAttribute('data-copy');
            _copyToClipboard(text, copy);
            return;
        }
    });

    var search = document.getElementById('gps-nmea-search');
    if (search) {
        search.addEventListener('input', function () {
            _gpsState.nmeaFilter.text = this.value || '';
            _renderNmeaRows();
        });
    }
    _gpsHandlersAttached = true;
}

function _copyToClipboard(text, btn) {
    var done = function () {
        if (!btn) return;
        var prev = btn.textContent;
        btn.classList.add('copied');
        btn.textContent = 'Copied!';
        setTimeout(function () {
            btn.classList.remove('copied');
            btn.textContent = prev;
        }, 1100);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {});
        return;
    }
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) {}
    document.body.removeChild(ta);
}

/* Patch a single element's innerHTML without touching any other element. */
function _gpsSet(id, html) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

/* Simple HTML escaper for raw NMEA strings */
function gpsEscapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/* Attribute-value escaper — also escapes the double-quote that breaks
   `data-copy="..."` when the payload is a DMS string like 41° 0' 38.26" N. */
function gpsEscapeAttr(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/* SNR / constellation helpers — pulled from the shared palette in
   static/js/gps_constellation_palette.js (loaded above) so all three
   GPS panels stay colour-consistent.  We keep local function names
   (snrClass / constellationInfo / SNR_COLORS) so the rest of this
   file doesn't need to change. */
var _GPS_PALETTE = (typeof window !== 'undefined' && window.EAS_GPS_PALETTE) || null;
function snrClass(snr) {
    return 'snr-' + (_GPS_PALETTE ? _GPS_PALETTE.snrBucket(snr) : 's0');
}
var SNR_COLORS = (function () {
    var src = _GPS_PALETTE ? _GPS_PALETTE.SNR_COLORS : {};
    var out = {};
    Object.keys(src).forEach(function (k) { out['snr-' + k] = src[k]; });
    return out;
})();
function snrHex(snr) {
    return _GPS_PALETTE ? _GPS_PALETTE.snrHex(snr) : '#484f58';
}
var CONSTELLATION_INFO = _GPS_PALETTE ? _GPS_PALETTE.CONSTELLATION_INFO : {};
function constellationInfo(code) {
    return _GPS_PALETTE ? _GPS_PALETTE.constInfo(code)
                        : { color: '#8b949e', label: code || 'Unknown' };
}
function snrAlpha(snr) {
    if (!_GPS_PALETTE) {
        if (snr === null || snr === undefined) return 0.55;
        return Math.max(0.45, Math.min(0.95, 0.4 + snr / 60));
    }
    return _GPS_PALETTE.snrAlpha(snr);
}

/* Read a CSS custom property from the document root */
function _getThemeColor(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || null;
}

/* Draw the polar sky plot onto a <canvas> element */
function drawSkyPlot(canvas, satsInView, activePrns) {
    var ctx = canvas.getContext('2d');
    var W = canvas.width, H = canvas.height;
    var cx = W / 2, cy = H / 2;
    var MAX_R = Math.min(W, H) / 2 - 16;   // leave room for N/S/E/W labels

    // Read theme colors at paint time so we always match the active theme
    var themeBg      = _getThemeColor('--bg-color')       || '#0d1117';
    var themeBorder  = _getThemeColor('--border-color')   || '#1c2128';
    var themeMuted   = _getThemeColor('--text-muted')     || '#2d3748';
    var themeLabel   = _getThemeColor('--text-secondary') || '#4a6080';

    ctx.clearRect(0, 0, W, H);

    // Clip everything inside the horizon circle
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, MAX_R, 0, Math.PI * 2);
    ctx.clip();

    // Background fill
    ctx.fillStyle = themeBg;
    ctx.fill();

    // Elevation rings: horizon (0°), 30°, 60°
    [0, 30, 60].forEach(function (el) {
        var r = MAX_R * (90 - el) / 90;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.strokeStyle = themeBorder;
        ctx.lineWidth = 1;
        ctx.stroke();
    });

    // Crosshairs
    ctx.strokeStyle = themeBorder;
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(cx, cy - MAX_R); ctx.lineTo(cx, cy + MAX_R);
    ctx.moveTo(cx - MAX_R, cy); ctx.lineTo(cx + MAX_R, cy);
    ctx.stroke();

    // Elevation labels inside the plot
    ctx.fillStyle = themeMuted;
    ctx.font = '8px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('30°', cx + 2, cy - MAX_R * 60 / 90);
    ctx.fillText('60°', cx + 2, cy - MAX_R * 30 / 90);

    // Zenith dot
    ctx.beginPath();
    ctx.arc(cx, cy, 2, 0, Math.PI * 2);
    ctx.fillStyle = themeMuted;
    ctx.fill();

    // Satellites
    (satsInView || []).forEach(function (sat) {
        if (sat.elevation === null || sat.azimuth === null) return;
        var r = MAX_R * (90 - Math.max(0, sat.elevation)) / 90;
        var azRad = sat.azimuth * Math.PI / 180;
        var x = cx + r * Math.sin(azRad);
        var y = cy - r * Math.cos(azRad);
        var isUsed = activePrns.indexOf(sat.prn) !== -1;
        var color = constellationInfo(sat.constellation).color;

        // Glow for used-in-fix sats
        if (isUsed && sat.snr !== null) {
            ctx.beginPath();
            ctx.arc(x, y, 12, 0, Math.PI * 2);
            ctx.fillStyle = color + '28';
            ctx.fill();
        }

        // Satellite circle — colour by constellation, alpha by SNR
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = snrAlpha(sat.snr);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = isUsed ? '#ffffff' : themeBorder;
        ctx.lineWidth = isUsed ? 1.5 : 0.8;
        ctx.stroke();

        // PRN label
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 7px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(sat.prn.toString(), x, y);
    });

    ctx.restore();

    // Cardinal labels (outside the clip)
    ctx.fillStyle = themeLabel;
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('N', cx, cy - MAX_R - 9);
    ctx.fillText('S', cx, cy + MAX_R + 9);
    ctx.textAlign = 'left';
    ctx.fillText('E', cx + MAX_R + 5, cy);
    ctx.textAlign = 'right';
    ctx.fillText('W', cx - MAX_R - 5, cy);
}

/* Build the satellite table HTML (cgps-style) */
function buildSatTable(satsInView, activePrns) {
    // Merge active PRNs that have no GSV entry so used satellites always appear
    var gsv_prns = (satsInView || []).map(function (s) { return s.prn; });
    var extraActive = (activePrns || []).filter(function (p) { return gsv_prns.indexOf(p) === -1; });
    var allSats = (satsInView || []).slice();
    extraActive.forEach(function (prn) {
        allSats.push({ prn: prn, elevation: null, azimuth: null, snr: null });
    });

    if (allSats.length === 0) {
        return '<div class="text-muted" style="padding:16px 4px;font-size:0.75rem">No satellite data yet&hellip;</div>';
    }
    // Check if we have any sky-position data at all
    var hasPos = allSats.some(function(s) { return s.elevation !== null || s.azimuth !== null; });
    var almanacNote = (!hasPos && allSats.length > 0)
        ? '<div style="padding:4px 4px 8px;font-size:0.7rem;color:var(--warning-color)">'
          + '<i class="fas fa-satellite-dish fa-fw"></i> '
          + 'Sky positions pending &mdash; receiver is downloading almanac&sol;ephemeris data.'
          + '</div>'
        : '';
    var sorted = allSats.slice().sort(function (a, b) {
        var sa = a.snr !== null ? a.snr : -1;
        var sb = b.snr !== null ? b.snr : -1;
        return sb - sa;
    });

    var rows = sorted.map(function (sat) {
        var used = activePrns.indexOf(sat.prn) !== -1;
        var cls = used ? 'sat-used' : 'sat-unused';
        var snr = sat.snr;
        var barW = snr !== null ? Math.min(100, Math.round(snr / 50 * 100)) : 0;
        var barColor = snrHex(snr);
        var info = constellationInfo(sat.constellation);
        var constDot = '<span title="' + info.label + '" style="display:inline-block;width:7px;height:7px;border-radius:50%;background:' + info.color + ';margin-right:5px;vertical-align:middle"></span>';
        var usedMark = used
            ? '<span style="color:#3fb950">&#10003;</span>'
            : '<span style="color:var(--border-color)">&#183;</span>';
        return '<tr class="' + cls + '">'
            + '<td style="text-align:right;padding-right:8px;white-space:nowrap">' + constDot + sat.prn + '</td>'
            + '<td style="text-align:right;padding-right:8px">' + (sat.elevation !== null ? sat.elevation : '&mdash;') + '</td>'
            + '<td style="text-align:right;padding-right:10px">' + (sat.azimuth !== null ? sat.azimuth : '&mdash;') + '</td>'
            + '<td><span class="gps-snr-track"><span class="gps-snr-fill" style="width:' + barW + '%;background:' + barColor + '"></span></span></td>'
            + '<td style="padding-left:5px;text-align:right">' + (snr !== null ? snr : '&mdash;') + '</td>'
            + '<td style="padding-left:6px;text-align:center">' + usedMark + '</td>'
            + '</tr>';
    }).join('');

    // Constellation legend — only shows the talkers actually present in this view
    var presentConsts = {};
    allSats.forEach(function (s) { if (s.constellation) presentConsts[s.constellation] = true; });
    var constLegend = Object.keys(presentConsts).sort().map(function (code) {
        var info = constellationInfo(code);
        return '<span><span class="snr-dot" style="background:' + info.color + '"></span>' + info.label + '</span>';
    }).join('');
    var constLegendHtml = constLegend
        ? '<div class="snr-legend" style="margin-top:2px">' + constLegend + '</div>'
        : '';

    return almanacNote
        + '<div class="table-responsive">'
        + '<table class="gps-sat-table">'
        + '<thead><tr>'
        + '<th style="text-align:right">Sv</th>'
        + '<th style="text-align:right">El&deg;</th>'
        + '<th style="text-align:right">Az&deg;</th>'
        + '<th colspan="2">C/N&#x2080; (dBHz)</th>'
        + '<th style="text-align:center">Fix</th>'
        + '</tr></thead>'
        + '<tbody>' + rows + '</tbody>'
        + '</table>'
        + '</div>'
        + '<div class="snr-legend">'
        + '<span><span class="snr-dot snr-s5"></span>&ge;45</span>'
        + '<span><span class="snr-dot snr-s4"></span>35&ndash;44</span>'
        + '<span><span class="snr-dot snr-s3"></span>25&ndash;34</span>'
        + '<span><span class="snr-dot snr-s2"></span>15&ndash;24</span>'
        + '<span><span class="snr-dot snr-s1"></span>&lt;15</span>'
        + '<span><span class="snr-dot snr-s0"></span>no sig</span>'
        + '</div>'
        + constLegendHtml;
}

var GPS_NMEA_COLORS = {
    GGA: '#3fb950', RMC: '#58a6ff', GSV: '#bc8cff',
    GSA: '#e3b341', GLL: '#79c0ff', VTG: '#ffa657'
};

/* Render the NMEA rows panel from current state — applies type filter and
   free-text filter. Pause freezes the visible buffer to whatever was present
   when the user paused. */
function _renderNmeaRows() {
    var slot = document.getElementById('gps-nmea-rows');
    if (!slot) return;
    var f = _gpsState.nmeaFilter;
    var sentences = f.paused ? (f.pauseSnapshot || []) : (_gpsState.lastSentences || []);
    if (!sentences.length) {
        slot.innerHTML = '<div class="gps-nmea-empty">No NMEA sentences received yet…</div>';
        return;
    }
    var typeOk = f.types || {};
    var needle = (f.text || '').toLowerCase();
    var rows = [];
    for (var i = sentences.length - 1; i >= 0; i--) {
        var s = sentences[i];
        var m = s.match(/^\$[A-Z]{2}([A-Z]{3})/);
        var t = m ? m[1] : null;
        if (t && Object.prototype.hasOwnProperty.call(typeOk, t) && !typeOk[t]) continue;
        if (needle && s.toLowerCase().indexOf(needle) === -1) continue;
        var color = (t && GPS_NMEA_COLORS[t]) || 'var(--text-muted)';
        rows.push('<div style="color:' + color + ';white-space:pre;line-height:1.4">'
            + gpsEscapeHtml(s) + '</div>');
    }
    if (!rows.length) {
        slot.innerHTML = '<div class="gps-nmea-empty">No sentences match the current filter.</div>';
        return;
    }
    slot.innerHTML = rows.join('');
}

/* Build the per-constellation chips that go in the header. Each chip shows
   the constellation name, total satellites in view for it, and how many of
   those are being used in the current fix. */
function buildConstellationChips(satsInView, activePrns) {
    if (!satsInView || !satsInView.length) return '';
    var groups = {};
    var activeSet = {};
    (activePrns || []).forEach(function (p) { activeSet[p] = true; });
    satsInView.forEach(function (s) {
        var code = s.constellation || 'GN';
        if (!groups[code]) groups[code] = { total: 0, used: 0 };
        groups[code].total += 1;
        if (activeSet[s.prn]) groups[code].used += 1;
    });
    return Object.keys(groups).sort().map(function (code) {
        var info = constellationInfo(code);
        var g = groups[code];
        return '<span class="gps-const-chip" title="' + info.label + ' — ' + g.used + ' used of ' + g.total + ' visible">'
            + '<span class="gps-const-dot" style="background:' + info.color + '"></span>'
            + info.label + ' ' + g.total
            + (g.used ? '<span class="gps-const-used">·' + g.used + '</span>' : '')
            + '</span>';
    }).join('');
}

/* Time-sync indicator. Hidden when use_for_time is off, since otherwise it
   would always read "OFF" and add noise. */
function buildTimeSyncChip(d) {
    if (!d.use_for_time) return '';
    if (d.time_synced) {
        var label = d.ntp_disabled ? 'TIME · GPS' : 'TIME · synced';
        return '<span class="gps-tsync-chip" title="System clock has been set from GPS time">'
            + '<i class="fas fa-clock"></i> ' + label + '</span>';
    }
    return '<span class="gps-tsync-chip tsync-off" title="Waiting for first GPS time sync">'
        + '<i class="far fa-clock"></i> TIME · pending</span>';
}

/* Map fix_quality enum to a short human label appended to the badge.
   Returns empty for the default/unknown case to avoid clutter. */
function fixQualityLabel(q) {
    return ({
        gps_fix:    '',
        dgps_fix:   'DGPS',
        pps_fix:    'PPS',
        rtk_fix:    'RTK',
        float_rtk:  'RTK Float',
        estimated:  'Dead-reckon',
        manual:     'Manual',
        simulation: 'Sim'
    }[q] || '');
}

/* Convert track_angle (true course) to an 8-point cardinal indicator. */
function bearingToCardinal(deg) {
    if (deg === null || deg === undefined || isNaN(deg)) return '';
    var dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    return dirs[Math.round(((deg % 360) / 45)) % 8];
}

/* Decimal degrees → "DD° MM' SS.SS\" H" with a hemisphere letter. */
function toDMS(deg, posChar, negChar) {
    if (deg === null || deg === undefined || isNaN(deg)) return '—';
    var hemi = deg >= 0 ? posChar : negChar;
    var abs = Math.abs(deg);
    var d = Math.floor(abs);
    var mFloat = (abs - d) * 60;
    var m = Math.floor(mFloat);
    var s = (mFloat - m) * 60;
    return d + '° ' + m + "' " + s.toFixed(2) + '" ' + hemi;
}

/* 6-character Maidenhead grid (e.g. EN80la) — handy for ham operators. */
function toMaidenhead(lat, lon) {
    if (lat === null || lon === null) return '—';
    var adjLon = lon + 180;
    var adjLat = lat + 90;
    var fLon = Math.floor(adjLon / 20);
    var fLat = Math.floor(adjLat / 10);
    var sLon = Math.floor((adjLon % 20) / 2);
    var sLat = Math.floor(adjLat % 10);
    var subLon = Math.floor((adjLon - 20 * fLon - 2 * sLon) * 12);
    var subLat = Math.floor((adjLat - 10 * fLat -     sLat) * 24);
    return String.fromCharCode(65 + fLon) + String.fromCharCode(65 + fLat)
        + sLon + sLat
        + String.fromCharCode(97 + subLon) + String.fromCharCode(97 + subLat);
}

/* RMS scatter of recent positions, in metres — a quick smoke test for
   "is this fix actually stable, or is it dancing?" */
function positionStability(history) {
    if (!history || history.length < 5) return null;
    var n = history.length;
    var meanLat = 0, meanLon = 0;
    for (var i = 0; i < n; i++) { meanLat += history[i].lat; meanLon += history[i].lon; }
    meanLat /= n; meanLon /= n;
    var vLat = 0, vLon = 0;
    for (var j = 0; j < n; j++) {
        vLat += Math.pow(history[j].lat - meanLat, 2);
        vLon += Math.pow(history[j].lon - meanLon, 2);
    }
    vLat /= n; vLon /= n;
    var sdLatM = Math.sqrt(vLat) * 111320;
    var sdLonM = Math.sqrt(vLon) * 111320 * Math.cos(meanLat * Math.PI / 180);
    return {
        samples: n,
        rmsM: Math.sqrt(sdLatM * sdLatM + sdLonM * sdLonM),
        spanS: history[n - 1].t - history[0].t
    };
}

/* Update _gpsState.rates from the latest sentence_counts dict using a simple
   delta over wall-clock time. Resets cleanly on counter rollover (manager
   restart) by clamping negative deltas to 0. */
function updateSentenceRates(counts) {
    var nowMs = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
    if (_gpsState.lastCounts && _gpsState.lastCountsAt) {
        var dt = (nowMs - _gpsState.lastCountsAt) / 1000;
        if (dt > 0.1) {
            var keys = {};
            Object.keys(counts || {}).forEach(function (k) { keys[k] = true; });
            Object.keys(_gpsState.lastCounts).forEach(function (k) { keys[k] = true; });
            Object.keys(keys).forEach(function (k) {
                var cur = (counts && counts[k]) || 0;
                var prev = _gpsState.lastCounts[k] || 0;
                var delta = Math.max(0, cur - prev);
                _gpsState.rates[k] = delta / dt;
            });
        }
    }
    _gpsState.lastCounts = Object.assign({}, counts || {});
    _gpsState.lastCountsAt = nowMs;
}

/* Build the diagnostics disclosure body — every secondary metric lives here
   so the main panel stays focused on at-a-glance fix quality. */
function buildDiagnostics(d, sats, activePrns, stability) {
    function row(label, val) {
        return '<div class="gps-diag-row">'
            + '<span class="gps-diag-label">' + label + '</span>'
            + '<span class="gps-diag-val">' + val + '</span></div>';
    }
    var rows = [];

    // SNR statistics across used satellites (falls back to all in view)
    var snrs = (sats || [])
        .filter(function (s) { return s.snr !== null && s.snr !== undefined; })
        .map(function (s) { return s.snr; });
    var usedSnrs = (sats || [])
        .filter(function (s) { return activePrns.indexOf(s.prn) !== -1
            && s.snr !== null && s.snr !== undefined; })
        .map(function (s) { return s.snr; });
    var snrSet = usedSnrs.length ? usedSnrs : snrs;
    if (snrSet.length) {
        var avg = snrSet.reduce(function (a, b) { return a + b; }, 0) / snrSet.length;
        var max = Math.max.apply(null, snrSet);
        var min = Math.min.apply(null, snrSet);
        rows.push(row('Avg C/N₀',
            avg.toFixed(1) + ' dBHz <span style="color:var(--text-muted)">(min ' + min + ', max ' + max + ')</span>'));
    }

    // Geoid separation (height of MSL above WGS-84 ellipsoid)
    if (d.geoid_separation_m !== null && d.geoid_separation_m !== undefined) {
        rows.push(row('Geoid separation', d.geoid_separation_m.toFixed(1) + ' m'));
        if (d.altitude_m !== null && d.altitude_m !== undefined) {
            rows.push(row('Altitude (WGS-84)',
                (d.altitude_m + d.geoid_separation_m).toFixed(1) + ' m'));
        }
    }

    // Magnetic variation (RMC)
    if (d.magnetic_variation !== null && d.magnetic_variation !== undefined) {
        rows.push(row('Magnetic variation',
            d.magnetic_variation.toFixed(1) + '° ' + (d.magnetic_variation_dir || '')));
    }

    // DGPS correction info
    if (d.dgps_age_s !== null && d.dgps_age_s !== undefined) {
        rows.push(row('DGPS age', d.dgps_age_s.toFixed(1) + ' s'));
    }
    if (d.dgps_station_id) {
        rows.push(row('DGPS station', gpsEscapeHtml(d.dgps_station_id)));
    }

    // Position stability over recent history
    if (stability) {
        rows.push(row('Position stability',
            '±' + stability.rmsM.toFixed(2) + ' m RMS '
            + '<span style="color:var(--text-muted)">(' + stability.samples + ' samples / '
            + Math.round(stability.spanS) + 's)</span>'));
    }

    // Parser health
    if (d.sentence_errors !== null && d.sentence_errors !== undefined) {
        var errColor = d.sentence_errors > 0 ? 'var(--warning-color)' : 'var(--text-muted)';
        rows.push(row('Parse errors',
            '<span style="color:' + errColor + '">' + d.sentence_errors + '</span>'));
    }

    // PPS pulse counter
    if (d.pps_pulse_count) {
        rows.push(row('PPS pulses', d.pps_pulse_count.toLocaleString()));
    }

    var html = rows.join('');

    // Sentence rates row spans full width
    var rateChips = NMEA_TYPES
        .filter(function (t) { return _gpsState.lastCounts && _gpsState.lastCounts[t]; })
        .map(function (t) {
            var hz = _gpsState.rates[t];
            var hzText = (hz !== undefined) ? hz.toFixed(1) + 'Hz' : '—';
            return '<span class="gps-diag-rate-chip">' + t + ' <strong>' + hzText + '</strong></span>';
        }).join('');
    if (rateChips) {
        html += '<div class="gps-diag-rates">'
            + '<span class="gps-diag-label" style="font-size:0.68rem">Sentence rates &nbsp;</span>'
            + rateChips + '</div>';
    }

    // Copy buttons — only when a position is available
    if (d.has_fix && d.latitude !== null && d.longitude !== null) {
        var dec = d.latitude.toFixed(6) + ', ' + d.longitude.toFixed(6);
        var dms = toDMS(d.latitude, 'N', 'S') + ', ' + toDMS(d.longitude, 'E', 'W');
        var grid = toMaidenhead(d.latitude, d.longitude);
        html += '<div class="gps-diag-copy">'
            + '<button type="button" class="gps-diag-copy-btn" data-copy="' + gpsEscapeAttr(dec) + '">'
              + '<i class="far fa-copy fa-fw"></i> Decimal</button>'
            + '<button type="button" class="gps-diag-copy-btn" data-copy="' + gpsEscapeAttr(dms) + '">'
              + '<i class="far fa-copy fa-fw"></i> DMS</button>'
            + '<button type="button" class="gps-diag-copy-btn" data-copy="' + gpsEscapeAttr(grid) + '">'
              + '<i class="far fa-copy fa-fw"></i> ' + gpsEscapeHtml(grid) + '</button>'
            + '</div>';
    }

    if (!html) {
        html = '<div class="gps-diag-row" style="grid-column:1/-1">'
            + '<span class="gps-diag-label">Awaiting data…</span></div>';
    }
    return html;
}

/* Build the PPS blinkenlite badge */
function buildPpsHtml(d) {
    var age = d.pps_pulse_age_s;
    var pin = d.pps_gpio_pin !== undefined ? d.pps_gpio_pin : '?';
    var active = age !== null && age < 2.5;
    var ever   = age !== null && age >= 2.5;
    var cls = active ? 'pps-active' : (ever ? 'pps-lost' : 'pps-inactive');
    var txt = active
        ? ('PPS \u00b7 ' + age.toFixed(1) + 's')
        : 'PPS';
    var tip = active
        ? ('PPS active on GPIO ' + pin + ' \u2014 last pulse ' + age.toFixed(1) + 's ago')
        : (ever ? ('PPS lost on GPIO ' + pin + ' \u2014 last pulse ' + age.toFixed(1) + 's ago')
               : ('No PPS signal detected on GPIO ' + pin));
    return '<span class="pps-led ' + cls + '" title="' + tip + '">'
        + '<span class="pps-dot"></span>' + txt + '</span>';
}

/* Status badge \u2014 when we have a fix, prefer the GSA-derived 2D/3D label and
   append the GGA fix-quality detail (DGPS / RTK / etc) when it's something
   more interesting than a plain GPS solution. */
function buildStatusBadge(d) {
    var errorStatuses = ['port_not_found','port_open_failed','pyserial_missing','pynmea2_missing'];
    var labels = {
        'fix':'3D Fix','acquiring':'Acquiring\u2026','no_fix':'No Fix',
        'port_not_found':'Port Not Found','port_open_failed':'Port Error',
        'pyserial_missing':'pyserial Missing','pynmea2_missing':'pynmea2 Missing',
        'not_started':'Not Started','disabled':'Disabled','stopped':'Stopped','reading':'Reading\u2026'
    };
    var lbl = labels[d.status] || d.status || 'Unknown';
    if (d.has_fix) {
        if (d.fix_mode === 2) lbl = '2D Fix';
        else if (d.fix_mode === 3) lbl = '3D Fix';
        var detail = fixQualityLabel(d.fix_quality);
        if (detail) lbl += ' \u00b7 ' + detail;
        return '<span style="color:#3fb950;font-weight:bold">[' + lbl + ']</span>';
    }
    if (d.status === 'acquiring' || d.status === 'reading')
        return '<span style="color:var(--warning-color);font-weight:bold">[' + lbl + ']</span>';
    if (errorStatuses.indexOf(d.status) !== -1)
        return '<span style="color:var(--danger-color);font-weight:bold">[' + lbl + ']</span>';
    return '<span style="color:var(--text-muted)">[' + lbl + ']</span>';
}

/* Error hint banners */
function buildErrorHint(d) {
    var hints = {
        'port_not_found':
            'Serial port <code>' + (d.serial_port||'/dev/serial0') + '</code> not found. '
            + 'Check that the GPS HAT is connected and enable UART via <code>raspi-config</code>.',
        'pyserial_missing':
            '<code>pyserial</code> not installed &mdash; run: <code>pip install pyserial</code>',
        'pynmea2_missing':
            '<code>pynmea2</code> not installed &mdash; run: <code>pip install pynmea2</code>',
        'port_open_failed':
            'Could not open serial port. Check permissions and that the port is not in use by another process.'
    };
    var msg = hints[d.status];
    if (msg) {
        return '<div style="margin:0;padding:6px 12px;background:rgba(248,81,73,0.12);color:var(--danger-color);border-top:1px solid rgba(248,81,73,0.3);font-size:0.75rem">'
            + '<i class="fas fa-exclamation-triangle me-1"></i>' + msg + '</div>';
    }
    // Acquiring hint: visible satellites but no position fix yet
    if (!d.has_fix && d.status === 'acquiring') {
        var satsVisible = (d.satellites_in_view || []).length;
        var haveSkyPos  = (d.satellites_in_view || []).some(function(s) { return s.elevation !== null && s.azimuth !== null; });
        var detail = haveSkyPos
            ? 'Waiting for enough satellites to compute a 3D fix.'
            : 'Downloading satellite almanac &amp; ephemeris data \u2014 this provides orbital positions needed to compute a fix. '
              + 'A cold start typically takes 1&ndash;3 minutes; warm start 30&ndash;60 seconds.';
        return '<div style="margin:0;padding:6px 12px;background:rgba(210,153,34,0.12);color:var(--warning-color);border-top:1px solid rgba(210,153,34,0.3);font-size:0.75rem">'
            + '<i class="fas fa-satellite-dish me-1"></i>'
            + '<strong>' + satsVisible + ' satellite' + (satsVisible !== 1 ? 's' : '') + ' in view &mdash;</strong> ' + detail
            + '</div>';
    }
    return '';
}

function refreshGpsStatus() {
    var container = document.getElementById('gps-status-card');
    if (!container) return;
    // Don't poll when the tab is hidden — the GPS card isn't visible and the
    // /api/hardware/gps/status request still runs a handler on the server.
    if (typeof document !== 'undefined' && document.hidden) return;
    fetch('/api/hardware/gps/status')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            var satsInView      = d.satellites_in_view    || [];
            var activePrns      = d.active_satellite_prns || [];
            var recentSentences = d.recent_sentences      || [];
            var usedCount       = activePrns.length;
            // Fallback: when the receiver doesn't emit GSA at all (some chips
            // need PMTK314 to enable it) but GGA reports a fix with N sats,
            // surface that count instead of misleadingly showing "0 used".
            if (usedCount === 0 && d.has_fix && d.satellites) {
                usedCount = d.satellites;
            }
            var viewCount       = satsInView.length || (d.satellites != null ? d.satellites : 0);
            var plottableSats   = satsInView.filter(function(s) { return s.elevation !== null && s.azimuth !== null; });
            var pendingAlmanac  = satsInView.length > 0 && plottableSats.length === 0;

            // Build the panel shell only once — never tear it down again.
            if (!_gpsRendered) {
                container.innerHTML = _buildGpsPanelShell();
                _gpsRendered = true;
                _attachGpsHandlers();
            }

            // ── Track rolling state ─────────────────────────────────
            _gpsState.lastSentences = recentSentences;
            updateSentenceRates(d.sentence_counts || {});

            if (d.has_fix && d.latitude !== null && d.longitude !== null) {
                var nowS = Date.now() / 1000;
                _gpsState.posHistory.push({ lat: d.latitude, lon: d.longitude, t: nowS });
                if (_gpsState.posHistory.length > _gpsState.posHistoryMax) {
                    _gpsState.posHistory.shift();
                }
            } else if (!d.has_fix) {
                _gpsState.posHistory = [];
            }
            var stability = positionStability(_gpsState.posHistory);

            // ── Patch each element in-place ──────────────────────────
            _gpsSet('gps-hdr-badge',    buildStatusBadge(d));
            _gpsSet('gps-hdr-vis-used', viewCount + ' visible &bull; ' + usedCount + ' used');
            _gpsSet('gps-hdr-port',
                '<code style="color:var(--accent-color)">' + (d.serial_port||'—') + '</code>'
                + ' &bull; ' + (d.baudrate||'9600') + 'bd');
            _gpsSet('gps-hdr-constellations', buildConstellationChips(satsInView, activePrns));
            _gpsSet('gps-hdr-pps',      buildPpsHtml(d));
            _gpsSet('gps-hdr-tsync',    buildTimeSyncChip(d));
            _gpsSet('gps-error-hint',   buildErrorHint(d));
            _gpsSet('gps-sky-overlay',
                pendingAlmanac
                    ? '<div style="margin-top:4px;font-size:0.7rem;color:var(--warning-color);text-align:center">'
                      + '<i class="fas fa-satellite-dish fa-fw"></i> Downloading sky positions&hellip;</div>'
                    : '');
            _gpsSet('gps-sat-table-wrap', buildSatTable(satsInView, activePrns));
            _renderNmeaRows();

            // ── Footer ───────────────────────────────────────────────
            var footerHtml;
            if (d.has_fix) {
                var lat  = d.latitude  != null ? d.latitude.toFixed(6)  + '&deg;' : '&mdash;';
                var lon  = d.longitude != null ? d.longitude.toFixed(6) + '&deg;' : '&mdash;';
                var alt  = d.altitude_m != null ? (d.altitude_m * METERS_TO_FEET).toFixed(0) + ' ft' : '&mdash;';
                var hdop = d.hdop != null ? d.hdop : '&mdash;';
                var pdop = d.pdop != null ? d.pdop : null;
                var vdop = d.vdop != null ? d.vdop : null;
                var utc  = d.gps_utc_time || '&mdash;';
                var spd  = d.speed_knots != null ? (d.speed_knots * KNOTS_TO_MPH).toFixed(1) + ' mph' : null;
                var crs  = d.track_angle != null
                    ? d.track_angle.toFixed(0) + '° ' + bearingToCardinal(d.track_angle)
                    : null;
                var acc  = d.hdop != null
                    ? '~' + (d.hdop * GPS_UERE_M).toFixed(1) + ' m'
                    : null;
                footerHtml =
                    '<span><span class="gps-lbl">Lat&nbsp;</span>' + lat + '</span>'
                    + '<span><span class="gps-lbl">Lon&nbsp;</span>' + lon + '</span>'
                    + '<span><span class="gps-lbl">Alt&nbsp;</span>' + alt + '</span>'
                    + '<span><span class="gps-lbl">HDOP&nbsp;</span>' + hdop + '</span>'
                    + (pdop !== null ? '<span><span class="gps-lbl">PDOP&nbsp;</span>' + pdop + '</span>' : '')
                    + (vdop !== null ? '<span><span class="gps-lbl">VDOP&nbsp;</span>' + vdop + '</span>' : '')
                    + (acc  !== null ? '<span title="Estimated horizontal accuracy = HDOP × ~5 m UERE"><span class="gps-lbl">Accuracy&nbsp;</span>' + acc + '</span>' : '')
                    + (crs  !== null ? '<span><span class="gps-lbl">Course&nbsp;</span>' + crs + '</span>' : '')
                    + (spd ? '<span><span class="gps-lbl">Speed&nbsp;</span>' + spd + '</span>' : '')
                    + '<span><span class="gps-lbl">UTC&nbsp;</span>' + utc + '</span>';
            } else {
                var noFixUtc = d.gps_utc_time
                    ? '<span><span class="gps-lbl">GPS UTC&nbsp;</span><span style="color:var(--accent-color)">' + d.gps_utc_time + '</span></span>'
                    : '';
                var noFixHdop = d.hdop != null
                    ? '<span><span class="gps-lbl">HDOP&nbsp;</span>' + d.hdop + '</span>' : '';
                var noFixPdop = d.pdop != null
                    ? '<span><span class="gps-lbl">PDOP&nbsp;</span>' + d.pdop + '</span>' : '';
                footerHtml =
                    '<span style="color:var(--text-muted)">No position fix yet&hellip;</span>'
                    + noFixUtc + noFixHdop + noFixPdop;
            }
            _gpsSet('gps-footer', footerHtml);

            // ── Diagnostics disclosure ──────────────────────────────
            _gpsSet('gps-diag-body', buildDiagnostics(d, satsInView, activePrns, stability));

            // Redraw sky plot onto the persistent canvas — never recreated.
            var canvas = document.getElementById('gps-sky-canvas');
            if (canvas) drawSkyPlot(canvas, satsInView, activePrns);
        })
        .catch(function (err) {
            // Allow the shell to rebuild after an error clears, and re-arm
            // the delegated click/input handlers since the old root element
            // will be discarded with the error markup.
            _gpsRendered = false;
            _gpsHandlersAttached = false;
            var c = document.getElementById('gps-status-card');
            if (c) c.innerHTML =
                '<span class="text-danger small">'
                + '<i class="fas fa-times-circle me-1"></i>Failed to load GPS status: ' + err
                + '</span>';
        });
}

function showHwAlert(message, type) {
    var banner = document.getElementById('hw-status-banner');
    if (!banner) return;
    banner.className = 'alert alert-' + type + ' alert-dismissible fade show mt-3';
    banner.innerHTML = message
        + ' <button type="button" class="btn-close" onclick="this.parentElement.className=\'d-none\'"></button>';
    banner.classList.remove('d-none');
    banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    if (type === 'success') {
        setTimeout(function() { banner.classList.add('d-none'); }, 6000);
    }
}

function restartServices(btn) {
    if (!confirm('This will restart all EAS Station™ services. Continue?')) return;
    var label = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Restarting\u2026'; }

    fetch(window.HWSettingsConfig.restartUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            showHwAlert('<i class="fas fa-check-circle me-1"></i> Services restarted successfully.', 'success');
        } else {
            showHwAlert('<i class="fas fa-exclamation-triangle me-1"></i> Restart failed: ' + data.error, 'danger');
        }
    })
    .catch(function(err) {
        showHwAlert('<i class="fas fa-exclamation-triangle me-1"></i> Error restarting services: ' + err, 'danger');
    })
    .finally(function() {
        if (btn) { btn.disabled = false; btn.innerHTML = label; }
    });
}

function saveAndRestart(btn) {
    var form = document.getElementById('hardwareForm');
    var formData = new FormData(form);
    var data = {};

    // Explicitly capture checkboxes — unchecked ones are absent from FormData
    form.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
        data[cb.name] = cb.checked;
    });
    // Capture all other fields
    formData.forEach(function(value, key) {
        if (!(key in data)) { data[key] = value; }
    });

    var label = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving\u2026'; }

    fetch(window.HWSettingsConfig.updateUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(function(r) {
        if (!r.ok) return r.json().then(function(d) { throw new Error(d.error || r.statusText); });
        return r.json();
    })
    .then(function(result) {
        if (!result.success) { throw new Error(result.error || 'Save failed'); }
        if (btn) { btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Restarting\u2026'; }
        return fetch(window.HWSettingsConfig.restartUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(function(r) { return r.json(); });
    })
    .then(function(result) {
        if (result.success) {
            showHwAlert('<i class="fas fa-check-circle me-1"></i> Settings saved and services restarted.', 'success');
        } else {
            showHwAlert('<i class="fas fa-check-circle me-1"></i> Settings saved. Restart failed: ' + (result.error || ''), 'warning');
        }
    })
    .catch(function(err) {
        showHwAlert('<i class="fas fa-exclamation-triangle me-1"></i> ' + err, 'danger');
    })
    .finally(function() {
        if (btn) { btn.disabled = false; btn.innerHTML = label; }
    });
}

// Zigbee auto-detect
document.addEventListener('DOMContentLoaded', function() {
    var detectBtn = document.getElementById('zigbee_detect_btn');
    if (!detectBtn) return;
    detectBtn.addEventListener('click', function() {
        var btn = this;
        var resultDiv = document.getElementById('zigbee_detect_result');
        var portInput = document.getElementById('zigbee_port');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Detecting...';
        resultDiv.style.display = 'none';
        fetch('/api/zigbee/detect')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success && data.devices && data.devices.length > 0) {
                    var dev = data.devices[0];
                    portInput.value = dev.port;
                    var badge = dev.confidence === 'high'
                        ? '<span class="badge bg-success">high confidence</span>'
                        : '<span class="badge bg-warning text-dark">medium confidence</span>';
                    resultDiv.innerHTML = '<div class="alert alert-success py-1 mb-0 small">'
                        + '<i class="fas fa-check-circle me-1"></i> Detected: <code>'
                        + dev.port + '</code> &mdash; ' + (dev.description || '') + ' ' + badge
                        + (data.devices.length > 1 ? ' (' + (data.devices.length - 1) + ' other(s) found)' : '')
                        + '</div>';
                    resultDiv.style.display = '';
                } else {
                    resultDiv.innerHTML = '<div class="alert alert-warning py-1 mb-0 small">'
                        + '<i class="fas fa-exclamation-triangle me-1"></i> No Zigbee coordinator detected. '
                        + 'Check device connection.</div>';
                    resultDiv.style.display = '';
                }
            })
            .catch(function(err) {
                resultDiv.innerHTML = '<div class="alert alert-danger py-1 mb-0 small">Detection failed: ' + err + '</div>';
                resultDiv.style.display = '';
            })
            .finally(function() {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-search"></i> Detect';
            });
    });
});

/* ── GPS HAT diagnostic panel ────────────────────────────────────────
   Populates the "GPS HAT Setup Status" card by polling
   /admin/hardware/gps-hat/diagnostics. When the privileged helper is
   reachable, each action is rendered with a "Run" button that POSTs
   to the corresponding /admin/hardware/gps-hat/* endpoint and shows
   the streamed (collected) helper output in a modal. Otherwise the
   action stays in copy-paste mode.
   ──────────────────────────────────────────────────────────────────── */
(function () {
    let _helperAvailable = false;
    let _activeAction = null;     // currently displayed in the modal
    let _runInFlight = false;
    let _bsModalRef = null;       // bootstrap.Modal instance (lazy)
    function getModal() {
        if (_bsModalRef) return _bsModalRef;
        const el = document.getElementById('gps-hat-action-modal');
        if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
        _bsModalRef = new window.bootstrap.Modal(el);
        return _bsModalRef;
    }

    var BADGE_CLASS = {
        ok:      'bg-success',
        info:    'bg-info text-dark',
        warning: 'bg-warning text-dark',
        error:   'bg-danger',
    };
    var BADGE_TEXT = {
        ok:      'All good',
        info:    'Suggestions',
        warning: 'Needs attention',
        error:   'Action required',
    };
    var SEVERITY_CLASS = {
        info:    'alert-info',
        warning: 'alert-warning',
        error:   'alert-danger',
    };
    var SEVERITY_ICON = {
        info:    'fa-circle-info',
        warning: 'fa-triangle-exclamation',
        error:   'fa-circle-xmark',
    };

    function escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderActions(actions) {
        if (!actions || !actions.length) {
            return '<div class="alert alert-success py-2 mb-0 small">'
                + '<i class="fas fa-check-circle me-1"></i> '
                + 'Every prerequisite is in place. The GPS HAT, RTC, PPS, gpsd, and chrony all look healthy.'
                + '</div>';
        }
        return actions.map(function (a, idx) {
            var sev = a.severity || 'info';
            var alertCls = SEVERITY_CLASS[sev] || 'alert-secondary';
            var icon = SEVERITY_ICON[sev] || 'fa-circle-info';
            var preconditions = '';
            if (a.preconditions && a.preconditions.length) {
                preconditions = '<div class="small text-muted mt-1"><em>Before running: '
                    + a.preconditions.map(escapeHtml).join('; ') + '</em></div>';
            }
            var rebootHint = a.requires_reboot
                ? '<div class="small text-muted mt-1"><i class="fas fa-power-off me-1"></i>Requires reboot to take effect.</div>'
                : '';
            // Action button (Tier 2): rendered only when the helper is
            // available AND this action carries a runner spec. Otherwise
            // we fall back to the copy-paste command box.
            var runBtn = '';
            if (_helperAvailable && a.runner && a.runner.endpoint) {
                var btnLabel = a.runner.button_label || 'Run';
                runBtn = '<button type="button" '
                    +     'class="btn btn-sm btn-primary mt-2 gps-hat-run-btn" '
                    +     'data-action-idx="' + idx + '">'
                    +     '<i class="fas fa-play me-1"></i>' + escapeHtml(btnLabel)
                    +   '</button>';
            }
            // Suppress the copy-paste box when a runnable button is present
            // and the helper is up — it's just visual noise once the user
            // can click. When the helper isn't available we still show the
            // command so the user has a path forward.
            var showCommand = !!a.command && !(runBtn && _helperAvailable);
            return '<div class="alert ' + alertCls + ' py-2 mb-2">'
                +   '<div class="d-flex align-items-start">'
                +     '<i class="fas ' + icon + ' me-2 mt-1"></i>'
                +     '<div class="flex-grow-1">'
                +       '<div class="fw-semibold">' + escapeHtml(a.label || a.id) + '</div>'
                +       (a.reason ? '<div class="small">' + escapeHtml(a.reason) + '</div>' : '')
                +       preconditions
                +       (showCommand
                            ? '<pre class="mt-2 mb-0 small bg-dark text-light p-2 rounded" style="white-space:pre-wrap;"><code>'
                                + escapeHtml(a.command) + '</code></pre>'
                            : '')
                +       rebootHint
                +       runBtn
                +     '</div>'
                +   '</div>'
                + '</div>';
        }).join('');
    }

    function renderDetail(report) {
        var rtc = report.rtc || {};
        var pps = report.pps || {};
        var serial = report.serial || {};
        var pkg  = report.packages || {};
        var svc  = report.services || {};
        var gcf  = report.gpsd_config || {};
        var ccf  = report.chrony_config || {};
        var crun = report.chrony_runtime || {};
        var cfg  = report.config_txt || {};

        function row(label, value, ok) {
            var icon = ok === true
                ? '<i class="fas fa-check-circle text-success me-1"></i>'
                : ok === false
                    ? '<i class="fas fa-circle-xmark text-danger me-1"></i>'
                    : '<i class="fas fa-circle text-muted me-1" style="font-size:.5em;vertical-align:middle;"></i>';
            return '<div>' + icon + '<strong>' + escapeHtml(label) + ':</strong> '
                + (value === null || value === undefined ? '<em class="text-muted">unknown</em>' : escapeHtml(value))
                + '</div>';
        }
        var rtcSummary = rtc.kernel_name
            ? rtc.kernel_name + (rtc.chip_label ? ' (' + rtc.chip_label + ')' : '')
            : (rtc.device_present ? 'present' : 'no /dev/rtc0');
        var ppsSummary = pps.gpio_device
            ? pps.gpio_device.name + ' seq=' + (pps.gpio_device.assert_sequence || 0)
            : 'no pps-gpio device';
        // Serial owner detection requires lsof + privileges the web service
        // user doesn't have, so we suppress the "— unknown" suffix when the
        // probe couldn't see it. Showing the resolved device path is enough
        // for the operator to recognise.
        var serialSummary = serial.exists
            ? (serial.resolved || serial.device)
                + (serial.owner && serial.owner !== 'unknown'
                    ? ' — ' + serial.owner
                    : '')
            : 'missing';
        var pkgItems = pkg.items || [];
        var pkgInstalled = pkgItems.filter(function (i) { return i.installed; }).length;
        var pkgMissingRequired = (pkg.missing_required || []).length;
        var pkgSummary = pkgItems.length === 0
            ? 'dpkg-query unavailable'
            : pkgMissingRequired === 0
                ? pkgInstalled + ' / ' + pkgItems.length + ' installed'
                : pkgMissingRequired + ' required missing';
        var pkgList = pkgItems.map(function (i) {
            return (i.installed ? '✅' : '❌') + ' ' + i.name + (i.version ? ' (' + i.version + ')' : '');
        }).join('<br>') || '<em>dpkg-query unavailable</em>';
        var svcItems = svc.items || [];
        var svcAllActive = svcItems.length > 0
            && svcItems.every(function (i) { return i.active === 'active'; });
        var svcSummary = svcItems.length === 0
            ? 'systemctl unavailable'
            : svcAllActive
                ? 'all units active'
                : svcItems.filter(function (i) { return i.active !== 'active'; }).length
                    + ' / ' + svcItems.length + ' inactive';
        var svcList = svcItems.map(function (i) {
            return i.unit + ': ' + i.active + ' / ' + i.enabled;
        }).join('<br>');
        var gpsdSummary = gcf.exists
            ? 'DEVICES=' + (gcf.devices || '?') + '; OPTIONS=' + (gcf.options || '?')
            : '/etc/default/gpsd missing';
        var chronySummary = ccf.exists
            ? ('rtcsync=' + ccf.rtcsync_enabled
                + '; PPS refclock=' + ccf.has_pps_refclock
                + '; SHM refclock=' + ccf.has_shm_refclock
                + '; sources=' + ((ccf.pool_lines || []).length))
            : '/etc/chrony/chrony.conf missing';
        // Stratum is the headline number an operator wants to see — surface
        // it prominently. Also flag any refclocks at Reach=0 so the user
        // sees why they're not yet at stratum 1.
        var chronyParts = [];
        if (crun.tracking_ok) {
            if (crun.stratum != null) chronyParts.push('stratum ' + crun.stratum);
            if (crun.selected_source) chronyParts.push('source=' + crun.selected_source);
            var offsetSrc = (crun.system_time_offset_seconds != null)
                ? crun.system_time_offset_seconds
                : crun.last_offset_seconds;
            if (offsetSrc != null) {
                chronyParts.push('offset=' + (Number(offsetSrc) * 1000).toFixed(3) + 'ms');
            }
            if (crun.leap_status) chronyParts.push('leap=' + crun.leap_status);
            if ((crun.refclocks_unreached || []).length) {
                chronyParts.push('refclocks unreached: ' + crun.refclocks_unreached.join(', '));
            }
        } else {
            chronyParts.push('chronyc unavailable');
        }
        var chronyRunSummary = chronyParts.join('; ');
        var configSummary = cfg.exists
            ? (cfg.path
                + (cfg.i2c_rtc_overlay_line ? ' [' + cfg.i2c_rtc_overlay_line + ']' : '')
                + (cfg.pps_gpio_overlay_line ? ' [' + cfg.pps_gpio_overlay_line + ']' : ''))
            : 'config.txt not found';

        return '<div class="row g-2">'
            + '<div class="col-md-6">'
            +   row('RTC',           rtcSummary,    rtc.device_present)
            +   row('PPS',           ppsSummary,    !!pps.gpio_device)
            +   row('Serial',        serialSummary, serial.exists)
            +   row('config.txt',    configSummary, cfg.exists)
            + '</div>'
            + '<div class="col-md-6">'
            +   row('Packages',      pkgSummary,    pkgMissingRequired === 0 && pkgItems.length > 0)
            +   '<div class="ms-3 small">' + pkgList + '</div>'
            +   row('Services',      svcSummary,    svcItems.length > 0 ? svcAllActive : null)
            +   '<div class="ms-3 small">' + svcList + '</div>'
            +   row('gpsd config',   gpsdSummary,   gcf.exists)
            +   row('chrony config', chronySummary, ccf.exists)
            +   row('chrony status', chronyRunSummary, crun.tracking_ok)
            + '</div>'
            + '</div>';
    }

    let _lastActions = [];

    function refresh(button) {
        var badge   = document.getElementById('gps-hat-status-badge');
        var actions = document.getElementById('gps-hat-actions');
        var detail  = document.getElementById('gps-hat-detail');
        var helperRow = document.getElementById('gps-hat-helper-status');
        if (!badge || !actions || !detail) return;
        badge.className = 'badge bg-secondary ms-2';
        badge.textContent = 'Checking…';
        if (button) {
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking';
        }
        fetch('/admin/hardware/gps-hat/diagnostics', {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.ok) {
                    throw new Error((data && data.error) || 'unknown error');
                }
                var report = data.report;
                _helperAvailable = !!(report.helper && report.helper.available);
                _lastActions = report.actions || [];
                if (helperRow) {
                    helperRow.innerHTML = _helperAvailable
                        ? '<i class="fas fa-plug text-success me-1"></i>'
                            + 'Privileged helper is reachable — actions can be run from this page.'
                        : '<i class="fas fa-plug text-warning me-1"></i>'
                            + 'Privileged helper not reachable — install the '
                            + '<code>eas-station-hwsetup</code> service to enable one-click fixes. '
                            + 'Until then the commands below can be copied into a terminal.';
                }
                var status = report.status || 'info';
                badge.className = 'badge ms-2 ' + (BADGE_CLASS[status] || 'bg-secondary');
                badge.textContent = BADGE_TEXT[status] || status;
                actions.innerHTML = renderActions(_lastActions);
                detail.innerHTML = renderDetail(report);
            })
            .catch(function (err) {
                badge.className = 'badge bg-danger ms-2';
                badge.textContent = 'Probe failed';
                if (helperRow) helperRow.innerHTML = '';
                actions.innerHTML = '<div class="alert alert-danger py-2 mb-0 small">'
                    + '<i class="fas fa-circle-xmark me-1"></i> '
                    + 'Diagnostic probe failed: ' + escapeHtml(String(err))
                    + '</div>';
                detail.innerHTML = '';
            })
            .finally(function () {
                if (button) {
                    button.disabled = false;
                    button.innerHTML = '<i class="fas fa-rotate"></i> Recheck';
                }
            });
    }

    /* ── Modal-driven action runner ──────────────────────────────────
       Click handler for the "Run" buttons rendered in renderActions().
       Opens the shared modal, populates it with the action's summary
       and any extra-param controls, lets the operator confirm, and
       POSTs to action.runner.endpoint. The result body is appended to
       a <pre> in the modal so the operator can see what happened.
       After a successful run we re-poll the diagnostics so the panel
       reflects the new state.
       ──────────────────────────────────────────────────────────────── */
    function appendOutput(text) {
        var pre = document.getElementById('gps-hat-modal-output');
        if (!pre) return;
        pre.textContent += text;
        pre.scrollTop = pre.scrollHeight;
    }

    function setModalStatus(html, cls) {
        var status = document.getElementById('gps-hat-modal-status');
        if (!status) return;
        status.className = 'small mt-2 ' + (cls || 'text-muted');
        status.innerHTML = html;
    }

    function openActionModal(action) {
        var modal = getModal();
        if (!modal) {
            // Bootstrap not loaded; fall back to confirm() + run inline.
            return runActionInline(action);
        }
        _activeAction = action;
        document.getElementById('gps-hat-modal-title').textContent =
            action.runner.button_label || ('Run ' + action.id);
        var summary = document.getElementById('gps-hat-modal-summary');
        if (summary) {
            summary.innerHTML = '<div class="fw-semibold">' + escapeHtml(action.label || action.id) + '</div>'
                + (action.reason ? '<div class="small text-muted">' + escapeHtml(action.reason) + '</div>' : '')
                + (action.runner.confirm
                    ? '<div class="small mt-2 fst-italic">' + escapeHtml(action.runner.confirm) + '</div>'
                    : '')
                + (action.runner.post_action
                    ? '<div class="small mt-2 text-muted">'
                        + '<i class="fas fa-link me-1"></i>'
                        + 'Will also ' + escapeHtml(action.runner.post_action.label || 'run a follow-up') + ' on success.'
                        + '</div>'
                    : '');
        }
        var extraWrap = document.getElementById('gps-hat-modal-extra-params');
        extraWrap.innerHTML = '';
        var extras = action.runner.extra_params || [];
        extras.forEach(function (p) {
            if (p.type === 'boolean') {
                extraWrap.innerHTML += '<div class="form-check small">'
                    + '<input class="form-check-input gps-hat-modal-extra" '
                    +   'type="checkbox" '
                    +   'data-extra-name="' + escapeHtml(p.name) + '" '
                    +   'id="gps-hat-modal-extra-' + escapeHtml(p.name) + '" '
                    +   (p.default ? 'checked' : '') + '>'
                    + '<label class="form-check-label" '
                    +   'for="gps-hat-modal-extra-' + escapeHtml(p.name) + '">'
                    +   escapeHtml(p.label || p.name)
                    + '</label>'
                    + '</div>';
            }
        });
        document.getElementById('gps-hat-modal-output').textContent = '';
        var btnLabel = action.runner.button_label || 'Run';
        setModalStatus(
            'Ready to run. Press <strong>' + escapeHtml(btnLabel)
            + '</strong> below to apply this fix, or Close to cancel.',
            'text-muted'
        );
        var runBtn = document.getElementById('gps-hat-modal-run-btn');
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.innerHTML = '<i class="fas fa-play me-1"></i>' + escapeHtml(btnLabel);
        }
        modal.show();
    }

    function gatherExtraParams() {
        var out = {};
        var inputs = document.querySelectorAll('.gps-hat-modal-extra');
        inputs.forEach(function (input) {
            var name = input.getAttribute('data-extra-name');
            if (!name) return;
            if (input.type === 'checkbox') {
                out[name] = input.checked;
            } else {
                out[name] = input.value;
            }
        });
        return out;
    }

    function runActiveAction() {
        if (_runInFlight || !_activeAction) return;
        var action = _activeAction;
        var runner = action.runner;
        if (!runner || !runner.endpoint) return;
        var body = Object.assign({}, runner.body || {}, gatherExtraParams());
        var runBtn = document.getElementById('gps-hat-modal-run-btn');
        if (runBtn) {
            runBtn.disabled = true;
            runBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Running…';
        }
        _runInFlight = true;
        appendOutput('POST ' + runner.endpoint + '\n');
        appendOutput('body: ' + JSON.stringify(body, null, 2) + '\n\n');
        setModalStatus('Calling helper…', 'text-muted');
        fetch(runner.endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        })
            .then(function (resp) {
                return resp.json().then(function (json) {
                    return { httpStatus: resp.status, body: json };
                });
            })
            .then(function (result) {
                var json = result.body || {};
                if (json.stdout)  appendOutput('--- stdout ---\n' + json.stdout);
                if (json.stderr)  appendOutput('--- stderr ---\n' + json.stderr);
                if (!json.stdout && !json.stderr) {
                    appendOutput('(no streamed output)\n');
                }
                appendOutput('\n--- result ---\n' + JSON.stringify(json, null, 2) + '\n');
                if (json.ok) {
                    setModalStatus(
                        '<i class="fas fa-check-circle text-success me-1"></i>'
                        + 'Action completed.'
                        + (json.requires_reboot ? ' <strong>Reboot required for the change to take effect.</strong>' : '')
                        + (json.duplicates_removed ? ' Removed ' + json.duplicates_removed + ' duplicate line(s).' : '')
                        + ((json.skipped_directives && json.skipped_directives.length)
                            ? ' Skipped: ' + json.skipped_directives.map(escapeHtml).join('; ') + '.'
                            : ''),
                        'text-success'
                    );
                    if (runner.post_action && runner.post_action.endpoint) {
                        appendOutput('\n--- post-action: ' + (runner.post_action.label || 'follow-up') + ' ---\n');
                        return fetch(runner.post_action.endpoint, {
                            method: 'POST',
                            credentials: 'same-origin',
                            headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
                            body: JSON.stringify(runner.post_action.body || {}),
                        }).then(function (r) { return r.json(); }).then(function (postJson) {
                            if (postJson.stdout) appendOutput(postJson.stdout);
                            if (postJson.stderr) appendOutput(postJson.stderr);
                            appendOutput(JSON.stringify(postJson, null, 2) + '\n');
                            if (!postJson.ok) {
                                setModalStatus(
                                    '<i class="fas fa-exclamation-triangle text-warning me-1"></i>'
                                    + 'Main action succeeded but follow-up '
                                    + escapeHtml(runner.post_action.label || '') + ' failed.',
                                    'text-warning'
                                );
                            }
                        });
                    }
                } else {
                    setModalStatus(
                        '<i class="fas fa-circle-xmark text-danger me-1"></i>'
                        + 'Action failed: ' + escapeHtml(json.error || ('HTTP ' + result.httpStatus)),
                        'text-danger'
                    );
                }
            })
            .catch(function (err) {
                appendOutput('\n--- request error ---\n' + String(err) + '\n');
                setModalStatus(
                    '<i class="fas fa-circle-xmark text-danger me-1"></i>'
                    + 'Request error: ' + escapeHtml(String(err)),
                    'text-danger'
                );
            })
            .finally(function () {
                _runInFlight = false;
                if (runBtn) {
                    runBtn.disabled = false;
                    runBtn.innerHTML = '<i class="fas fa-play me-1"></i>Run again';
                }
                // Re-poll diagnostics so the panel updates without a full
                // page reload. Small delay so the user can read the modal.
                setTimeout(function () { refresh(null); }, 500);
            });
    }

    function runActionInline(action) {
        // Bootstrap-modal-less fallback. Should only fire on environments
        // where bootstrap.bundle.js failed to load.
        if (!action.runner || !action.runner.endpoint) return;
        if (action.runner.confirm && !window.confirm(action.runner.confirm)) return;
        _activeAction = action;
        runActiveAction();
    }

    function findActionByIndex(idx) {
        var n = parseInt(idx, 10);
        if (isNaN(n) || n < 0 || n >= _lastActions.length) return null;
        return _lastActions[n];
    }

    document.addEventListener('DOMContentLoaded', function () {
        var card = document.getElementById('gps-hat-diag-card');
        if (!card) return;
        var btn = document.getElementById('gps-hat-refresh-btn');
        if (btn) {
            btn.addEventListener('click', function () { refresh(btn); });
        }
        // Delegated click handler for per-action Run buttons rendered
        // inside the actions container.
        var actionsHost = document.getElementById('gps-hat-actions');
        if (actionsHost) {
            actionsHost.addEventListener('click', function (ev) {
                var target = ev.target.closest('.gps-hat-run-btn');
                if (!target) return;
                ev.preventDefault();
                var action = findActionByIndex(target.getAttribute('data-action-idx'));
                if (action) openActionModal(action);
            });
        }
        // Modal "Run" button handler.
        var modalRunBtn = document.getElementById('gps-hat-modal-run-btn');
        if (modalRunBtn) {
            modalRunBtn.addEventListener('click', function () { runActiveAction(); });
        }
        refresh(null);
    });
})();
