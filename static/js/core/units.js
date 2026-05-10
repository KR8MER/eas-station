/* eslint-disable no-var */
/**
 * EAS Station — display-units preference module.
 *
 * Wraps lat/lon, altitude, speed and distance formatting behind a
 * single namespace (`window.EASUnits`) so every page renders these
 * values in whichever units the operator picked.  The selection is
 * persisted in localStorage and broadcast as a window-level
 * `eas:units-changed` CustomEvent so live dashboards can re-render
 * the moment the user flips a setting.
 */
(function (window) {
    'use strict';

    var STORAGE_KEY = 'eas:units:v1';
    var DEFAULTS = {
        coord:    'decimal',  // 'decimal' | 'dms'
        altitude: 'm',        // 'm' | 'ft'
        speed:    'kn',       // 'm/s' | 'kn' | 'mph' | 'km/h'
        distance: 'm'         // 'm' | 'ft' | 'mi' | 'nmi'
    };
    var LABELS = {
        coord:    [['decimal', 'D.dddd'], ['dms', 'DMS']],
        altitude: [['m', 'm'], ['ft', 'ft']],
        speed:    [['kn', 'kn'], ['mph', 'mph'], ['km/h', 'km/h'], ['m/s', 'm/s']],
        distance: [['m', 'm'], ['ft', 'ft'], ['mi', 'mi'], ['nmi', 'nmi']]
    };
    var ROW_LABELS = {
        coord: 'Coords', altitude: 'Altitude', speed: 'Speed', distance: 'Distance'
    };

    var prefs = load();

    function load() {
        var out = {};
        for (var k in DEFAULTS) out[k] = DEFAULTS[k];
        try {
            var raw = window.localStorage && localStorage.getItem(STORAGE_KEY);
            if (raw) {
                var parsed = JSON.parse(raw);
                for (var key in DEFAULTS) {
                    if (parsed && typeof parsed[key] === 'string' && hasOption(key, parsed[key])) {
                        out[key] = parsed[key];
                    }
                }
            }
        } catch (e) { /* ignore — fall back to defaults */ }
        return out;
    }
    function save() {
        try {
            if (window.localStorage) localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
        } catch (e) { /* quota / private mode — ignore */ }
    }
    function hasOption(category, value) {
        var opts = LABELS[category];
        if (!opts) return false;
        for (var i = 0; i < opts.length; i++) if (opts[i][0] === value) return true;
        return false;
    }

    function get(category) {
        return Object.prototype.hasOwnProperty.call(prefs, category) ? prefs[category] : DEFAULTS[category];
    }
    function set(category, value) {
        if (!hasOption(category, value)) return;
        if (prefs[category] === value) return;
        prefs[category] = value;
        save();
        try {
            window.dispatchEvent(new CustomEvent('eas:units-changed', {
                detail: { category: category, value: value, prefs: getAll() }
            }));
        } catch (e) { /* very old browsers — ignore */ }
    }
    function getAll() {
        var out = {};
        for (var k in prefs) out[k] = prefs[k];
        return out;
    }

    // ── Formatters ─────────────────────────────────────────────────
    function _num(v) { return (v != null && !isNaN(v)) ? Number(v) : null; }
    function _prec(opts, fallback) {
        return (opts && opts.precision != null) ? opts.precision : fallback;
    }

    function fmtLat(lat, opts) {
        var v = _num(lat);
        if (v === null) return '—';
        if (get('coord') === 'dms') return _dms(v, 'NS');
        return v.toFixed(_prec(opts, 6)) + '°';
    }
    function fmtLon(lon, opts) {
        var v = _num(lon);
        if (v === null) return '—';
        if (get('coord') === 'dms') return _dms(v, 'EW');
        return v.toFixed(_prec(opts, 6)) + '°';
    }
    function fmtCoord(lat, lon, opts) {
        var a = _num(lat), b = _num(lon);
        if (a === null || b === null) return '—';
        return fmtLat(a, opts) + ', ' + fmtLon(b, opts);
    }
    function _dms(value, hemis) {
        var hemi = (value >= 0) ? hemis[0] : hemis[1];
        var v = Math.abs(value);
        var d = Math.floor(v);
        var mF = (v - d) * 60;
        var m = Math.floor(mF);
        var s = (mF - m) * 60;
        // Rollover guard — 59.95 s → 60.0 s would render as 60"
        if (s >= 59.95) { s = 0; m += 1; }
        if (m >= 60)    { m = 0; d += 1; }
        var pad = (m < 10 ? '0' : '') + m;
        return d + '°' + pad + "'" + s.toFixed(1) + '"' + hemi;
    }

    function fmtAltitude(meters, opts) {
        var v = _num(meters);
        if (v === null) return '—';
        if (get('altitude') === 'ft') return (v * 3.28084).toFixed(_prec(opts, 0)) + ' ft';
        return v.toFixed(_prec(opts, 1)) + ' m';
    }

    function fmtSpeed(metersPerSec, opts) {
        var v = _num(metersPerSec);
        if (v === null) return '—';
        var p = _prec(opts, 1);
        switch (get('speed')) {
            case 'kn':   return (v * 1.943844).toFixed(p) + ' kn';
            case 'mph':  return (v * 2.236936).toFixed(p) + ' mph';
            case 'km/h': return (v * 3.6).toFixed(p)      + ' km/h';
            default:     return v.toFixed(p)              + ' m/s';
        }
    }

    function fmtDistance(meters, opts) {
        var v = _num(meters);
        if (v === null) return '—';
        var p = _prec(opts, 1);
        switch (get('distance')) {
            case 'ft':  return (v * 3.28084).toFixed(p) + ' ft';
            case 'mi':  return (v / 1609.344).toFixed(p) + ' mi';
            case 'nmi': return (v / 1852).toFixed(p)     + ' nmi';
            default:    return v.toFixed(p)              + ' m';
        }
    }

    // ── Selector UI ────────────────────────────────────────────────
    // Renders a compact <select>-per-category panel inside `container`.
    // Keeps its own option <select>s in sync if the user changes a
    // preference somewhere else (e.g. another tab or another widget
    // on the same page).
    function attachSelector(container, options) {
        if (!container) return;
        var categories = (options && options.categories) || ['coord', 'altitude', 'speed', 'distance'];
        var html = '<div class="eas-units-selector" role="group" aria-label="Display units">';
        categories.forEach(function (cat) {
            html += '<label class="eas-units-row">' +
                        '<span class="eas-units-row-label">' + (ROW_LABELS[cat] || cat) + '</span>' +
                        '<select class="form-select form-select-sm eas-units-select" data-units-category="' + cat + '">';
            (LABELS[cat] || []).forEach(function (opt) {
                html += '<option value="' + opt[0] + '"' + (get(cat) === opt[0] ? ' selected' : '') + '>' + opt[1] + '</option>';
            });
            html += '</select></label>';
        });
        html += '</div>';
        container.innerHTML = html;
        container.querySelectorAll('select.eas-units-select').forEach(function (sel) {
            sel.addEventListener('change', function () {
                set(this.getAttribute('data-units-category'), this.value);
            });
        });
        window.addEventListener('eas:units-changed', function (ev) {
            if (!container.isConnected) return;
            var cat = ev && ev.detail && ev.detail.category;
            if (!cat) return;
            var sel = container.querySelector('select[data-units-category="' + cat + '"]');
            if (sel && sel.value !== ev.detail.value) sel.value = ev.detail.value;
        });
    }

    window.EASUnits = {
        get: get, set: set, getAll: getAll,
        fmtLat: fmtLat, fmtLon: fmtLon, fmtCoord: fmtCoord,
        fmtAltitude: fmtAltitude, fmtSpeed: fmtSpeed, fmtDistance: fmtDistance,
        attachSelector: attachSelector,
        DEFAULTS: DEFAULTS
    };
})(window);
