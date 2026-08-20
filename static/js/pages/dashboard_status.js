// Dashboard "System Status" strip: a lightweight, independently-refreshed
// summary of active alerts, EAS decoder state, app health and receiver
// count. Deliberately decoupled from the map's own alert/boundary fetch
// cycle (see index.html) so a slow or failing map load never blocks these
// tiles, and vice versa.

(function () {
    const REFRESH_INTERVAL_MS = 30 * 1000;

    function setBadge(elementId, text, variant) {
        const el = document.getElementById(elementId);
        if (!el) {
            return;
        }
        el.textContent = text;
        el.className = `status-badge ${variant}`;
    }

    function setText(elementId, text) {
        const el = document.getElementById(elementId);
        if (el) {
            el.textContent = text;
        }
    }

    async function fetchJson(url) {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`${url} responded with status ${response.status}`);
        }
        return response.json();
    }

    async function refreshAlertsTile() {
        try {
            const data = await fetchJson('/api/alerts');
            const count = Array.isArray(data.features) ? data.features.length : 0;
            setText('dash-stat-alerts-value', String(count));
        } catch (error) {
            console.error('Dashboard status: failed to load alerts', error);
            setText('dash-stat-alerts-value', '—');
        }
    }

    async function refreshMonitorTile() {
        try {
            const data = await fetchJson('/api/eas-monitor/status');
            if (data.running) {
                setBadge('dash-stat-monitor-badge', 'Running', 'success');
                setText('dash-stat-monitor-sub', data.audio_flowing ? 'Audio flowing' : 'Audio silent');
            } else {
                setBadge('dash-stat-monitor-badge', 'Stopped', 'danger');
                setText('dash-stat-monitor-sub', data.error || 'EAS Decoder');
            }
        } catch (error) {
            console.error('Dashboard status: failed to load EAS monitor status', error);
            setBadge('dash-stat-monitor-badge', 'Unknown', 'secondary');
            setText('dash-stat-monitor-sub', 'EAS Decoder');
        }
    }

    async function refreshHealthTile() {
        try {
            const data = await fetchJson('/health');
            const healthy = data.status === 'healthy';
            setBadge('dash-stat-health-badge', healthy ? 'Healthy' : 'Unhealthy', healthy ? 'success' : 'danger');
            setText('dash-stat-health-sub', data.database === 'connected' ? 'Database connected' : 'Database issue');
            setText('dash-stat-receivers-value', data.radio_receivers != null ? String(data.radio_receivers) : '--');
        } catch (error) {
            console.error('Dashboard status: failed to load health status', error);
            setBadge('dash-stat-health-badge', 'Unknown', 'secondary');
            setText('dash-stat-health-sub', 'System Health');
            setText('dash-stat-receivers-value', '--');
        }
    }

    async function refreshDashboardStatus() {
        await Promise.all([
            refreshAlertsTile(),
            refreshMonitorTile(),
            refreshHealthTile(),
        ]);

        const updatedEl = document.getElementById('dash-status-updated');
        if (updatedEl) {
            updatedEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
        }
    }

    if (document.getElementById('dash-status-updated')) {
        refreshDashboardStatus();
        setInterval(refreshDashboardStatus, REFRESH_INTERVAL_MS);
    }
})();
