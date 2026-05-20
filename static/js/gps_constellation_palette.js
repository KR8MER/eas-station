/* ===========================================================================
 * EAS Station ™ — shared GPS constellation palette
 *
 * Single source of truth for the colours we use to differentiate GNSS
 * constellations across the three GPS panels in the UI:
 *
 *   - templates/admin/gps_dashboard.html   (full chrogps-dash style page)
 *   - templates/admin/hardware_settings.html  (live GPS panel)
 *   - templates/system_health.html         (system-wide GPS card)
 *
 * Each template imports this file and reads palette values from
 * ``window.EAS_GPS_PALETTE`` instead of duplicating the constants
 * inline.  Templates may layer thin wrappers on top to satisfy local
 * naming conventions (e.g. ``gpsConstInfo`` vs ``constInfo``) — the
 * canonical helpers below are stable.
 *
 * Keys are NMEA talker IDs (the two-letter prefix of a sentence's
 * source field, e.g. ``GP`` for GPS, ``GL`` for GLONASS).  Unknown
 * codes get rendered as neutral grey so a new constellation showing up
 * in a future receiver firmware doesn't break the layout.
 * =========================================================================*/
(function (global) {
    'use strict';

    var CONSTELLATION_INFO = {
        'GP': { color: '#58a6ff', label: 'GPS' },
        'GL': { color: '#f85149', label: 'GLONASS' },
        'GA': { color: '#bc8cff', label: 'Galileo' },
        'GB': { color: '#ffa657', label: 'BeiDou' },
        'GQ': { color: '#79c0ff', label: 'QZSS' },
        'GI': { color: '#84cc16', label: 'NavIC' },
        'SB': { color: '#a78bfa', label: 'SBAS' }
    };

    function constInfo(code) {
        return CONSTELLATION_INFO[code] || { color: '#8b949e', label: code || 'Unknown' };
    }

    /* SNR (dBHz) palette — five steps plus an "unknown" bucket.
       Stops match the legacy GPS panels so colours stay consistent. */
    var SNR_COLORS = {
        s0: '#484f58',
        s1: '#f85149',
        s2: '#f97316',
        s3: '#d29922',
        s4: '#84cc16',
        s5: '#3fb950'
    };

    /* Raw bucket — returns just the suffix ("s0".."s5") so each
       template can prefix it with whatever CSS namespace it uses
       (``gps-snr-s3`` vs ``snr-s3``). */
    function snrBucket(snr) {
        if (snr === null || snr === undefined) return 's0';
        if (snr >= 45) return 's5';
        if (snr >= 35) return 's4';
        if (snr >= 25) return 's3';
        if (snr >= 15) return 's2';
        return 's1';
    }

    function snrHex(snr) {
        return SNR_COLORS[snrBucket(snr)] || SNR_COLORS.s0;
    }

    /* Sky-plot dot opacity — ramps with SNR so strong sats glow and
       weak ones fade while colour stays locked to constellation. */
    function snrAlpha(snr) {
        if (snr === null || snr === undefined) return 0.55;
        return Math.max(0.45, Math.min(0.95, 0.4 + snr / 60));
    }

    global.EAS_GPS_PALETTE = {
        CONSTELLATION_INFO: CONSTELLATION_INFO,
        constInfo: constInfo,
        SNR_COLORS: SNR_COLORS,
        snrBucket: snrBucket,
        snrHex: snrHex,
        snrAlpha: snrAlpha
    };
})(typeof window !== 'undefined' ? window : this);
