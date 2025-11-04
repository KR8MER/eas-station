/**
 * Audio Monitoring and Management
 * Real-time audio source monitoring, metering, and control interface
 */

(() => {
    'use strict';

    // Configuration
    const API_BASE = '/api/audio';
    const METRICS_REFRESH_INTERVAL = 1000; // 1 second
    const SOURCES_REFRESH_INTERVAL = 5000; // 5 seconds
    const HEALTH_REFRESH_INTERVAL = 2000; // 2 seconds

    // State
    let sources = [];
    let metricsInterval = null;
    let sourcesInterval = null;
    let healthInterval = null;

    // DOM Elements
    const elements = {
        sourcesTable: document.getElementById('audioSourcesTable')?.querySelector('tbody'),
        addSourceBtn: document.getElementById('addSourceBtn'),
        refreshBtn: document.getElementById('refreshBtn'),
        discoverDevicesBtn: document.getElementById('discoverDevicesBtn'),
        lastUpdated: document.getElementById('lastUpdated'),
        statusBanner: document.getElementById('audioStatus'),

        // Health metrics
        healthScore: document.getElementById('healthScore'),
        activeSources: document.getElementById('activeSources'),
        totalSources: document.getElementById('totalSources'),
        uptime: document.getElementById('uptime'),
        silenceAlerts: document.getElementById('silenceAlerts'),

        // Modal
        modal: document.getElementById('audioSourceModal'),
        modalForm: document.getElementById('audioSourceForm'),
        modalTitle: document.getElementById('audioSourceModalLabel'),
    };

    // Utility functions
    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(value);
        return div.innerHTML;
    }

    function formatTime(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) return '—';

        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);

        if (hours > 0) {
            return `${hours}h ${minutes}m`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }

    function formatSampleRate(rate) {
        if (!Number.isFinite(rate)) return '—';
        return `${(rate / 1000).toFixed(1)} kHz`;
    }

    function formatLevel(db) {
        if (!Number.isFinite(db) || db === -Infinity) return '—';
        return `${db.toFixed(1)} dBFS`;
    }

    function setStatus(message, kind = 'info') {
        if (!elements.statusBanner) return;

        if (!message) {
            elements.statusBanner.classList.add('d-none');
            elements.statusBanner.textContent = '';
            return;
        }

        elements.statusBanner.className = `alert alert-${kind}`;
        elements.statusBanner.textContent = message;
        elements.statusBanner.classList.remove('d-none');

        setTimeout(() => setStatus(''), 6000);
    }

    function renderStatusBadge(status) {
        const statusMap = {
            'running': { class: 'bg-success', icon: 'fa-circle-check', text: 'Running' },
            'stopped': { class: 'bg-secondary', icon: 'fa-circle-stop', text: 'Stopped' },
            'starting': { class: 'bg-info', icon: 'fa-circle-play', text: 'Starting...' },
            'error': { class: 'bg-danger', icon: 'fa-circle-xmark', text: 'Error' },
            'disconnected': { class: 'bg-warning text-dark', icon: 'fa-circle-exclamation', text: 'Disconnected' }
        };

        const info = statusMap[status] || statusMap['stopped'];
        return `<span class="badge ${info.class}"><i class="fas ${info.icon}"></i> ${info.text}</span>`;
    }

    function renderMeteringBars(metrics) {
        if (!metrics) {
            return '<div class="text-muted small">No metrics</div>';
        }

        const peakPercent = dbToPercent(metrics.peak_level_db);
        const rmsPercent = dbToPercent(metrics.rms_level_db);

        const peakColor = getLevelColor(metrics.peak_level_db);
        const rmsColor = getLevelColor(metrics.rms_level_db);

        const silenceBadge = metrics.silence_detected
            ? '<span class="badge bg-warning text-dark ms-2"><i class="fas fa-volume-xmark"></i> Silence</span>'
            : '';

        return `
            <div class="audio-meters">
                <div class="meter-row mb-1">
                    <div class="meter-label small text-muted" style="width: 50px;">Peak:</div>
                    <div class="progress" style="height: 20px; flex: 1;">
                        <div class="progress-bar ${peakColor}" role="progressbar"
                             style="width: ${peakPercent}%"
                             aria-valuenow="${peakPercent}" aria-valuemin="0" aria-valuemax="100">
                            ${formatLevel(metrics.peak_level_db)}
                        </div>
                    </div>
                </div>
                <div class="meter-row">
                    <div class="meter-label small text-muted" style="width: 50px;">RMS:</div>
                    <div class="progress" style="height: 20px; flex: 1;">
                        <div class="progress-bar ${rmsColor}" role="progressbar"
                             style="width: ${rmsPercent}%"
                             aria-valuenow="${rmsPercent}" aria-valuemin="0" aria-valuemax="100">
                            ${formatLevel(metrics.rms_level_db)}
                        </div>
                    </div>
                </div>
                ${silenceBadge}
            </div>
        `;
    }

    function dbToPercent(db) {
        if (!Number.isFinite(db) || db === -Infinity) return 0;

        // Map -60 dBFS to 0%, 0 dBFS to 100%
        const normalized = (db + 60) / 60;
        return Math.max(0, Math.min(100, normalized * 100));
    }

    function getLevelColor(db) {
        if (!Number.isFinite(db) || db === -Infinity) return 'bg-secondary';

        if (db > -3) return 'bg-danger';        // Clipping risk
        if (db > -10) return 'bg-warning';      // High level
        if (db > -40) return 'bg-success';      // Normal level
        return 'bg-info';                        // Low level
    }

    // API functions
    async function fetchSources() {
        const response = await fetch(`${API_BASE}/sources`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        return data.sources || [];
    }

    async function fetchMetrics() {
        const response = await fetch(`${API_BASE}/metrics`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    }

    async function fetchHealth() {
        const response = await fetch(`${API_BASE}/health`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    }

    async function createSource(data) {
        const response = await fetch(`${API_BASE}/sources`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Failed to create source');
        return result;
    }

    async function startSource(name) {
        const response = await fetch(`${API_BASE}/sources/${encodeURIComponent(name)}/start`, {
            method: 'POST'
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Failed to start source');
        return result;
    }

    async function stopSource(name) {
        const response = await fetch(`${API_BASE}/sources/${encodeURIComponent(name)}/stop`, {
            method: 'POST'
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Failed to stop source');
        return result;
    }

    async function deleteSource(name) {
        const response = await fetch(`${API_BASE}/sources/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Failed to delete source');
        return result;
    }

    async function discoverDevices() {
        const response = await fetch(`${API_BASE}/devices`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    }

    // Rendering functions
    function renderSources() {
        if (!elements.sourcesTable) return;

        elements.sourcesTable.innerHTML = '';

        if (!sources.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 6;
            cell.className = 'text-center text-muted py-4';
            cell.innerHTML = '<i class="fas fa-inbox fa-2x mb-2"></i><br>No audio sources configured yet.';
            row.appendChild(cell);
            elements.sourcesTable.appendChild(row);
            return;
        }

        sources.forEach(source => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td class="fw-semibold">${escapeHtml(source.name)}</td>
                <td><span class="badge bg-light text-dark border">${escapeHtml(source.type)}</span></td>
                <td>${renderStatusBadge(source.status)}</td>
                <td class="text-end">${formatSampleRate(source.sample_rate)}</td>
                <td>${renderMeteringBars(source.metrics)}</td>
                <td class="text-end">
                    <div class="btn-group btn-group-sm" role="group">
                        ${source.status === 'running'
                            ? `<button class="btn btn-outline-warning" data-action="stop" data-name="${escapeHtml(source.name)}">
                                   <i class="fas fa-stop"></i>
                               </button>`
                            : `<button class="btn btn-outline-success" data-action="start" data-name="${escapeHtml(source.name)}">
                                   <i class="fas fa-play"></i>
                               </button>`
                        }
                        <button class="btn btn-outline-danger" data-action="delete" data-name="${escapeHtml(source.name)}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </td>
            `;
            elements.sourcesTable.appendChild(row);
        });

        if (elements.lastUpdated) {
            elements.lastUpdated.textContent = new Date().toLocaleTimeString();
        }
    }

    function updateHealthDisplay(health) {
        if (!health) return;

        if (elements.healthScore) {
            elements.healthScore.textContent = `${health.health_score}%`;
            elements.healthScore.className = `display-4 fw-bold ${getHealthColor(health.health_score)}`;
        }

        if (elements.activeSources) {
            elements.activeSources.textContent = health.active_sources || 0;
        }

        if (elements.totalSources) {
            elements.totalSources.textContent = `of ${health.total_sources || 0} total`;
        }

        if (elements.uptime) {
            elements.uptime.textContent = formatTime(health.uptime_seconds);
        }

        if (elements.silenceAlerts) {
            elements.silenceAlerts.textContent = health.silence_alerts || 0;
            elements.silenceAlerts.className = `display-4 fw-bold ${health.silence_alerts > 0 ? 'text-warning' : 'text-success'}`;
        }
    }

    function getHealthColor(score) {
        if (score >= 80) return 'text-success';
        if (score >= 50) return 'text-warning';
        return 'text-danger';
    }

    // Update functions
    async function updateMetrics() {
        try {
            const data = await fetchMetrics();

            // Update sources with new metrics
            if (data.metrics) {
                data.metrics.forEach(metric => {
                    const source = sources.find(s => s.name === metric.source_name);
                    if (source) {
                        source.metrics = metric;
                        source.status = metric.status;
                    }
                });
                renderSources();
            }
        } catch (error) {
            console.error('Failed to update metrics:', error);
        }
    }

    async function updateSources() {
        try {
            sources = await fetchSources();
            renderSources();
        } catch (error) {
            console.error('Failed to update sources:', error);
            setStatus('Failed to load audio sources', 'danger');
        }
    }

    async function updateHealth() {
        try {
            const health = await fetchHealth();
            updateHealthDisplay(health);
        } catch (error) {
            console.error('Failed to update health:', error);
        }
    }

    // Event handlers
    async function handleSourceAction(action, name) {
        try {
            switch (action) {
                case 'start':
                    await startSource(name);
                    setStatus(`Started audio source: ${name}`, 'success');
                    break;
                case 'stop':
                    await stopSource(name);
                    setStatus(`Stopped audio source: ${name}`, 'info');
                    break;
                case 'delete':
                    if (!confirm(`Delete audio source "${name}"?`)) return;
                    await deleteSource(name);
                    setStatus(`Deleted audio source: ${name}`, 'success');
                    break;
            }
            await updateSources();
            await updateHealth();
        } catch (error) {
            console.error(`Failed to ${action} source:`, error);
            setStatus(error.message, 'danger');
        }
    }

    function openAddSourceModal() {
        if (!elements.modalForm || !elements.modal) return;

        elements.modalForm.reset();
        elements.modalTitle.textContent = 'Add Audio Source';

        const modal = bootstrap.Modal.getOrCreateInstance(elements.modal);
        modal.show();
    }

    async function handleFormSubmit(event) {
        event.preventDefault();

        const formData = new FormData(elements.modalForm);
        const data = {
            name: formData.get('display_name'),
            type: formData.get('type'),
            sample_rate: parseInt(formData.get('sample_rate')),
            channels: parseInt(formData.get('channels')),
            priority: parseInt(formData.get('priority')),
            silence_threshold_db: parseFloat(formData.get('silence_threshold_db')),
            enabled: formData.get('enabled') !== null,
            auto_start: formData.get('auto_start') !== null,
            device_params: {}
        };

        // Add device-specific parameters based on type
        if (data.type === 'alsa') {
            data.device_params.device_name = formData.get('device_name') || 'default';
        } else if (data.type === 'pulse') {
            data.device_params.device_index = formData.get('device_index') ? parseInt(formData.get('device_index')) : null;
        } else if (data.type === 'sdr') {
            data.device_params.receiver_id = formData.get('receiver_id');
        } else if (data.type === 'file') {
            data.device_params.file_path = formData.get('file_path');
            data.device_params.loop = formData.get('loop') !== null;
        }

        try {
            await createSource(data);
            setStatus(`Audio source "${data.name}" created successfully`, 'success');

            const modal = bootstrap.Modal.getInstance(elements.modal);
            modal.hide();

            await updateSources();
            await updateHealth();
        } catch (error) {
            console.error('Failed to create source:', error);
            setStatus(error.message, 'danger');
        }
    }

    async function handleDiscoverDevices() {
        const modalElement = document.getElementById('discoveryModal');
        const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
        const modalBody = document.getElementById('discoveryModalBody');

        modalBody.innerHTML = `
            <div class="text-center py-4">
                <div class="spinner-border text-primary" role="status"></div>
                <p class="mt-3">Discovering audio devices...</p>
            </div>
        `;
        modal.show();

        try {
            const data = await discoverDevices();

            if (!data.devices || data.devices.length === 0) {
                modalBody.innerHTML = `
                    <div class="alert alert-warning">
                        <h6><i class="fas fa-exclamation-triangle"></i> No Devices Found</h6>
                        <p class="mb-0">No audio input devices were detected.</p>
                    </div>
                `;
                return;
            }

            let html = `<div class="alert alert-success"><i class="fas fa-check-circle"></i> Found ${data.devices.length} device(s)</div>`;

            data.devices.forEach((device, idx) => {
                html += `
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <strong><i class="fas fa-microphone"></i> ${escapeHtml(device.name)}</strong>
                            <button class="btn btn-sm btn-primary" onclick="useDiscoveredDevice(${idx})">
                                <i class="fas fa-plus"></i> Use This Device
                            </button>
                        </div>
                        <div class="card-body">
                            <dl class="row mb-0">
                                <dt class="col-sm-3">Type</dt>
                                <dd class="col-sm-9"><code>${escapeHtml(device.type)}</code></dd>
                                <dt class="col-sm-3">Device ID</dt>
                                <dd class="col-sm-9"><code>${escapeHtml(device.device_id)}</code></dd>
                                <dt class="col-sm-3">Description</dt>
                                <dd class="col-sm-9">${escapeHtml(device.description)}</dd>
                            </dl>
                        </div>
                    </div>
                `;
            });

            modalBody.innerHTML = html;
            window.discoveredAudioDevices = data.devices;

        } catch (error) {
            console.error('Device discovery failed:', error);
            modalBody.innerHTML = `
                <div class="alert alert-danger">
                    <h6><i class="fas fa-times-circle"></i> Discovery Failed</h6>
                    <p class="mb-0">${escapeHtml(error.message)}</p>
                </div>
            `;
        }
    }

    // Global function for discovered device selection
    window.useDiscoveredDevice = (deviceIndex) => {
        const device = window.discoveredAudioDevices?.[deviceIndex];
        if (!device) return;

        const discoveryModal = bootstrap.Modal.getInstance(document.getElementById('discoveryModal'));
        if (discoveryModal) discoveryModal.hide();

        // Pre-fill form
        document.getElementById('sourceDisplayName').value = device.name;
        document.getElementById('sourceType').value = device.type;

        openAddSourceModal();
    };

    // Initialize
    function init() {
        // Event listeners
        if (elements.addSourceBtn) {
            elements.addSourceBtn.addEventListener('click', openAddSourceModal);
        }

        if (elements.refreshBtn) {
            elements.refreshBtn.addEventListener('click', async () => {
                await updateSources();
                await updateHealth();
                setStatus('Refreshed audio sources', 'info');
            });
        }

        if (elements.discoverDevicesBtn) {
            elements.discoverDevicesBtn.addEventListener('click', handleDiscoverDevices);
        }

        if (elements.modalForm) {
            elements.modalForm.addEventListener('submit', handleFormSubmit);
        }

        if (elements.sourcesTable) {
            elements.sourcesTable.addEventListener('click', (event) => {
                const button = event.target.closest('button[data-action]');
                if (!button) return;

                const action = button.getAttribute('data-action');
                const name = button.getAttribute('data-name');
                handleSourceAction(action, name);
            });
        }

        // Handle visibility changes to pause/resume updates
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                stopAutoRefresh();
            } else {
                updateSources();
                updateHealth();
                startAutoRefresh();
            }
        });

        // Initial load
        updateSources();
        updateHealth();
        startAutoRefresh();
    }

    function startAutoRefresh() {
        stopAutoRefresh();
        metricsInterval = setInterval(updateMetrics, METRICS_REFRESH_INTERVAL);
        sourcesInterval = setInterval(updateSources, SOURCES_REFRESH_INTERVAL);
        healthInterval = setInterval(updateHealth, HEALTH_REFRESH_INTERVAL);
    }

    function stopAutoRefresh() {
        if (metricsInterval) clearInterval(metricsInterval);
        if (sourcesInterval) clearInterval(sourcesInterval);
        if (healthInterval) clearInterval(healthInterval);
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
