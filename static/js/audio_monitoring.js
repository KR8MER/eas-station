/**
 * Audio Monitoring JavaScript
 * Handles real-time audio source monitoring, metrics display, and source management
 */

// Global state
let audioSources = [];
let metricsUpdateInterval = null;
let healthUpdateInterval = null;
let deviceMonitorInterval = null;
let lastDeviceList = [];

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

    // Start periodic updates (every 1 second for real-time monitoring)
    metricsUpdateInterval = setInterval(updateMetrics, 1000);
    healthUpdateInterval = setInterval(loadAudioHealth, 1000);
    // Monitor for device changes every 10 seconds
    deviceMonitorInterval = setInterval(monitorDeviceChanges, 10000);

    // Setup event listeners
    document.getElementById('sourceType')?.addEventListener('change', updateSourceTypeConfig);
}

/**
 * Monitor for audio device changes (hot-plug detection)
 */
async function monitorDeviceChanges() {
    try {
        const response = await fetch('/api/audio/devices');
        if (!response.ok) return;

        const data = await response.json();
        const currentDevices = data.devices || [];

        // Only check if we have a previous device list
        if (lastDeviceList.length > 0) {
            // Check for new devices
            const newDevices = currentDevices.filter(curr =>
                !lastDeviceList.some(prev => prev.device_id === curr.device_id && prev.type === curr.type)
            );

            // Check for removed devices
            const removedDevices = lastDeviceList.filter(prev =>
                !currentDevices.some(curr => curr.device_id === prev.device_id && curr.type === prev.type)
            );

            // Notify user of changes
            if (newDevices.length > 0) {
                console.info('New audio devices detected:', newDevices);
                newDevices.forEach(device => {
                    showSuccess(`New device detected: ${device.name}`);
                });
            }

            if (removedDevices.length > 0) {
                console.info('Audio devices removed:', removedDevices);
                removedDevices.forEach(device => {
                    showError(`Device disconnected: ${device.name}`);
                });
                // Refresh sources to update status
                loadAudioSources();
            }
        }

        // Update the last known device list
        lastDeviceList = currentDevices;
    } catch (error) {
        console.debug('Error monitoring device changes:', error);
    }
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
 * Sanitize ID for use in HTML element IDs and CSS selectors
 */
function sanitizeId(id) {
    // Replace characters that are problematic in CSS selectors and HTML IDs
    return id.replace(/[^a-zA-Z0-9_-]/g, '_');
}

/**
 * Create HTML for a source card
 */
function createSourceCard(source) {
    const statusClass = `status-${source.status}`;
    const statusBadge = getStatusBadge(source.status);
    const metrics = source.metrics || {};

    // Sanitize source ID for use in HTML element IDs
    const safeId = sanitizeId(source.id);

    // Escape source ID for safe use in JavaScript strings (onclick attributes)
    const escapedId = escapeHtml(source.id).replace(/'/g, "\\'").replace(/\\/g, '\\\\');

    return `
        <div class="source-card card mb-3 ${statusClass}" id="source-${safeId}">
            <div class="card-body">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h5 class="mb-1">${escapeHtml(source.name)}</h5>
                        <p class="mb-1">
                            <span class="badge bg-secondary">${escapeHtml(source.type.toUpperCase())}</span>
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
                                     id="peak-${safeId}"
                                     style="width: 0%">
                                    <span class="audio-meter-value" id="peak-value-${safeId}">-- dB</span>
                                </div>
                            </div>
                        </div>
                        <div>
                            <small class="text-muted d-block mb-1">RMS Level</small>
                            <div class="audio-meter">
                                <div class="audio-meter-bar rms"
                                     id="rms-${safeId}"
                                     style="width: 0%">
                                    <span class="audio-meter-value" id="rms-value-${safeId}">-- dB</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 text-end">
                        ${source.status === 'running'
                            ? `<button class="btn btn-sm btn-warning" onclick="stopSource('${escapedId}')">
                                <i class="fas fa-stop"></i> Stop
                               </button>`
                            : `<button class="btn btn-sm btn-success" onclick="startSource('${escapedId}')">
                                <i class="fas fa-play"></i> Start
                               </button>`
                        }
                        <button class="btn btn-sm btn-primary" onclick="editSource('${escapedId}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="deleteSource('${escapedId}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="row mt-3">
                    <div class="col-12">
                        <div class="d-flex justify-content-between align-items-center mb-1">
                            <small class="text-muted">
                                <i class="fas fa-wave-square"></i> Waveform Monitor
                                ${source.status === 'running' ? '<span class="text-success">● LIVE</span>' : '<span class="text-muted">○ Stopped</span>'}
                            </small>
                            <small class="text-muted">Data flowing: <span id="data-indicator-${safeId}">--</span></small>
                        </div>
                        <canvas id="waveform-${safeId}" class="waveform-canvas" width="800" height="120"></canvas>
                    </div>
                </div>
                ${metrics.silence_detected ? `
                <div class="alert alert-warning mt-3 mb-0 silence-warning">
                    <i class="fas fa-volume-mute"></i> Silence detected on this source
                </div>
                ` : ''}
                ${source.status === 'error' && source.error_message ? `
                <div class="alert alert-danger mt-3 mb-0">
                    <i class="fas fa-exclamation-triangle"></i> <strong>Error:</strong> ${escapeHtml(source.error_message)}
                </div>
                ` : ''}
                ${source.status === 'disconnected' ? `
                <div class="alert alert-warning mt-3 mb-0">
                    <i class="fas fa-plug-circle-xmark"></i> Disconnected - attempting to reconnect...
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
            // Update waveform for running sources
            if (audioSources.find(s => s.id === metric.source_id && s.status === 'running')) {
                updateWaveform(metric.source_id);
            }
        });
    } catch (error) {
        console.error('Error updating metrics:', error);
    }
}

/**
 * Update waveform display for a source
 */
async function updateWaveform(sourceId) {
    // Check if we should display waterfall spectrogram instead
    const useWaterfall = window.audioVisualizationMode === 'waterfall';

    if (useWaterfall) {
        try {
            const response = await fetch(`/api/audio/spectrogram/${encodeURIComponent(sourceId)}`);
            if (!response.ok) {
                console.warn(`Spectrogram fetch failed for ${sourceId}, status: ${response.status}`);
                // Fall back to waveform on error
                return await updateWaveformFallback(sourceId);
            }

            const data = await response.json();

            // Validate we have spectrogram data
            if (!data.spectrogram || data.spectrogram.length === 0) {
                console.warn(`No spectrogram data for ${sourceId}, falling back to waveform`);
                return await updateWaveformFallback(sourceId);
            }

            drawWaterfall(sourceId, data.spectrogram, data.sample_rate, data.fft_size);

            // Update data flow indicator
            const safeId = sanitizeId(sourceId);
            const indicator = document.getElementById(`data-indicator-${safeId}`);
            if (indicator) {
                const now = new Date();
                indicator.textContent = `${now.toLocaleTimeString()} (${data.frequency_bins} bins × ${data.time_frames} frames)`;
                indicator.className = 'text-success fw-bold';
            }
        } catch (error) {
            // Log error and fall back to waveform
            console.error('Error updating spectrogram for', sourceId, error);
            return await updateWaveformFallback(sourceId);
        }
    } else {
        try {
            const response = await fetch(`/api/audio/waveform/${encodeURIComponent(sourceId)}`);
            if (!response.ok) return;

            const data = await response.json();
            drawWaveform(sourceId, data.waveform);

            // Update data flow indicator
            const safeId = sanitizeId(sourceId);
            const indicator = document.getElementById(`data-indicator-${safeId}`);
            if (indicator) {
                const now = new Date();
                indicator.textContent = `${now.toLocaleTimeString()} (${data.sample_count} samples)`;
                indicator.className = 'text-success fw-bold';
            }
        } catch (error) {
            // Silently fail for individual waveform updates
            console.debug('Error updating waveform for', sourceId, error);
        }
    }
}

/**
 * Fallback to waveform display when spectrogram fails
 */
async function updateWaveformFallback(sourceId) {
    try {
        const response = await fetch(`/api/audio/waveform/${encodeURIComponent(sourceId)}`);
        if (!response.ok) return;

        const data = await response.json();
        drawWaveform(sourceId, data.waveform);

        // Update data flow indicator
        const safeId = sanitizeId(sourceId);
        const indicator = document.getElementById(`data-indicator-${safeId}`);
        if (indicator) {
            const now = new Date();
            indicator.textContent = `${now.toLocaleTimeString()} (${data.sample_count} samples) [waveform]`;
            indicator.className = 'text-warning fw-bold';
        }
    } catch (error) {
        console.debug('Error updating waveform fallback for', sourceId, error);
    }
}

/**
 * Draw waveform on canvas
 */
function drawWaveform(sourceId, waveformData) {
    const safeId = sanitizeId(sourceId);
    const canvas = document.getElementById(`waveform-${safeId}`);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;

    // Clear canvas
    ctx.fillStyle = '#1a1a1a';
    ctx.fillRect(0, 0, width, height);

    // Draw center line
    ctx.strokeStyle = '#444';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, centerY);
    ctx.lineTo(width, centerY);
    ctx.stroke();

    // Draw grid lines
    ctx.strokeStyle = '#2a2a2a';
    ctx.lineWidth = 0.5;
    for (let i = 1; i < 4; i++) {
        const y = (height / 4) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
    }

    if (!waveformData || waveformData.length === 0) return;

    // Draw waveform
    const step = width / waveformData.length;

    // Create gradient for waveform
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, '#00ff88');
    gradient.addColorStop(0.5, '#00cc66');
    gradient.addColorStop(1, '#00ff88');

    ctx.strokeStyle = gradient;
    ctx.lineWidth = 2;
    ctx.beginPath();

    for (let i = 0; i < waveformData.length; i++) {
        const x = i * step;
        // Clamp values to [-1, 1] range
        const sample = Math.max(-1, Math.min(1, waveformData[i]));
        const y = centerY - (sample * centerY * 0.9); // 0.9 for some padding

        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    }

    ctx.stroke();

    // Draw amplitude indicators
    ctx.fillStyle = '#888';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText('+1.0', width - 5, 12);
    ctx.fillText('0.0', width - 5, centerY + 4);
    ctx.fillText('-1.0', width - 5, height - 4);
}

/**
 * Draw waterfall spectrogram
 */
function drawWaterfall(sourceId, spectrogramData, sampleRate, fftSize) {
    const safeId = sanitizeId(sourceId);
    const canvas = document.getElementById(`waveform-${safeId}`);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    // Clear canvas
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, width, height);

    if (!spectrogramData || spectrogramData.length === 0) return;

    const timeFrames = spectrogramData.length;
    const freqBins = spectrogramData[0].length;

    // Draw spectrogram
    const pixelWidth = width / freqBins;
    const pixelHeight = height / timeFrames;

    // Color mapping function (hot colormap: black -> red -> yellow -> white)
    function getColor(value) {
        // value is 0-1
        const v = Math.max(0, Math.min(1, value));

        if (v < 0.25) {
            // Black to dark red
            const r = Math.floor(v * 4 * 128);
            return `rgb(${r}, 0, 0)`;
        } else if (v < 0.5) {
            // Dark red to red
            const r = 128 + Math.floor((v - 0.25) * 4 * 127);
            return `rgb(${r}, 0, 0)`;
        } else if (v < 0.75) {
            // Red to yellow
            const g = Math.floor((v - 0.5) * 4 * 255);
            return `rgb(255, ${g}, 0)`;
        } else {
            // Yellow to white
            const b = Math.floor((v - 0.75) * 4 * 255);
            return `rgb(255, 255, ${b})`;
        }
    }

    // Draw from oldest (top) to newest (bottom)
    for (let t = 0; t < timeFrames; t++) {
        const y = t * pixelHeight;
        for (let f = 0; f < freqBins; f++) {
            const x = f * pixelWidth;
            const value = spectrogramData[t][f];
            ctx.fillStyle = getColor(value);
            ctx.fillRect(x, y, Math.ceil(pixelWidth), Math.ceil(pixelHeight));
        }
    }

    // Draw frequency axis labels
    ctx.fillStyle = '#fff';
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';

    const nyquist = sampleRate / 2;
    const freqStep = nyquist / 4;

    for (let i = 0; i <= 4; i++) {
        const freq = (i * freqStep) / 1000; // Convert to kHz
        const x = (i / 4) * width;
        ctx.fillText(freq.toFixed(1) + ' kHz', x + 2, height - 4);
    }

    // Draw time indicator
    ctx.textAlign = 'right';
    ctx.fillText('Time ↓', width - 5, 12);
}

/**
 * Update a meter display
 */
function updateMeterDisplay(sourceId, type, levelDb) {
    const safeId = sanitizeId(sourceId);
    const bar = document.getElementById(`${type}-${safeId}`);
    const value = document.getElementById(`${type}-value-${safeId}`);

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

    // Set up the sourceType change listener (ensure it's set up every time modal opens)
    const sourceTypeSelect = document.getElementById('sourceType');
    if (sourceTypeSelect) {
        // Remove any existing listeners
        const newSourceTypeSelect = sourceTypeSelect.cloneNode(true);
        sourceTypeSelect.parentNode.replaceChild(newSourceTypeSelect, sourceTypeSelect);
        // Add fresh listener
        newSourceTypeSelect.addEventListener('change', updateSourceTypeConfig);
    }

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
                    <input type="url" class="form-control" id="streamUrl"
                           placeholder="https://stream.revma.ihrhls.com/zc####" required>
                    <small class="form-text text-muted">
                        <strong>Examples:</strong><br>
                        • iHeartRadio: https://stream.revma.ihrhls.com/zc####<br>
                        • Direct MP3: https://example.com/stream.mp3<br>
                        • M3U Playlist: https://example.com/playlist.m3u8<br>
                        Supports MP3, AAC, and OGG formats with automatic reconnection.
                    </small>
                </div>
                <div class="mb-3">
                    <label for="streamFormat" class="form-label">Stream Format</label>
                    <select class="form-select" id="streamFormat">
                        <option value="mp3" selected>MP3 (auto-detect)</option>
                        <option value="aac">AAC</option>
                        <option value="ogg">OGG Vorbis</option>
                        <option value="raw">Raw PCM</option>
                    </select>
                    <small class="form-text text-muted">Format will be auto-detected from HTTP Content-Type header</small>
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

    const requestBody = {
        type: sourceType,
        name: sourceName,
        sample_rate: sampleRate,
        channels: channels,
        silence_threshold_db: silenceThreshold,
        silence_duration_seconds: silenceDuration,
        device_params: deviceParams,
    };

    console.log('Creating audio source with config:', requestBody);

    try {
        const response = await fetch('/api/audio/sources', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        console.log('Response status:', response.status, response.statusText);

        if (response.ok) {
            bootstrap.Modal.getInstance(document.getElementById('addSourceModal')).hide();
            showSuccess('Audio source added successfully');
            loadAudioSources();
        } else {
            const error = await response.json().catch(() => ({ error: 'Unknown error - invalid JSON response' }));
            console.error('Server error response:', error);
            showError(`Failed to add source: ${error.error || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Error adding audio source:', error);
        showError(`Failed to add audio source: ${error.message || 'Network or connection error'}`);
    }
}

/**
 * Start an audio source
 */
async function startSource(sourceId) {
    try {
        const response = await fetch(`/api/audio/sources/${encodeURIComponent(sourceId)}/start`, {
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
        const response = await fetch(`/api/audio/sources/${encodeURIComponent(sourceId)}/stop`, {
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
        const response = await fetch(`/api/audio/sources/${encodeURIComponent(sourceId)}`, {
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
        const response = await fetch(`/api/audio/sources/${encodeURIComponent(sourceId)}`);
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

        const response = await fetch(`/api/audio/sources/${encodeURIComponent(sourceId)}`, {
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
    if (deviceMonitorInterval) clearInterval(deviceMonitorInterval);
});
