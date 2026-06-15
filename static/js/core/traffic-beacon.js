/*
 * EAS Station - Traffic analytics client beacon
 *
 * Reports the browser's screen resolution to the server once per session so the
 * Traffic Analytics dashboard can show resolution stats (awstats-style). Screen
 * size is not available in HTTP headers, so it must be sampled client-side.
 *
 * Lightweight and best-effort: a single GET with the resolution as query
 * params, guarded by sessionStorage so it only fires once per browser session.
 */
(function () {
    'use strict';

    try {
        if (sessionStorage.getItem('eas_traffic_beacon_sent')) {
            return;
        }
        var w = window.screen && window.screen.width;
        var h = window.screen && window.screen.height;
        if (!w || !h) {
            return;
        }
        // Device pixel ratio aware physical resolution is overkill here; the CSS
        // pixel resolution matches what awstats-style reports show.
        var url = '/api/traffic/client?w=' + encodeURIComponent(w) + '&h=' + encodeURIComponent(h);
        fetch(url, { method: 'GET', credentials: 'same-origin' })
            .then(function () {
                try { sessionStorage.setItem('eas_traffic_beacon_sent', '1'); } catch (e) {}
            })
            .catch(function () { /* ignore — analytics must never disrupt the page */ });
    } catch (e) {
        /* sessionStorage/screen unavailable — silently skip */
    }
})();
