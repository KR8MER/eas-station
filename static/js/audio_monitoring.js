/**
 * Audio Monitoring JavaScript
 * Handles real-time audio source monitoring, metrics display, and source management
 */

// Global state
let audioSources = [];
let metricsUpdateInterval = null;
let healthUpdateInterval = null;

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeAudioMonitoring();
});

/**
 * Initialize audio monitoring system
 */
function initializeAudioMonitoring() {
    // Load initial data
    loadAudioSources();
    loadAudioHealth();
    loadAudioAlerts();

    // Start periodic updates (every 1 second)
    metricsUpdateInterval = setInterval(updateMetrics, 1000);
    healthUpdateInterval = setInterval(loadAudioHealth, 5000);

    // Setup event listeners
    document.getElementById('sourceType')?.addEventListener('change', updateSourceTypeConfig);
}

/**
 * Load all audio sources
 */
async function loadAudioSources() {
    try {
        const response = await fetch('/api/audio/sources');
        const data = await response.json();

        audioSources = data.sources || [];
        renderAudioSources();

        // Update counts
        document.getElementById('active-sources-count').textContent = data.active_count || 0;
        document.getElementById('total-sources-count').textContent = data.total || 0;
    } catch (error) {
        console.error('Error loading audio sources:', error);
        showError('Failed to load audio sources');
    }
}

/**
 * Render audio sources list
 */
function renderAudioSources() {
    const container = document.getElementById('sources-list');

    if (audioSources.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-5">
                <i class="fas fa-microphone-slash fa-3x mb-3"></i>
                <p>No audio sources configured.</p>
                <button class="btn btn-primary" onclick="showAddSourceModal()">
                    <i class="fas fa-plus"></i> Add Your First Source
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = audioSources.map(source => createSourceCard(source)).join('');
}

/**
 * Create HTML for a source card
 */
function createSourceCard(source) {
    const statusClass = `status-${source.status}`;
    const statusBadge = getStatusBadge(source.status);
    const metrics = source.metrics || {};

    return `
        <div class="source-card card mb-3 ${statusClass}" id="source-${source.id}">
            <div class="card-body">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h5 class="mb-1">${escapeHtml(source.name)}</h5>
                        <p class="mb-1">
                            <span class="badge bg-secondary">${source.type.toUpperCase()}</span>
                            ${statusBadge}
                        </p>
                        <small class="text-muted">
                            ${source.config.sample_rate} Hz • ${source.config.channels} ch
                        </small>
                    </div>
                    <div class="col-md-5">
                        <div class="mb-2">
                            <small class="text-muted d-block mb-1">Peak Level</small>
                            <div class="audio-meter">
                                <div class="audio-meter-bar peak"
                                     id="peak-${source.id}"
                                     style="width: 0%">
                                    <span class="audio-meter-value" id="peak-value-${source.id}">-- dB</span>
                                </div>
                            </div>
                        </div>
                        <div>
                            <small class="text-muted d-block mb-1">RMS Level</small>
                            <div class="audio-meter">
                                <div class="audio-meter-bar rms"
                                     id="rms-${source.id}"
                                     style="width: 0%">
                                    <span class="audio-meter-value" id="rms-value-${source.id}">-- dB</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 text-end">
                        ${source.status === 'running'
                            ? `<button class="btn btn-sm btn-warning" onclick="stopSource('${source.id}')">
                                <i class="fas fa-stop"></i> Stop
                               </button>`
                            : `<button class="btn btn-sm btn-success" onclick="startSource('${source.id}')">
                                <i class="fas fa-play"></i> Start
                               </button>`
                        }
                        <button class="btn btn-sm btn-primary" onclick="editSource('${source.id}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="deleteSource('${source.id}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                ${metrics.silence_detected ? `
                <div class="alert alert-warning mt-3 mb-0 silence-warning">
                    <i class="fas fa-volume-mute"></i> Silence detected on this source
                </div>
                ` : ''}
            </div>
        </div>
    `;
}

/**
 * Get status badge HTML
 */
function getStatusBadge(status) {
    const badges = {
        running: '<span class="status-badge bg-success"><span class="status-dot"></span> Running</span>',
        stopped: '<span class="status-badge bg-secondary"><span class="status-dot"></span> Stopped</span>',
        starting: '<span class="status-badge bg-warning"><span class="status-dot"></span> Starting</span>',
        error: '<span class="status-badge bg-danger"><span class="status-dot"></span> Error</span>',
        disconnected: '<span class="status-badge bg-danger"><span class="status-dot"></span> Disconnected</span>',
    };
    return badges[status] || badges.stopped;
}

/**
 * Update real-time metrics
 */
async function updateMetrics() {
    try {
        const response = await fetch('/api/audio/metrics');
        const data = await response.json();

        const liveMetrics = data.live_metrics || [];

        liveMetrics.forEach(metric => {
            updateMeterDisplay(metric.source_id, 'peak', metric.peak_level_db);
            updateMeterDisplay(metric.source_id, 'rms', metric.rms_level_db);
        });
    } catch (error) {
        console.error('Error updating metrics:', error);
    }
}

/**
 * Update a meter display
 */
function updateMeterDisplay(sourceId, type, levelDb) {
    const bar = document.getElementById(`${type}-${sourceId}`);
    const value = document.getElementById(`${type}-value-${sourceId}`);

    if (!bar || !value) return;

    // Convert dB to percentage (assuming -60dB to 0dB range)
    const percentage = Math.max(0, Math.min(100, ((levelDb + 60) / 60) * 100));

    bar.style.width = `${percentage}%`;
    value.textContent = `${levelDb.toFixed(1)} dB`;
}

/**
 * Load audio health status
 */
async function loadAudioHealth() {
    try {
        const response = await fetch('/api/audio/health');
        const data = await response.json();

        const healthScore = Math.round(data.overall_health_score || 0);
        document.getElementById('overall-health-score').textContent = healthScore;

        // Update health circle
        const circle = document.getElementById('overall-health-circle');
        circle.style.setProperty('--score', healthScore);

        // Change color based on health
        let color = '#28a745'; // green
        if (healthScore < 50) color = '#dc3545'; // red
        else if (healthScore < 80) color = '#ffc107'; // yellow

        circle.style.background = `conic-gradient(${color} 0deg, ${color} ${healthScore * 3.6}deg, #e9ecef ${healthScore * 3.6}deg)`;
    } catch (error) {
        console.error('Error loading health status:', error);
    }
}

/**
 * Load audio alerts
 */
async function loadAudioAlerts() {
    try {
        const response = await fetch('/api/audio/alerts?unresolved_only=true');
        const data = await response.json();

        const alerts = data.alerts || [];
        document.getElementById('alerts-count').textContent = data.unresolved_count || 0;

        const container = document.getElementById('alerts-list');

        if (alerts.length === 0) {
            container.innerHTML = '<p class="text-muted">No recent alerts.</p>';
            return;
        }

        container.innerHTML = alerts.slice(0, 10).map(alert => `
            <div class="alert alert-${getAlertClass(alert.alert_level)} mb-2">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>${escapeHtml(alert.source_name)}</strong>: ${escapeHtml(alert.message)}
                        <br>
                        <small class="text-muted">${formatTimestamp(alert.created_at)}</small>
                    </div>
                    <div>
                        ${!alert.acknowledged ? `
                        <button class="btn btn-sm btn-outline-secondary" onclick="acknowledgeAlert(${alert.id})">
                            Acknowledge
                        </button>
                        ` : ''}
                        <button class="btn btn-sm btn-success" onclick="resolveAlert(${alert.id})">
                            Resolve
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading alerts:', error);
    }
}

/**
 * Get Bootstrap alert class from alert level
 */
function getAlertClass(level) {
    const classes = {
        critical: 'danger',
        error: 'danger',
        warning: 'warning',
        info: 'info',
    };
    return classes[level] || 'info';
}

/**
 * Show add source modal
 */
function showAddSourceModal() {
    const modal = new bootstrap.Modal(document.getElementById('addSourceModal'));
    document.getElementById('addSourceForm').reset();
    document.getElementById('sourceTypeConfig').innerHTML = '';
    modal.show();
}

/**
 * Update source type specific configuration
 */
function updateSourceTypeConfig() {
    const sourceType = document.getElementById('sourceType').value;
    const container = document.getElementById('sourceTypeConfig');

    let html = '';

    switch (sourceType) {
        case 'sdr':
            html = `
                <div class="mb-3">
                    <label for="receiverId" class="form-label">Receiver ID <span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="receiverId" placeholder="e.g., rtl_sdr_0" required>
                    <small class="form-text text-muted">Must match a configured SDR receiver</small>
                </div>
            `;
            break;
        case 'stream':
            html = `
                <div class="mb-3">
                    <label for="streamUrl" class="form-label">Stream URL <span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="streamUrl" placeholder="https://example.com/stream.m3u or https://example.com/live.mp3" required>
                    <small class="form-text text-muted">HTTP/HTTPS URL to M3U playlist or direct audio stream (MP3, AAC, OGG)</small>
                </div>
                <div class="mb-3">
                    <label for="streamFormat" class="form-label">Stream Format</label>
                    <select class="form-select" id="streamFormat">
                        <option value="mp3" selected>MP3 (auto-detect)</option>
                        <option value="aac">AAC</option>
                        <option value="ogg">OGG Vorbis</option>
                        <option value="raw">Raw PCM</option>
                    </select>
                    <small class="form-text text-muted">Format will be auto-detected from Content-Type if possible</small>
                </div>
            `;
            break;
        case 'alsa':
            html = `
                <div class="mb-3">
                    <label for="deviceName" class="form-label">ALSA Device Name</label>
                    <input type="text" class="form-control" id="deviceName" placeholder="e.g., default, hw:0,0" value="default">
                    <small class="form-text text-muted">Leave as "default" to use system default device</small>
                </div>
            `;
            break;
        case 'pulse':
            html = `
                <div class="mb-3">
                    <label for="deviceIndex" class="form-label">PulseAudio Device Index (optional)</label>
                    <input type="number" class="form-control" id="deviceIndex" placeholder="Leave blank for default">
                    <small class="form-text text-muted">Optional: Specific device index from PulseAudio</small>
                </div>
            `;
            break;
        case 'file':
            html = `
                <div class="mb-3">
                    <label for="filePath" class="form-label">Audio File Path <span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="filePath" placeholder="/path/to/audio.wav" required>
                    <small class="form-text text-muted">Absolute path to WAV or MP3 file</small>
                </div>
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="loop" checked>
                        <label class="form-check-label" for="loop">
                            Loop playback continuously
                        </label>
                    </div>
                </div>
            `;
            break;
    }

    container.innerHTML = html;
}

/**
 * Add a new audio source
 */
async function addAudioSource() {
    const sourceType = document.getElementById('sourceType').value;
    const sourceName = document.getElementById('sourceName').value;
    const sampleRate = parseInt(document.getElementById('sampleRate').value);
    const channels = parseInt(document.getElementById('channels').value);
    const silenceThreshold = parseFloat(document.getElementById('silenceThreshold').value);
    const silenceDuration = parseFloat(document.getElementById('silenceDuration').value);

    if (!sourceType || !sourceName) {
        showError('Please fill in all required fields');
        return;
    }

    const deviceParams = {};

    // Get source-specific parameters and validate required fields
    switch (sourceType) {
        case 'sdr':
            const receiverId = document.getElementById('receiverId')?.value;
            if (!receiverId) {
                showError('Receiver ID is required for SDR sources');
                return;
            }
            deviceParams.receiver_id = receiverId;
            break;
        case 'stream':
            const streamUrl = document.getElementById('streamUrl')?.value;
            const streamFormat = document.getElementById('streamFormat')?.value;
            if (!streamUrl) {
                showError('Stream URL is required for stream sources');
                return;
            }
            deviceParams.stream_url = streamUrl;
            if (streamFormat && streamFormat !== 'mp3') {
                deviceParams.format = streamFormat;
            }
            break;
        case 'alsa':
            const deviceName = document.getElementById('deviceName')?.value || 'default';
            deviceParams.device_name = deviceName;
            break;
        case 'pulse':
            const deviceIndex = document.getElementById('deviceIndex')?.value;
            if (deviceIndex) {
                deviceParams.device_index = parseInt(deviceIndex);
            }
            break;
        case 'file':
            const filePath = document.getElementById('filePath')?.value;
            const loop = document.getElementById('loop')?.checked;
            if (!filePath) {
                showError('File path is required for file sources');
                return;
            }
            deviceParams.file_path = filePath;
            deviceParams.loop = loop;
            break;
    }

    try {
        const response = await fetch('/api/audio/sources', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                type: sourceType,
                name: sourceName,
                sample_rate: sampleRate,
                channels: channels,
                silence_threshold_db: silenceThreshold,
                silence_duration_seconds: silenceDuration,
                device_params: deviceParams,
            }),
        });

        if (response.ok) {
            bootstrap.Modal.getInstance(document.getElementById('addSourceModal')).hide();
            showSuccess('Audio source added successfully');
            loadAudioSources();
        } else {
            const error = await response.json();
            showError(`Failed to add source: ${error.error}`);
        }
    } catch (error) {
        console.error('Error adding audio source:', error);
        showError('Failed to add audio source');
    }
}

/**
 * Start an audio source
 */
async function startSource(sourceId) {
    try {
        const response = await fetch(`/api/audio/sources/${sourceId}/start`, {
            method: 'POST',
        });

        if (response.ok) {
            showSuccess('Audio source started');
            loadAudioSources();
        } else {
            const error = await response.json();
            showError(`Failed to start source: ${error.error}`);
        }
    } catch (error) {
        console.error('Error starting source:', error);
        showError('Failed to start audio source');
    }
}

/**
 * Stop an audio source
 */
async function stopSource(sourceId) {
    try {
        const response = await fetch(`/api/audio/sources/${sourceId}/stop`, {
            method: 'POST',
        });

        if (response.ok) {
            showSuccess('Audio source stopped');
            loadAudioSources();
        } else {
            const error = await response.json();
            showError(`Failed to stop source: ${error.error}`);
        }
    } catch (error) {
        console.error('Error stopping source:', error);
        showError('Failed to stop audio source');
    }
}

/**
 * Delete an audio source
 */
async function deleteSource(sourceId) {
    if (!confirm('Are you sure you want to delete this audio source?')) {
        return;
    }

    try {
        const response = await fetch(`/api/audio/sources/${sourceId}`, {
            method: 'DELETE',
        });

        if (response.ok) {
            showSuccess('Audio source deleted');
            loadAudioSources();
        } else {
            const error = await response.json();
            showError(`Failed to delete source: ${error.error}`);
        }
    } catch (error) {
        console.error('Error deleting source:', error);
        showError('Failed to delete audio source');
    }
}

/**
 * Edit an audio source
 */
async function editSource(sourceId) {
    try {
        // Fetch current source configuration
        const response = await fetch(`/api/audio/sources/${sourceId}`);
        if (!response.ok) {
            showError('Failed to load source configuration');
            return;
        }

        const source = await response.json();

        // Populate the edit modal
        document.getElementById('editSourceId').value = source.id;
        document.getElementById('editSourceName').value = source.name;
        document.getElementById('editSourceType').value = source.type.toUpperCase();
        document.getElementById('editPriority').value = source.priority || 100;
        document.getElementById('editEnabled').checked = source.enabled !== false;

        // Set silence detection values from config
        const config = source.config || {};
        document.getElementById('editSilenceThreshold').value = config.silence_threshold_db || -60;
        document.getElementById('editSilenceDuration').value = config.silence_duration_seconds || 5;

        // Set database-only fields
        document.getElementById('editAutoStart').checked = source.auto_start || false;
        document.getElementById('editDescription').value = source.description || '';

        // Show the modal
        const modal = new bootstrap.Modal(document.getElementById('editSourceModal'));
        modal.show();
    } catch (error) {
        console.error('Error loading source for edit:', error);
        showError('Failed to load source configuration');
    }
}

/**
 * Save edited audio source configuration
 */
async function saveEditedSource() {
    try {
        const sourceId = document.getElementById('editSourceId').value;

        const updates = {
            enabled: document.getElementById('editEnabled').checked,
            priority: parseInt(document.getElementById('editPriority').value),
            silence_threshold_db: parseFloat(document.getElementById('editSilenceThreshold').value),
            silence_duration_seconds: parseFloat(document.getElementById('editSilenceDuration').value),
            auto_start: document.getElementById('editAutoStart').checked,
            description: document.getElementById('editDescription').value,
        };

        const response = await fetch(`/api/audio/sources/${sourceId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(updates),
        });

        if (response.ok) {
            bootstrap.Modal.getInstance(document.getElementById('editSourceModal')).hide();
            showSuccess('Audio source updated successfully');
            loadAudioSources();
        } else {
            const error = await response.json();
            showError(`Failed to update source: ${error.error}`);
        }
    } catch (error) {
        console.error('Error updating source:', error);
        showError('Failed to update audio source');
    }
}

/**
 * Discover audio devices
 */
async function discoverDevices() {
    const modal = new bootstrap.Modal(document.getElementById('deviceDiscoveryModal'));
    modal.show();

    try {
        const response = await fetch('/api/audio/devices');
        const data = await response.json();

        const container = document.getElementById('discoveredDevices');
        const devices = data.devices || [];

        if (devices.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="fas fa-search fa-3x mb-3"></i>
                    <p>No audio devices found.</p>
                    <p class="small">Make sure ALSA or PulseAudio is installed and configured.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="list-group">
                ${devices.map(device => `
                    <div class="list-group-item">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <h6 class="mb-1">${escapeHtml(device.name)}</h6>
                                <p class="mb-0 text-muted small">${escapeHtml(device.description)}</p>
                                ${device.sample_rate ? `<small class="text-muted">${device.sample_rate} Hz • ${device.max_channels} channels</small>` : ''}
                            </div>
                            <button class="btn btn-sm btn-primary" onclick="quickAddDevice('${device.type}', '${escapeHtml(device.device_id)}', '${escapeHtml(device.name)}')">
                                <i class="fas fa-plus"></i> Add
                            </button>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        console.error('Error discovering devices:', error);
        document.getElementById('discoveredDevices').innerHTML = `
            <div class="alert alert-danger">
                Failed to discover devices: ${error.message}
            </div>
        `;
    }
}

/**
 * Quick add a discovered device
 */
function quickAddDevice(type, deviceId, deviceName) {
    // Close discovery modal
    bootstrap.Modal.getInstance(document.getElementById('deviceDiscoveryModal')).hide();

    // Open add source modal with pre-filled values
    showAddSourceModal();

    document.getElementById('sourceType').value = type;
    document.getElementById('sourceName').value = deviceName;
    updateSourceTypeConfig();

    // Set device-specific fields
    setTimeout(() => {
        if (type === 'alsa') {
            document.getElementById('deviceName').value = deviceId;
        } else if (type === 'pulse') {
            document.getElementById('deviceIndex').value = deviceId;
        }
    }, 100);
}

/**
 * Acknowledge an alert
 */
async function acknowledgeAlert(alertId) {
    try {
        const response = await fetch(`/api/audio/alerts/${alertId}/acknowledge`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                acknowledged_by: 'web_user',
            }),
        });

        if (response.ok) {
            showSuccess('Alert acknowledged');
            loadAudioAlerts();
        } else {
            const error = await response.json();
            showError(`Failed to acknowledge alert: ${error.error}`);
        }
    } catch (error) {
        console.error('Error acknowledging alert:', error);
        showError('Failed to acknowledge alert');
    }
}

/**
 * Resolve an alert
 */
async function resolveAlert(alertId) {
    try {
        const response = await fetch(`/api/audio/alerts/${alertId}/resolve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                resolved_by: 'web_user',
                resolution_notes: 'Resolved via web interface',
            }),
        });

        if (response.ok) {
            showSuccess('Alert resolved');
            loadAudioAlerts();
        } else {
            const error = await response.json();
            showError(`Failed to resolve alert: ${error.error}`);
        }
    } catch (error) {
        console.error('Error resolving alert:', error);
        showError('Failed to resolve alert');
    }
}

/**
 * Show success toast notification
 */
function showSuccess(message) {
    showToast(message, 'success');
}

/**
 * Show error toast notification
 */
function showError(message) {
    showToast(message, 'danger');
}

/**
 * Show a toast notification
 */
function showToast(message, type = 'info') {
    const container = document.querySelector('.toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible fade show`;
    toast.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 150);
    }, 5000);
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format timestamp for display
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return 'Unknown';
    const date = new Date(timestamp);
    return date.toLocaleString();
}

/**
 * Cleanup on page unload
 */
window.addEventListener('beforeunload', function() {
    if (metricsUpdateInterval) clearInterval(metricsUpdateInterval);
    if (healthUpdateInterval) clearInterval(healthUpdateInterval);
});
