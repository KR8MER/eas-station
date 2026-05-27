/**
 * EAS Station - Alert Watch Module
 *
 * Surfaces active CAP alerts to the operator regardless of which tab is
 * focused.  Two complementary signals are wired off the `alerts_update`
 * WebSocket event (already pushed by app_core.websocket_push at ~5s):
 *
 *   1. Document-title badge.  When any active alerts exist, the tab title
 *      becomes "(N) <original title>".  An operator scanning a browser
 *      window full of tabs sees the count without switching pages.
 *
 *   2. Toast + (optional) browser Notification when *new* alert IDs first
 *      appear.  The very first payload after page load primes the
 *      seen-set silently, so navigation/reloads don't re-fire toasts for
 *      already-active alerts.
 *
 * Seen-IDs are kept in sessionStorage so each tab is self-contained and
 * a fresh tab won't replay history.
 */
(function (window) {
    'use strict';

    const SEEN_KEY = 'eas:alert-watch:seen-ids';
    const TITLE_PREFIX_RE = /^\(\d+\)\s+/;
    const MAX_TOASTS_PER_UPDATE = 3;

    // Cache the page's pristine title (without any prefix we may have added).
    let baseTitle = document.title.replace(TITLE_PREFIX_RE, '');
    let primed = false;  // true after the first payload has been processed

    function loadSeen() {
        try {
            const raw = sessionStorage.getItem(SEEN_KEY);
            if (!raw) return new Set();
            const arr = JSON.parse(raw);
            return new Set(Array.isArray(arr) ? arr : []);
        } catch (_e) {
            return new Set();
        }
    }

    function saveSeen(set) {
        try {
            // Cap the persisted set so it doesn't grow without bound across
            // a long-lived session.
            const arr = Array.from(set).slice(-200);
            sessionStorage.setItem(SEEN_KEY, JSON.stringify(arr));
        } catch (_e) {
            // Storage full / disabled — silently degrade.
        }
    }

    function severityToToastType(severity) {
        switch ((severity || '').toLowerCase()) {
            case 'extreme': return 'error';
            case 'severe':  return 'warning';
            case 'moderate': return 'warning';
            case 'minor':   return 'info';
            default:        return 'info';
        }
    }

    function updateTitleBadge(count) {
        const prefix = count > 0 ? `(${count}) ` : '';
        const next = prefix + baseTitle;
        if (document.title !== next) {
            document.title = next;
        }
    }

    function maybeNotify(alert) {
        // Only fire a desktop Notification if the user has already granted
        // permission AND the tab is hidden.  We never auto-prompt — that has
        // to happen from a user gesture (see enableNotifications()).
        if (typeof window.Notification === 'undefined') return;
        if (Notification.permission !== 'granted') return;
        if (!document.hidden) return;

        try {
            const title = alert.event || 'Active Alert';
            const body = alert.headline || `${alert.severity || ''} ${alert.urgency || ''}`.trim();
            const n = new Notification(`EAS Station: ${title}`, {
                body,
                tag: `eas-alert-${alert.id}`,  // dedupes if re-fired
                requireInteraction: (alert.severity || '').toLowerCase() === 'extreme',
            });
            n.onclick = function () {
                window.focus();
                n.close();
            };
        } catch (_e) {
            // Notification constructor can throw on some platforms; ignore.
        }
    }

    function toastForAlert(alert) {
        if (typeof window.showToast !== 'function') return;
        const type = severityToToastType(alert.severity);
        const title = alert.event || 'Active Alert';
        const body = alert.headline || `${alert.severity || 'Unknown'} · ${alert.urgency || 'Unknown'}`;
        // window.showToast signature (from loading-error-utils.js):
        //   showToast(message, type, title, duration)
        window.showToast(body, type, title, 10000);
    }

    function handleAlertsUpdate(payload) {
        if (!payload || !Array.isArray(payload.alerts)) return;

        const alerts = payload.alerts;
        const count = typeof payload.count === 'number' ? payload.count : alerts.length;
        updateTitleBadge(count);

        const seen = loadSeen();

        if (!primed) {
            // First payload after page load: record everything as seen so
            // we don't toast for already-active alerts on every navigation.
            alerts.forEach(a => { if (a && a.id != null) seen.add(String(a.id)); });
            saveSeen(seen);
            primed = true;
            return;
        }

        const fresh = alerts.filter(a => a && a.id != null && !seen.has(String(a.id)));
        if (fresh.length === 0) return;

        // Toast the most recent N; mark all fresh as seen.
        fresh.slice(0, MAX_TOASTS_PER_UPDATE).forEach(alert => {
            toastForAlert(alert);
            maybeNotify(alert);
        });

        if (fresh.length > MAX_TOASTS_PER_UPDATE) {
            const extra = fresh.length - MAX_TOASTS_PER_UPDATE;
            if (typeof window.showToast === 'function') {
                window.showToast(
                    `+${extra} more active alert${extra === 1 ? '' : 's'} — open the Alerts page for the full list.`,
                    'info',
                    'Additional Alerts',
                    8000,
                );
            }
        }

        fresh.forEach(a => seen.add(String(a.id)));
        saveSeen(seen);
    }

    function enableNotifications() {
        if (typeof window.Notification === 'undefined') {
            return Promise.resolve('unsupported');
        }
        if (Notification.permission === 'granted' || Notification.permission === 'denied') {
            return Promise.resolve(Notification.permission);
        }
        return Notification.requestPermission();
    }

    function init() {
        if (!window.EASWebSocket || typeof window.EASWebSocket.subscribe !== 'function') {
            return;
        }

        // Polling fallback hits /api/alerts (GeoJSON FeatureCollection) and
        // reshapes it into the `alerts_update` payload shape.  Only runs
        // when the websocket connection isn't available.
        const fallback = window.EASWebSocket.createPollingFallback(
            '/api/alerts',
            function (data) {
                if (!data) return;
                let alerts = [];
                if (Array.isArray(data)) {
                    alerts = data;
                } else if (Array.isArray(data.alerts)) {
                    alerts = data.alerts;
                } else if (Array.isArray(data.features)) {
                    alerts = data.features
                        .map(f => f && f.properties)
                        .filter(p => p && !p.is_expired);
                }
                handleAlertsUpdate({ alerts, count: alerts.length });
            },
        );

        window.EASWebSocket.subscribe('alerts_update', handleAlertsUpdate, {
            fallbackFn: fallback,
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // Defer slightly so EASWebSocket finishes its own bootstrap.
        setTimeout(init, 150);
    }

    window.EASAlertWatch = {
        enableNotifications,
        // exposed for debugging / future settings UI
        _handleAlertsUpdate: handleAlertsUpdate,
    };
})(window);
