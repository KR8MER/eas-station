/**
 * EAS Station™ — Shared Leaflet map helpers (theme aware)
 *
 * The browser-side twin of the share-image map renderer
 * (`app_utils/image_export/maps.py`). That renderer produces the alert
 * graphics people actually share, and it looks the way it does because a raw
 * OpenStreetMap mosaic is the loudest thing in frame: the basemap is toned
 * back to a quiet ground and the hazard polygon is the only saturated thing
 * left, drawn as a blurred glow + white casing + accent core so it reads at
 * thumbnail size.
 *
 * The in-app maps had none of that. This module gives every map the same
 * treatment and makes it follow the active theme:
 *
 *   • `init()`     — tone the basemap (via static/css/map.css), add the
 *                    hazard/reference panes, scale bar and attribution.
 *   • `hazard*()`  — draw an alert polygon the way the share card does.
 *   • `reference*()` — draw context boundaries as quiet lines underneath.
 *
 * Colours are read from CSS custom properties rather than hardcoded, so a
 * theme switch restyles the overlays without a page reload — layers created
 * through this module re-resolve their colour on the `theme-changed` event
 * dispatched by static/js/core/theme.js.
 *
 * Requires: Leaflet, static/css/map.css.
 */
(function (window, document) {
    'use strict';

    /** Leaflet pane z-indexes. All three sit inside the map pane so they pan
     *  and zoom with the map. Radar sits above the basemap tile pane
     *  (z=200) but below reference/hazard, so the alert polygon and county
     *  outlines stay legible drawn on top of it; reference sits under the
     *  hazard and the hazard under markers/tooltips, matching the share
     *  card's draw order (county outlines → glow → fill → casing → core). */
    var PANE_RADAR = 'easRadar';
    var PANE_REFERENCE = 'easReference';
    var PANE_HAZARD = 'easHazard';
    var Z_RADAR = 350;
    var Z_REFERENCE = 410;
    var Z_HAZARD = 430;

    /** IEM's WMS-T mosaic of NWS WSR-88D Level III base reflectivity
     *  (product N0Q), 5-minute cadence back to 2011-02-16. See
     *  https://mesonet.agron.iastate.edu/ogc/ -- "nexrad-n0q-wmst" is the
     *  actual data layer (there's also a non-image "time_idx" helper layer
     *  at the same capabilities level; don't request that one). */
    var RADAR_WMS_URL = 'https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi';
    var RADAR_WMS_LAYER = 'nexrad-n0q-wmst';

    /** Fallbacks used only when the stylesheet has not loaded (or a CSS
     *  variable was renamed) — they mirror `palette._SEVERITY`. */
    var SEVERITY_FALLBACK = {
        extreme: '#dc3545',
        severe: '#fd7e14',
        moderate: '#ffc107',
        minor: '#0d6efd',
        unknown: '#6c757d'
    };

    /** Used to pick which hazard the shared pane glow follows. */
    var SEVERITY_RANK = { extreme: 4, severe: 3, moderate: 2, minor: 1, unknown: 0 };

    /** Maps decorated by init(), so a theme switch can re-resolve colours. */
    var registry = [];
    var listening = false;

    // ── Colour helpers ──────────────────────────────────────────────────

    function cssVar(name, fallback) {
        var value = getComputedStyle(document.documentElement)
            .getPropertyValue(name).trim();
        return value || fallback;
    }

    function isDark() {
        return document.documentElement.getAttribute('data-theme-mode') === 'dark';
    }

    /**
     * Resolve a CAP severity to the active theme's colour for it.
     * @param {string} severity e.g. 'Severe'. Anything unrecognised → unknown.
     * @returns {string} CSS colour.
     */
    function severityColor(severity) {
        var key = String(severity || 'unknown').toLowerCase();
        if (!SEVERITY_FALLBACK[key]) {
            key = 'unknown';
        }
        return cssVar('--severity-' + key, SEVERITY_FALLBACK[key]);
    }

    /**
     * Resolve a CAP severity to its rank (higher = more severe), the same
     * table refreshGlow() uses to pick which alert's colour the shared pane
     * glow follows. Exposed so pages drawing several hazards at once (the
     * dashboard map) can sort by the same ordering instead of keeping a
     * second copy of this table that could drift from it.
     * @param {string} severity e.g. 'Severe'. Anything unrecognised → 0.
     * @returns {number}
     */
    function severityRank(severity) {
        var key = String(severity || 'unknown').toLowerCase();
        return SEVERITY_RANK[key] === undefined ? 0 : SEVERITY_RANK[key];
    }

    /**
     * Convert a CSS colour to `rgba(r, g, b, alpha)`.
     *
     * Themes express severity colours as hex, but the glow needs the same
     * hue at partial alpha. Anything the browser understands is normalised
     * through a canvas so `color(srgb …)` and `color-mix()` values survive;
     * naive string parsing of those yields wildly wrong numbers.
     */
    function withAlpha(color, alpha) {
        var probe = document.createElement('canvas').getContext('2d');
        probe.fillStyle = '#000';
        probe.fillStyle = color;
        var resolved = probe.fillStyle;   // always #rrggbb or rgba(...)

        if (resolved.charAt(0) === '#') {
            var int = parseInt(resolved.slice(1), 16);
            return 'rgba(' + ((int >> 16) & 255) + ', ' + ((int >> 8) & 255) +
                ', ' + (int & 255) + ', ' + alpha + ')';
        }
        // rgb()/rgba() form — swap in our alpha.
        var parts = resolved.replace(/rgba?\(|\)|\s/g, '').split(',');
        return 'rgba(' + parts[0] + ', ' + parts[1] + ', ' + parts[2] +
            ', ' + alpha + ')';
    }

    // ── Basemap ─────────────────────────────────────────────────────────

    /**
     * The OpenStreetMap tile layer, with the attribution the tile usage
     * policy requires. Toning happens in CSS (`.eas-map .leaflet-tile-pane`)
     * rather than here so it re-evaluates on a theme switch for free.
     *
     * @param {Object} [options] Passed through to L.tileLayer.
     */
    function tileLayer(options) {
        var opts = Object.assign({
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 18
        }, options || {});
        return L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', opts);
    }

    // ── Map decoration ──────────────────────────────────────────────────

    /**
     * Apply the shared skin to a map that already exists.
     *
     * @param {L.Map} map
     * @param {Object} [options]
     * @param {boolean} [options.scale=true]   Add a metric/imperial scale bar.
     * @param {boolean} [options.vignette=true] Darken the frame edges.
     * @returns {L.Map} the same map, for chaining.
     */
    function init(map, options) {
        var opts = options || {};
        var container = map.getContainer();

        container.classList.add('eas-map');
        if (opts.vignette === false) {
            container.classList.add('eas-map--flat');
        }

        if (!map.getPane(PANE_RADAR)) {
            map.createPane(PANE_RADAR).style.zIndex = Z_RADAR;
        }
        if (!map.getPane(PANE_REFERENCE)) {
            map.createPane(PANE_REFERENCE).style.zIndex = Z_REFERENCE;
        }
        if (!map.getPane(PANE_HAZARD)) {
            var hazardPane = map.createPane(PANE_HAZARD);
            hazardPane.style.zIndex = Z_HAZARD;
            hazardPane.classList.add('eas-pane-hazard');
        }

        if (opts.scale !== false && L.control.scale) {
            L.control.scale({ position: 'bottomleft', imperial: true, metric: true })
                .addTo(map);
        }

        if (map.attributionControl && map.attributionControl.setPrefix) {
            // Leaflet's default prefix is a Leaflet advert; the OSM credit
            // below it is the part the tile policy actually requires.
            map.attributionControl.setPrefix('');
        }

        if (registry.indexOf(map) === -1) {
            registry.push(map);
            map.on('unload', function () {
                var at = registry.indexOf(map);
                if (at !== -1) {
                    registry.splice(at, 1);
                }
            });
        }
        startListening();
        return map;
    }

    /**
     * Create a themed map in one call: L.map + toned basemap + skin.
     *
     * @param {string|HTMLElement} element Container id or node.
     * @param {Object} [options] Leaflet map options, plus `tile` (tile layer
     *        options), `scale` and `vignette` as per init().
     */
    function create(element, options) {
        var opts = options || {};
        var node = typeof element === 'string' ? document.getElementById(element) : element;
        if (node) {
            // Placeholder spinners live inside the container until the map
            // exists; Leaflet appends its panes rather than clearing them.
            node.innerHTML = '';
        }
        var map = L.map(node || element, opts);
        tileLayer(opts.tile).addTo(map);
        return init(map, opts);
    }

    // ── Hazard overlay ──────────────────────────────────────────────────

    /**
     * Draw a hazard polygon the way the share card does: a white casing
     * stroke under an accent core, over a semi-transparent fill, with the
     * pane-level glow behind it.
     *
     * Leaflet cannot cased-stroke a single path, so the geometry is drawn
     * twice — a heavier white layer first, the accent on top. Both go in the
     * hazard pane, which carries the glow filter.
     *
     * @param {Object} geojson GeoJSON feature or feature collection.
     * @param {Object} [options]
     * @param {string} [options.severity]  CAP severity; resolves the colour.
     * @param {string} [options.color]     Explicit colour (wins over severity).
     * @param {number} [options.weight=3]  Core stroke weight.
     * @param {number} [options.fillOpacity=0.28]
     * @param {string} [options.dashArray]
     * @param {string} [options.className] Extra class on the drawn paths.
     * @param {boolean} [options.casing=true] Draw the white halo stroke under
     *        the core. A page overlaying several hazards at once (the
     *        dashboard map) turns this off for broad/context alerts —
     *        several overlapping white halos are what actually reads as a
     *        "blob"; the single-alert pages (alert detail, VTEC trail) want
     *        it on so the shape pops against the basemap.
     * @param {Function} [options.onEachFeature] Applied to the core layer.
     * @returns {L.FeatureGroup} supports getBounds()/bindPopup()/addTo().
     */
    function hazardLayer(geojson, options) {
        var opts = options || {};
        var color = opts.color || severityColor(opts.severity);
        var weight = opts.weight || 3;
        var layers = [];

        if (opts.casing !== false) {
            layers.push(L.geoJSON(geojson, {
                pane: PANE_HAZARD,
                interactive: false,
                style: {
                    color: '#ffffff',
                    weight: weight + 2.5,
                    opacity: 0.9,
                    fill: false,
                    dashArray: opts.dashArray || null,
                    className: opts.className || undefined
                }
            }));
        }

        var core = L.geoJSON(geojson, {
            pane: PANE_HAZARD,
            style: {
                color: color,
                weight: weight,
                opacity: 1,
                fillColor: color,
                fillOpacity: opts.fillOpacity === undefined ? 0.28 : opts.fillOpacity,
                dashArray: opts.dashArray || null,
                className: opts.className || undefined
            },
            onEachFeature: opts.onEachFeature
        });
        layers.push(core);

        var group = L.featureGroup(layers);
        // Remembered so a theme switch can re-resolve the severity colour and
        // repaint the glow without the page having to reload the geometry.
        group._easHazard = { severity: opts.severity, fixedColor: opts.color, core: core };
        // `_map` is still set while the 'remove' event fires, but the layer
        // has already left `map._layers`, so the recount below is correct
        // for both directions.
        group.on('add remove', function () {
            refreshGlow(group._map);
        });
        return group;
    }

    /**
     * Repaint the hazard pane's glow.
     *
     * The glow is a pane-level filter — one blur for the whole overlay
     * instead of one per path, which is what keeps a 40-county flood watch
     * cheap. The cost is a single colour for the pane, so on a map showing
     * several alerts at once it follows the most severe one rather than
     * whichever happened to be added last.
     */
    function refreshGlow(map) {
        if (!map) {
            return;
        }
        var pane = map.getPane(PANE_HAZARD);
        if (!pane) {
            return;
        }
        var best = null;
        var bestRank = -1;
        map.eachLayer(function (layer) {
            var meta = layer._easHazard;
            if (!meta) {
                return;
            }
            var key = String(meta.severity || 'unknown').toLowerCase();
            var rank = SEVERITY_RANK[key] === undefined ? 0 : SEVERITY_RANK[key];
            if (rank >= bestRank) {
                bestRank = rank;
                best = meta.fixedColor || severityColor(meta.severity);
            }
        });
        pane.style.setProperty('--map-hazard-glow',
            withAlpha(best || severityColor('unknown'), 0.55));
    }

    /**
     * Style for context boundaries drawn underneath the hazard — quiet
     * reference lines, not a second subject. Mirrors the share card's muted
     * county outlines.
     *
     * @param {Object} [options]
     * @param {string} [options.color]      Tint the line toward a category colour.
     * @param {boolean} [options.emphasis]  Slightly heavier/brighter line.
     */
    function referenceStyle(options) {
        var opts = options || {};
        return {
            pane: PANE_REFERENCE,
            color: opts.color || cssVar('--map-reference-line', 'rgba(140, 155, 185, 0.5)'),
            weight: opts.emphasis ? 1.8 : 1.1,
            opacity: opts.emphasis ? 0.85 : 0.55,
            fillColor: opts.color || cssVar('--map-reference-line', 'rgba(140, 155, 185, 0.5)'),
            fillOpacity: opts.emphasis ? 0.06 : 0.03
        };
    }

    /** Convenience: an L.geoJSON already wearing referenceStyle(). */
    function referenceLayer(geojson, options) {
        var opts = options || {};
        return L.geoJSON(geojson, {
            pane: PANE_REFERENCE,
            style: referenceStyle(opts),
            onEachFeature: opts.onEachFeature
        });
    }

    // ── Radar overlay ───────────────────────────────────────────────────

    /**
     * Round a Date down to the nearest 5-minute mark, matching the WMS-T
     * service's PT5M cadence. The service's `nearestValue` flag is off (its
     * capabilities document does not advertise automatic snapping), so an
     * arbitrary timestamp between two real scans can come back empty rather
     * than returning the nearest one.
     */
    function _floorTo5Min(date) {
        var d = new Date(date.getTime());
        d.setUTCSeconds(0, 0);
        d.setUTCMinutes(Math.floor(d.getUTCMinutes() / 5) * 5);
        return d;
    }

    /**
     * NWS WSR-88D Level III base reflectivity (product N0Q), as a CONUS
     * mosaic from IEM's WMS-T service -- the classic green/yellow/red radar
     * image. Not raw Level II moments (reflectivity/velocity/spectrum width
     * per gate); that needs volume-scan decoding this doesn't attempt.
     *
     * @param {Object} [options]
     * @param {Date|string} [options.time] UTC time to show radar as-of
     *        (rounded down to the nearest 5 min). Omit for the current scan.
     * @param {number} [options.opacity=0.6] Layer opacity -- overlays drawn
     *        in the hazard/reference panes stay legible on top of it.
     * @returns {L.TileLayer.WMS}
     */
    function radarLayer(options) {
        var opts = options || {};
        var when = opts.time ? new Date(opts.time) : new Date();
        var timeParam = _floorTo5Min(when).toISOString().replace(/\.\d{3}Z$/, 'Z');

        return L.tileLayer.wms(RADAR_WMS_URL, {
            pane: PANE_RADAR,
            layers: RADAR_WMS_LAYER,
            format: 'image/png',
            transparent: true,
            version: '1.1.1',
            // 0.65 blended correctly but read as a solid weather-radar image
            // over a wide, intense cell. 0.45 kept the basemap legible but
            // read as too faint to register as radar at a glance. 0.6 is the
            // verified midpoint (matches _RADAR_OPACITY in maps.py).
            opacity: opts.opacity === undefined ? 0.6 : opts.opacity,
            attribution: 'Radar: Iowa Environmental Mesonet / NWS WSR-88D',
            time: timeParam
        });
    }

    // ── Theme switching ─────────────────────────────────────────────────

    function startListening() {
        if (listening) {
            return;
        }
        listening = true;
        window.addEventListener('theme-changed', function () {
            registry.forEach(refreshMap);
            themeCallbacks.forEach(function (fn) {
                try {
                    fn(isDark());
                } catch (err) {
                    console.error('EASMap theme callback failed:', err);
                }
            });
        });
    }

    /** Re-resolve every themed overlay on *map* against the new theme. */
    function refreshMap(map) {
        map.eachLayer(function (layer) {
            var meta = layer._easHazard;
            if (!meta) {
                return;
            }
            var color = meta.fixedColor || severityColor(meta.severity);
            meta.core.setStyle({ color: color, fillColor: color });
        });
        refreshGlow(map);
    }

    var themeCallbacks = [];

    /**
     * Run *fn* whenever the theme changes (and once immediately), for pages
     * that colour their own layers.
     * @param {Function} fn Receives `true` when the new theme is dark.
     */
    function onThemeChange(fn) {
        themeCallbacks.push(fn);
        startListening();
        fn(isDark());
    }

    window.EASMap = {
        PANE_HAZARD: PANE_HAZARD,
        PANE_REFERENCE: PANE_REFERENCE,
        PANE_RADAR: PANE_RADAR,
        isDark: isDark,
        cssVar: cssVar,
        withAlpha: withAlpha,
        severityColor: severityColor,
        severityRank: severityRank,
        tileLayer: tileLayer,
        init: init,
        create: create,
        hazardLayer: hazardLayer,
        referenceStyle: referenceStyle,
        referenceLayer: referenceLayer,
        radarLayer: radarLayer,
        onThemeChange: onThemeChange
    };
})(window, document);
