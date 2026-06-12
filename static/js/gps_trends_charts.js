/*!
 * EAS Station — GPS dashboard "Historical Trends" charts.
 *
 * Renders four long-window Chart.js line charts at the bottom of the
 * GPS & Time dashboard from the tiered trend archive served by
 * GET /admin/api/gps-dashboard/trends?window=1h|6h|24h|7d|30d|90d
 * (raw 5 s tier ≈1.1 h → 1 h buckets ≈91 d).
 *
 * Deliberately self-contained: it does NOT touch the page's existing
 * 1 Hz status poll, its hand-rolled sparkline ring buffers, or the
 * engineering window selector — this section has its own selector
 * (default 24h) and a slow 60 s auto-refresh.
 *
 * Requires: Chart.js v3 + chartjs-adapter-date-fns (both vendored and
 * included by templates/admin/gps_dashboard.html before this file).
 */
(function () {
    'use strict';

    var ENDPOINT = '/admin/api/gps-dashboard/trends';
    var DEFAULT_WINDOW = '24h';
    var REFRESH_MS = 60000;        // slow refresh — archive ticks at >=5 s
    var MAX_POINTS = 700;          // client-side decimation cap per series

    // Mirrors the server-side GPS_TRENDS_WINDOW_TO_TIER table
    // (services/gps/trends.py); used for the caption until the payload's
    // authoritative bucket_seconds arrives.
    var WINDOW_RESOLUTIONS = {
        '1h': '5 s', '6h': '1 min', '24h': '1 min',
        '7d': '10 min', '30d': '1 hour', '90d': '1 hour'
    };

    var currentWindow = DEFAULT_WINDOW;
    var charts = {};               // canvasId -> Chart instance
    var inFlight = false;
    var refreshTimer = null;

    // ── Theme helpers ──────────────────────────────────────────────
    function cssVar(name, fallback) {
        try {
            var v = getComputedStyle(document.documentElement).getPropertyValue(name);
            return (v && v.trim()) ? v.trim() : fallback;
        } catch (e) { return fallback; }
    }
    function theme() {
        return {
            text:  cssVar('--text-color', '#e6edf3'),
            muted: cssVar('--text-muted', '#8b949e'),
            grid:  'rgba(127,127,127,0.14)'
        };
    }
    // Palette shared with the page's sparkline swatches (GitHub-dark hues).
    var C = {
        blue:   '#58a6ff',
        purple: '#bc8cff',
        green:  '#3fb950',
        amber:  '#d29922',
        red:    '#f85149',
        teal:   '#39c5cf'
    };
    function rgba(hex, a) {
        var n = parseInt(hex.slice(1), 16);
        return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
    }

    // ── Data helpers ───────────────────────────────────────────────
    function decimate(samples) {
        if (!samples || samples.length <= MAX_POINTS) return samples || [];
        var stride = Math.ceil(samples.length / MAX_POINTS);
        var out = [];
        for (var i = 0; i < samples.length; i += stride) out.push(samples[i]);
        // Always keep the newest sample so the right edge is current.
        if (out[out.length - 1] !== samples[samples.length - 1]) {
            out.push(samples[samples.length - 1]);
        }
        return out;
    }
    function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : null; }
    // Build {x: ms, y} points; nulls preserved so Chart.js draws gaps
    // (spanGaps stays false everywhere).
    function pts(samples, field, scale, positiveOnly) {
        var out = [];
        for (var i = 0; i < samples.length; i++) {
            var s = samples[i] || {};
            var t = num(s.t);
            if (t === null) continue;
            var v = num(s[field]);
            if (v !== null) {
                if (positiveOnly && v <= 0) v = null;
                else v = v * (scale || 1);
            }
            out.push({ x: t, y: v });
        }
        return out;
    }
    function anyValue(points) {
        for (var i = 0; i < points.length; i++) if (points[i].y !== null) return true;
        return false;
    }
    function maxAbs(points) {
        var m = 0;
        for (var i = 0; i < points.length; i++) {
            var y = points[i].y;
            if (y !== null && Math.abs(y) > m) m = Math.abs(y);
        }
        return m;
    }
    function fmtVal(v) {
        if (v === null || v === undefined || !isFinite(v)) return '—';
        var a = Math.abs(v);
        if (a !== 0 && (a < 0.001 || a >= 1e6)) return v.toExponential(2);
        if (a >= 100) return v.toFixed(1);
        if (a >= 1) return v.toFixed(2);
        return v.toFixed(3);
    }

    // ── Chart scaffolding ─────────────────────────────────────────
    // Whether the date-fns adapter actually loaded; if not we fall back
    // to a linear x-axis with manually formatted local-time ticks.
    function hasDateAdapter() {
        try {
            var A = window.Chart && Chart._adapters && Chart._adapters._date;
            if (!A) return false;
            var probe = new A({});
            // The unconfigured base adapter throws from format(); a real
            // adapter (date-fns bundle) returns a string.
            return typeof probe.format(Date.now(), 'yyyy') === 'string';
        } catch (e) { return false; }
    }
    var USE_TIME_SCALE = false;    // resolved in init()

    function fmtTickLocal(ms) {
        var d = new Date(ms);
        var spanDays = ({ '1h': 0, '6h': 0.25, '24h': 1, '7d': 7, '30d': 30, '90d': 90 })[currentWindow] || 1;
        if (spanDays >= 7) {
            return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
        }
        if (spanDays >= 1) {
            return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
                   d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function xScale() {
        var t = theme();
        if (USE_TIME_SCALE) {
            return {
                type: 'time',
                time: {
                    tooltipFormat: 'MMM d, HH:mm:ss',
                    displayFormats: {
                        second: 'HH:mm:ss', minute: 'HH:mm', hour: 'MMM d HH:mm',
                        day: 'MMM d', week: 'MMM d', month: 'MMM yyyy'
                    }
                },
                ticks: { color: t.muted, maxTicksLimit: 8, maxRotation: 0, autoSkip: true, font: { size: 10 } },
                grid: { color: t.grid, borderColor: t.grid }
            };
        }
        return {
            type: 'linear',
            ticks: {
                color: t.muted, maxTicksLimit: 7, maxRotation: 0, autoSkip: true,
                font: { size: 10 },
                callback: function (value) { return fmtTickLocal(value); }
            },
            grid: { color: t.grid, borderColor: t.grid }
        };
    }
    function yScale(title, opts) {
        var t = theme();
        var s = {
            type: (opts && opts.log) ? 'logarithmic' : 'linear',
            position: (opts && opts.position) || 'left',
            title: { display: true, text: title, color: t.muted, font: { size: 10 } },
            ticks: {
                color: t.muted, maxTicksLimit: 6, font: { size: 10 },
                callback: function (value) { return fmtVal(typeof value === 'number' ? value : Number(value)); }
            },
            grid: { color: t.grid, borderColor: t.grid }
        };
        if (opts && opts.position === 'right') s.grid.drawOnChartArea = false;
        if (opts && opts.beginAtZero) s.beginAtZero = true;
        return s;
    }
    function baseOptions(scales) {
        var t = theme();
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            spanGaps: false,
            parsing: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
                legend: {
                    display: true, position: 'top', align: 'end',
                    labels: { color: t.text, boxWidth: 10, boxHeight: 10, padding: 10, font: { size: 10 } }
                },
                tooltip: {
                    callbacks: {
                        title: function (items) {
                            if (!items.length) return '';
                            var x = items[0].parsed.x;
                            return new Date(x).toLocaleString([], {
                                month: 'short', day: 'numeric',
                                hour: '2-digit', minute: '2-digit', second: '2-digit'
                            });
                        },
                        label: function (item) {
                            return (item.dataset.label || '') + ': ' + fmtVal(item.parsed.y);
                        }
                    }
                },
                // The page loads chartjs plugins globally on some other
                // dashboards; keep datalabels off if it ever registers.
                datalabels: { display: false }
            },
            scales: scales
        };
    }
    function dataset(label, points, color, opts) {
        var d = {
            label: label,
            data: points,
            borderColor: color,
            backgroundColor: rgba(color, 0.12),
            borderWidth: 1.4,
            pointRadius: 0,
            pointHitRadius: 6,
            tension: 0.18,
            fill: false,
            spanGaps: false
        };
        if (opts) for (var k in opts) if (Object.prototype.hasOwnProperty.call(opts, k)) d[k] = opts[k];
        return d;
    }

    function setEmpty(key, message) {
        var el = document.getElementById('gps-hist-' + key + '-empty');
        if (el) {
            el.style.display = message ? 'flex' : 'none';
            if (message) el.textContent = message;
        }
    }
    // Create the chart on first use, then swap datasets/scales in place.
    function upsertChart(key, datasets, scales) {
        var canvas = document.getElementById('gps-hist-' + key + '-canvas');
        if (!canvas) return;
        var chart = charts[key];
        if (!chart) {
            chart = new Chart(canvas, {
                type: 'line',
                data: { datasets: datasets },
                options: baseOptions(scales)
            });
            charts[key] = chart;
        } else {
            chart.data.datasets = datasets;
            chart.options.scales = scales;
            chart.update('none');
        }
    }

    // ── The four chart builders ───────────────────────────────────
    function renderClock(samples) {
        var freq = pts(samples, 'frequency_ppm');
        var offRaw = pts(samples, 'last_offset_s');
        // Scale chrony's last offset to µs when everything is sub-ms,
        // otherwise ms — keeps the axis readable across disciplines.
        var m = maxAbs(offRaw);
        var unitIsUs = (m > 0 && m < 0.0005);
        var scale = unitIsUs ? 1e6 : 1e3;
        var unit = unitIsUs ? 'µs' : 'ms';
        var off = offRaw.map(function (p) { return { x: p.x, y: p.y === null ? null : p.y * scale }; });

        if (!anyValue(freq) && !anyValue(off)) {
            setEmpty('clock', 'No chrony samples in this window');
        } else {
            setEmpty('clock', null);
        }
        upsertChart('clock', [
            dataset('Frequency (ppm)', freq, C.blue, { yAxisID: 'y' }),
            dataset('Last offset (' + unit + ')', off, C.purple, { yAxisID: 'y2' })
        ], {
            x: xScale(),
            y:  yScale('ppm'),
            y2: yScale(unit, { position: 'right' })
        });
    }

    function renderJitter(samples) {
        var jit = pts(samples, 'pps_jitter_ns', 1, true);   // >0 only — log-safe
        var a10 = pts(samples, 'adev_10s', 1, true);
        var a100 = pts(samples, 'adev_100s', 1, true);
        var haveAdev = anyValue(a10) || anyValue(a100);

        if (!anyValue(jit) && !haveAdev) {
            setEmpty('jitter', 'No PPS jitter samples in this window');
        } else {
            setEmpty('jitter', null);
        }
        // Log axis when jitter spans more than ~2 decades, linear otherwise.
        var lo = Infinity, hi = 0;
        for (var i = 0; i < jit.length; i++) {
            var y = jit[i].y;
            if (y !== null) { if (y < lo) lo = y; if (y > hi) hi = y; }
        }
        var useLog = (hi > 0 && lo < Infinity && (hi / Math.max(lo, 1e-12)) > 100);

        var sets = [dataset('PPS jitter (ns)', jit, C.blue, { yAxisID: 'y' })];
        var scales = { x: xScale(), y: yScale('ns' + (useLog ? ' (log)' : ''), { log: useLog }) };
        if (haveAdev) {
            sets.push(dataset('ADEV τ=10 s', a10, C.amber, { yAxisID: 'y2', borderDash: [4, 3] }));
            sets.push(dataset('ADEV τ=100 s', a100, C.red, { yAxisID: 'y2', borderDash: [2, 3] }));
            scales.y2 = yScale('σy(τ) (log)', { position: 'right', log: true });
        }
        upsertChart('jitter', sets, scales);
    }

    function renderSats(samples) {
        var used = pts(samples, 'sats_used');
        var vis = pts(samples, 'sats_visible');
        var snr = pts(samples, 'avg_snr');

        if (!anyValue(used) && !anyValue(vis) && !anyValue(snr)) {
            setEmpty('sats', 'No satellite samples in this window');
        } else {
            setEmpty('sats', null);
        }
        upsertChart('sats', [
            dataset('Sats used', used, C.green, { yAxisID: 'y', stepped: true, tension: 0 }),
            dataset('Sats visible', vis, C.teal, { yAxisID: 'y', stepped: true, tension: 0, borderDash: [4, 3] }),
            dataset('Avg SNR (dB-Hz)', snr, C.amber, { yAxisID: 'y2' })
        ], {
            x: xScale(),
            y:  yScale('satellites', { beginAtZero: true }),
            y2: yScale('dB-Hz', { position: 'right' })
        });
    }

    function renderEnv(samples) {
        var temp = pts(samples, 'cpu_temp_c');
        var hold = pts(samples, 'holdover_s');
        // Only chart holdover when it ever left zero — a flat 0 line
        // just compresses the temperature trace for no information.
        var holdSeen = false;
        for (var i = 0; i < hold.length; i++) {
            if (hold[i].y !== null && hold[i].y > 0) { holdSeen = true; break; }
        }

        if (!anyValue(temp) && !holdSeen) {
            setEmpty('env', anyValue(hold) ? 'No CPU temperature samples (holdover steady at 0 s)'
                                           : 'No environment samples in this window');
        } else {
            setEmpty('env', null);
        }
        var sets = [dataset('CPU temp (°C)', temp, C.red, { yAxisID: 'y', fill: true })];
        var scales = { x: xScale(), y: yScale('°C') };
        if (holdSeen) {
            sets.push(dataset('Holdover (s)', hold, C.amber, { yAxisID: 'y2', stepped: true, tension: 0 }));
            scales.y2 = yScale('s', { position: 'right', beginAtZero: true });
        }
        upsertChart('env', sets, scales);
    }

    function renderAll(samples) {
        renderClock(samples);
        renderJitter(samples);
        renderSats(samples);
        renderEnv(samples);
    }

    // ── Fetch / refresh plumbing ──────────────────────────────────
    function setResolutionCaption(bucketSeconds) {
        var el = document.getElementById('gps-hist-window-resolution');
        if (!el) return;
        var label;
        if (typeof bucketSeconds === 'number' && bucketSeconds > 0) {
            label = bucketSeconds >= 3600 ? (bucketSeconds / 3600) + ' hour'
                  : bucketSeconds >= 60   ? (bucketSeconds / 60) + ' min'
                  : bucketSeconds + ' s';
        } else {
            label = WINDOW_RESOLUTIONS[currentWindow] || '—';
        }
        el.textContent = 'resolution: ' + label;
    }

    function fetchAndRender() {
        if (inFlight) return;
        inFlight = true;
        fetch(ENDPOINT + '?window=' + encodeURIComponent(currentWindow), { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (payload) {
                payload = payload || {};
                var samples = decimate(Array.isArray(payload.samples) ? payload.samples : []);
                setResolutionCaption(payload.bucket_seconds);
                if (!samples.length) {
                    ['clock', 'jitter', 'sats', 'env'].forEach(function (key) {
                        setEmpty(key, 'No archived samples for this window yet');
                        var ch = charts[key];
                        if (ch) {
                            ch.data.datasets.forEach(function (d) { d.data = []; });
                            ch.update('none');
                        }
                    });
                    return;
                }
                renderAll(samples);
            })
            .catch(function (err) {
                if (window.console && console.warn) {
                    console.warn('GPS historical trends fetch failed:', err);
                }
                ['clock', 'jitter', 'sats', 'env'].forEach(function (key) {
                    if (!charts[key]) setEmpty(key, 'Trend archive unavailable');
                });
            })
            .then(function () { inFlight = false; }, function () { inFlight = false; });
    }

    function startRefresh() {
        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(function () {
            // Don't burn cycles (or fight the 1 Hz poll for bandwidth)
            // while the tab is hidden — the next visible tick catches up.
            if (document.hidden) return;
            fetchAndRender();
        }, REFRESH_MS);
    }

    function init() {
        var section = document.getElementById('gps-hist-section');
        if (!section || typeof window.Chart === 'undefined') return;
        USE_TIME_SCALE = hasDateAdapter();

        var sel = document.getElementById('gps-hist-window-select');
        if (sel) {
            sel.value = currentWindow;
            sel.addEventListener('change', function () {
                currentWindow = sel.value || DEFAULT_WINDOW;
                setResolutionCaption(null);
                fetchAndRender();
            });
        }
        setResolutionCaption(null);
        fetchAndRender();
        startRefresh();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
