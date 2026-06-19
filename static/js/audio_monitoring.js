/**
 * Audio Monitoring JavaScript
 * Handles real-time audio source monitoring, metrics display, and source management
 *
 * Uses WebSocket for real-time updates with automatic fallback to polling.
 */

// Global state
let audioSources = [];
let metricsUpdateInterval = null;
let waveformUpdateInterval = null;
let healthUpdateInterval = null;
let deviceMonitorInterval = null;
let lastDeviceList = [];
const lastMetricTimestamps = {};
let anonymousIdCounter = 0;
const DEFAULT_LEVEL_DB = -120;

// WebSocket subscription handles
let wsMetricsUnsubscribe = null;
let wsHealthUnsubscribe = null;
let wsSourcesUnsubscribe = null;

/**
 * Utility: Safely close a Bootstrap modal by removing focus first
 * Prevents aria-hidden accessibility warnings
 */
function safeCloseModal(modalId) {
    // Remove focus from any active element to prevent aria-hidden issues
    if (document.activeElement) {
        document.activeElement.blur();
    }
    const modalElement = document.getElementById(modalId);
    const modalInstance = bootstrap.Modal.getInstance(modalElement);
    if (modalInstance) {
        modalInstance.hide();
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeAudioMonitoring();
});

/**
 * Initialize audio monitoring system
 * Uses WebSocket with automatic fallback to polling
 */
function initializeAudioMonitoring() {
    // Load initial data
    loadAudioSources();
    loadAudioHealth();
    loadAudioAlerts();

    // Perform an immediate metrics refresh so VU meters populate without delay
    updateMetrics();
    // Initial waveform update
    updateWaveforms();

    // Setup event listeners
    document.getElementById('sourceType')?.addEventListener('change', updateSourceTypeConfig);

    // Subscribe to WebSocket updates if available
    if (window.EASWebSocket) {
        // Audio metrics (VU meters) - real-time via WebSocket
        wsMetricsUnsubscribe = window.EASWebSocket.subscribe(
            'audio_monitoring_update',
            handleAudioMetricsUpdate,
            {
                fallbackFn: updateMetrics,
                fallbackInterval: 2000  // 2s polling fallback
            }
        );

        // Audio health - slower updates
        wsHealthUnsubscribe = window.EASWebSocket.subscribe(
            'audio_health_update',
            handleAudioHealthUpdate,
            {
                fallbackFn: loadAudioHealth,
                fallbackInterval: 30000  // 30s polling fallback
            }
        );

        // Audio sources list
        wsSourcesUnsubscribe = window.EASWebSocket.subscribe(
            'audio_sources_update',
            handleAudioSourcesUpdate,
            {
                fallbackFn: loadAudioSources,
                fallbackInterval: 30000  // 30s polling fallback
            }
        );

        // Waveforms still need polling (not included in WebSocket yet)
        waveformUpdateInterval = setInterval(updateWaveforms, 10000);

        // Device monitoring still needs polling
        deviceMonitorInterval = setInterval(monitorDeviceChanges, 60000);
    } else {
        // Fallback to polling if WebSocket module not available
        metricsUpdateInterval = setInterval(updateMetrics, 2000);
        waveformUpdateInterval = setInterval(updateWaveforms, 10000);
        healthUpdateInterval = setInterval(loadAudioHealth, 30000);
        deviceMonitorInterval = setInterval(monitorDeviceChanges, 60000);
    }
}

/**
 * Handle WebSocket audio metrics update (VU meters)
 */
function handleAudioMetricsUpdate(data) {
    try {
        const snapshot = data?.audio_metrics || data;
        const liveMetrics = snapshot?.live_metrics || [];

        updateBackendStatusIndicator(snapshot?.broadcast_stats, snapshot?.active_source);

        if (!Array.isArray(liveMetrics) || liveMetrics.length === 0) {
            showMetricsWarning('No live audio metrics received — check audio service/Redis');
            refreshMetricTimestampIndicators();
            return;
        }

        const hasRealMetrics = liveMetrics.some(metric => hasMeaningfulLevels(metric));
        if (!hasRealMetrics) {
            const hasRunningSources = liveMetrics.some(
                metric => metric.source_status === 'running'
            );
            if (hasRunningSources) {
                showMetricsWarning('Sources running but no audio detected — check stream URLs and audio levels');
            } else {
                showMetricsWarning('No live audio metrics received — check audio service/Redis');
            }
        } else {
            hideMetricsWarning();
        }

        liveMetrics.forEach(metric => {
            if (!hasUsableId(metric?.source_id)) return;

            if (hasMeaningfulLevels(metric)) {
                const parsedTimestamp = parseMetricTimestamp(metric.timestamp) || new Date();
                lastMetricTimestamps[metric.source_id] = parsedTimestamp;
            }

            updateMeterDisplay(metric.source_id, 'peak', metric.peak_level_db);
            updateMeterDisplay(metric.source_id, 'rms', metric.rms_level_db);
            renderMetricTimestamp(metric.source_id);
        });

        refreshMetricTimestampIndicators();
    } catch (error) {
        console.error('Error processing WebSocket audio metrics:', error);
    }
}

/**
 * Handle WebSocket audio health update
 */
function handleAudioHealthUpdate(data) {
    try {
        const healthScore = Math.round(data.overall_health_score || 0);
        const scoreElement = document.getElementById('overall-health-score');
        if (scoreElement) {
            scoreElement.textContent = healthScore;
        }

        // Update health circle
        const circle = document.getElementById('overall-health-circle');
        if (circle) {
            circle.style.setProperty('--score', healthScore);

            let color = '#28a745'; // green
            if (healthScore < 50) color = '#dc3545'; // red
            else if (healthScore < 80) color = '#ffc107'; // yellow

            circle.style.background = `conic-gradient(${color} 0deg, ${color} ${healthScore * 3.6}deg, #e9ecef ${healthScore * 3.6}deg)`;
        }
    } catch (error) {
        console.error('Error processing WebSocket audio health:', error);
    }
}

/**
 * Handle WebSocket audio sources update
 */
function handleAudioSourcesUpdate(data) {
    try {
        const sources = data.sources || [];
        // Preserve existing runtime status when the update omits it (Redis unavailable)
        const existingStatusMap = new Map(audioSources.map(s => [s.name, s.status]));
        audioSources = sources.filter(source => hasUsableId(source?.id || source?.name)).map(source => {
            if (!source.status && existingStatusMap.has(source.name)) {
                return { ...source, status: existingStatusMap.get(source.name) };
            }
            return source;
        });
        renderAudioSources();

        // Update counts
        const activeCount = document.getElementById('active-sources-count');
        const totalCount = document.getElementById('total-sources-count');
        if (activeCount) activeCount.textContent = data.active_count || 0;
        if (totalCount) totalCount.textContent = data.total || 0;
    } catch (error) {
        console.error('Error processing WebSocket audio sources:', error);
    }
}

// Simple debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Monitor for audio device changes (hot-plug detection)
 */
async function monitorDeviceChanges() {
    try {
        const fetchFunc = window.cachedFetch || fetch;
        const response = await fetchFunc('/api/audio/devices');
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
        const fetchFunc = window.cachedFetch || fetch;
        const response = await fetchFunc('/api/audio/sources');
        const data = await response.json();

        audioSources = (data.sources || []).filter(source => {
            const hasId = hasUsableId(source?.id);
            if (!hasId) {
                console.warn('Skipping audio source with missing id', source);
            }
            return hasId;
        });
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
    if (!container) return;

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
function hasUsableId(id) {
    return id !== undefined && id !== null && String(id).trim() !== '';
}

function sanitizeId(id) {
    if (id === undefined || id === null) {
        anonymousIdCounter += 1;
        return `unknown-${anonymousIdCounter}`;
    }

    const rawId = String(id);
    if (rawId.trim() === '') {
        anonymousIdCounter += 1;
        return `unknown-${anonymousIdCounter}`;
    }

    // Replace characters that are problematic in CSS selectors and HTML IDs
    return rawId.replace(/[^a-zA-Z0-9_-]/g, '_');
}

/**
 * Create HTML for a source card
 */
function createSourceCard(source) {
    const statusClass = `status-${source.status || 'unknown'}`;
    const statusBadge = getStatusBadge(source.status);
    const metrics = source.metrics || {};
    const config = source.config || {};

    // Sanitize source ID for use in HTML element IDs
    const safeId = sanitizeId(source.id);

    // Escape source ID for safe use in JavaScript strings (onclick attributes)
    const escapedId = escapeHtml(source.id).replace(/'/g, "\\'").replace(/\\/g, '\\\\');

    // Get config values with defaults
    const sampleRate = config.sample_rate || metrics.sample_rate || '?';
    const channels = config.channels || metrics.channels || '?';

    // Get source type with fallback
    const sourceType = (source.type || 'unknown').toUpperCase();
    const sourceName = source.name || 'Unnamed Source';

    return `
        <div class="source-card card mb-3 ${statusClass}" id="source-${safeId}">
            <div class="card-body">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h5 class="mb-1">${escapeHtml(sourceName)}</h5>
                        <p class="mb-1">
                            <span class="badge bg-secondary">${escapeHtml(sourceType)}</span>
                            ${statusBadge}
                        </p>
                        <small class="text-muted">
                            ${sampleRate} Hz • ${channels} ch
                        </small>
                    </div>
                    <div class="col-md-5">
                        <div class="mb-2">
                            <small class="text-muted d-block mb-1" id="peak-label-${safeId}">Peak: -- dBFS</small>
                            <div class="audio-meter">
                                <div class="audio-meter-bar peak"
                                     id="peak-meter-${safeId}"
                                     style="width: 0%">
                                </div>
                            </div>
                        </div>
                        <div>
                            <small class="text-muted d-block mb-1" id="rms-label-${safeId}">RMS: -- dBFS</small>
                            <div class="audio-meter">
                                <div class="audio-meter-bar rms"
                                     id="rms-meter-${safeId}"
                                     style="width: 0%">
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
                            <small class="text-muted d-flex flex-wrap gap-2 justify-content-end">
                                <span>Data flowing: <span id="data-indicator-${safeId}">--</span></span>
                                <span id="metric-timestamp-${safeId}">Last metric: --</span>
                            </small>
                        </div>
                        <canvas id="waveform-${safeId}" class="waveform-canvas" width="800" height="120"></canvas>
                    </div>
                </div>
                ${source.status === 'running' ? `
                <div class="row mt-3">
                    <div class="col-12">
                        <div class="audio-player-container">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <small class="text-muted">
                                    <i class="fas fa-volume-up"></i> Audio Stream
                                </small>
                                ${source.icecast_url ? `
                                <small class="text-muted">
                                    <i class="fas fa-broadcast-tower"></i> Icecast Stream
                                    ${source.streaming && source.streaming.icecast ? `
                                        ${typeof source.streaming.icecast.bitrate_kbps === 'number' ? ` • ${Number(source.streaming.icecast.bitrate_kbps).toFixed(1)} kbps` : ''}
                                    ` : ''}
                                </small>
                                ` : ''}
                            </div>
                            <audio
                                controls
                                preload="none"
                                class="w-100"
                                id="audio-player-${safeId}"
                                style="height: 40px;">
                                ${source.icecast_url ? `<source src="${escapeHtml(source.icecast_url)}" type="audio/mpeg">` : ''}
                                <source src="/api/audio/stream/${encodeURIComponent(source.name)}" type="audio/wav">
                                Your browser does not support the audio element.
                            </audio>
                            ${source.icecast_url ? `
                            <small class="text-muted d-block mt-1">
                                <i class="fas fa-info-circle"></i> Stream URL: <a href="${escapeHtml(source.icecast_url)}" target="_blank" class="text-decoration-none">${escapeHtml(source.icecast_url)}</a>
                            </small>
                            ` : `
                            <small class="text-muted d-block mt-1">
                                <i class="fas fa-info-circle"></i> Using built-in proxy stream
                                ${metrics.metadata && metrics.metadata.stereo_enabled ? `
                                    <span class="badge bg-success ms-2" title="Stereo audio with 19 kHz pilot tone">
                                        <i class="fas fa-circle-dot"></i> STEREO
                                    </span>
                                ` : ''}
                                ${metrics.sample_rate ? `
                                    <span class="badge bg-info ms-2" title="Audio sample rate">
                                        ${(metrics.sample_rate / 1000).toFixed(1)} kHz
                                    </span>
                                ` : ''}
                                ${metrics.metadata && metrics.metadata.receiver_modulation ? `
                                    <span class="badge bg-secondary ms-2" title="FM modulation type">
                                        ${escapeHtml(metrics.metadata.receiver_modulation)}
                                    </span>
                                ` : ''}
                            </small>
                            `}
                        </div>
                    </div>
                </div>
                ` : ''}
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
        unknown: '<span class="status-badge bg-secondary" style="opacity:0.6"><span class="status-dot"></span> Unknown</span>',
    };
    return badges[status] || badges.unknown;
}

function updateBackendStatusIndicator(broadcastStats = {}, activeSource = null) {
    const indicator = document.getElementById('backend-status-indicator');
    if (!indicator) return;

    const isActive = Boolean(broadcastStats.active);
    const sourceLabel = activeSource || broadcastStats.active_source;

    indicator.className = `badge ${isActive ? 'bg-success' : 'bg-danger'} px-3 py-2`;
    indicator.textContent = isActive
        ? `Backend active${sourceLabel ? ` • ${sourceLabel}` : ''}`
        : 'Backend inactive — no data broadcasting';
}

function showMetricsWarning(message) {
    const banner = document.getElementById('metrics-warning-banner');
    const text = document.getElementById('metrics-warning-text');
    if (!banner || !text) return;

    text.textContent = message;
    banner.classList.remove('d-none');
}

function hideMetricsWarning() {
    const banner = document.getElementById('metrics-warning-banner');
    if (!banner) return;

    banner.classList.add('d-none');
}

function hasMeaningfulLevels(metric) {
    if (!metric) return false;
    const peak = Number(metric.peak_level_db);
    const rms = Number(metric.rms_level_db);

    const peakValid = Number.isFinite(peak) && peak > DEFAULT_LEVEL_DB;
    const rmsValid = Number.isFinite(rms) && rms > DEFAULT_LEVEL_DB;

    return peakValid || rmsValid;
}

function parseMetricTimestamp(timestamp) {
    if (timestamp === undefined || timestamp === null) return null;

    if (typeof timestamp === 'number') {
        const tsMs = timestamp > 1e12 ? timestamp : timestamp * 1000;
        const parsed = new Date(tsMs);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    const parsed = new Date(timestamp);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function renderMetricTimestamp(sourceId) {
    if (!hasUsableId(sourceId)) return;

    const safeId = sanitizeId(sourceId);
    const target = document.getElementById(`metric-timestamp-${safeId}`);
    if (!target) return;

    const ts = lastMetricTimestamps[sourceId];
    if (!ts) {
        target.textContent = 'Last metric: --';
        target.className = 'text-muted';
        return;
    }

    const ageSeconds = Math.max(0, Math.round((Date.now() - ts.getTime()) / 1000));
    target.textContent = `Last metric: ${ts.toLocaleTimeString()} (${ageSeconds}s ago)`;

    let className = 'text-success';
    if (ageSeconds > 120) className = 'text-danger fw-bold';
    else if (ageSeconds > 60) className = 'text-warning fw-bold';

    target.className = className;
}

function refreshMetricTimestampIndicators() {
    if (!Array.isArray(audioSources)) return;
    audioSources.forEach(source => {
        if (!hasUsableId(source?.id)) return;
        renderMetricTimestamp(source.id);
    });
}

/**
 * Update real-time metrics
 */
async function updateMetrics() {
    try {
        const fetchFunc = window.cachedFetch || fetch;
        const response = await fetchFunc('/api/audio/metrics', { cache: 'no-store' });

        if (!response.ok) {
            console.warn('Metrics request failed', response.status);
            return;
        }

        const data = await response.json();

        // API returns metrics at the top level while WebSocket wraps them
        const snapshot = data?.audio_metrics || data;
        const liveMetrics = snapshot?.live_metrics || [];
        updateBackendStatusIndicator(snapshot?.broadcast_stats, snapshot?.active_source);

        if (!Array.isArray(liveMetrics)) {
            console.debug('No live metrics found in snapshot', snapshot);
            showMetricsWarning('No live audio metrics received — check audio service/Redis');
            refreshMetricTimestampIndicators();
            return;
        }

        if (liveMetrics.length === 0) {
            showMetricsWarning('No live audio metrics received — check audio service/Redis');
            refreshMetricTimestampIndicators();
            return;
        }

        const hasRealMetrics = liveMetrics.some(metric => hasMeaningfulLevels(metric));
        if (!hasRealMetrics) {
            const hasRunningSources = liveMetrics.some(
                metric => metric.source_status === 'running'
            );
            if (hasRunningSources) {
                showMetricsWarning('Sources running but no audio detected — check stream URLs and audio levels');
            } else {
                showMetricsWarning('No live audio metrics received — check audio service/Redis');
            }
        } else {
            hideMetricsWarning();
        }

        liveMetrics.forEach(metric => {
            if (!hasUsableId(metric?.source_id)) {
                console.warn('Skipping metric with missing source_id', metric);
                return;
            }

            if (hasMeaningfulLevels(metric)) {
                const parsedTimestamp = parseMetricTimestamp(metric.timestamp) || new Date();
                lastMetricTimestamps[metric.source_id] = parsedTimestamp;
            }

            updateMeterDisplay(metric.source_id, 'peak', metric.peak_level_db);
            updateMeterDisplay(metric.source_id, 'rms', metric.rms_level_db);
            renderMetricTimestamp(metric.source_id);
        });

        refreshMetricTimestampIndicators();
    } catch (error) {
        console.error('Error updating metrics:', error);
    }
}

/**
 * Update waveforms for all running sources (called less frequently than metrics)
 */
function updateWaveforms() {
    audioSources.forEach(source => {
        if (source.status === 'running') {
            updateWaveform(source.id);
        }
    });
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
                // No spectrogram data available yet - show waiting message
                const safeId = sanitizeId(sourceId);
                const indicator = document.getElementById(`data-indicator-${safeId}`);
                if (indicator) {
                    indicator.textContent = 'Waiting for spectrogram data...';
                    indicator.className = 'text-muted';
                }
                return;
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
            
            // Check if we have valid waveform data
            if (data.waveform && data.waveform.length > 0) {
                drawWaveform(sourceId, data.waveform);

                // Update data flow indicator
                const safeId = sanitizeId(sourceId);
                const indicator = document.getElementById(`data-indicator-${safeId}`);
                if (indicator) {
                    const now = new Date();
                    indicator.textContent = `${now.toLocaleTimeString()} (${data.sample_count} samples)`;
                    indicator.className = 'text-success fw-bold';
                }
            } else {
                // No waveform data available yet - source may be starting
                const safeId = sanitizeId(sourceId);
                const indicator = document.getElementById(`data-indicator-${safeId}`);
                if (indicator) {
                    indicator.textContent = 'Waiting for data...';
                    indicator.className = 'text-muted';
                }
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
        
        // Check if we have valid waveform data
        if (data.waveform && data.waveform.length > 0) {
            drawWaveform(sourceId, data.waveform);

            // Update data flow indicator
            const safeId = sanitizeId(sourceId);
            const indicator = document.getElementById(`data-indicator-${safeId}`);
            if (indicator) {
                const now = new Date();
                indicator.textContent = `${now.toLocaleTimeString()} (${data.sample_count} samples) [waveform]`;
                indicator.className = 'text-warning fw-bold';
            }
        } else {
            // No waveform data available yet
            const safeId = sanitizeId(sourceId);
            const indicator = document.getElementById(`data-indicator-${safeId}`);
            if (indicator) {
                indicator.textContent = 'Waiting for data...';
                indicator.className = 'text-muted';
            }
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
 * Update a meter display (fallback when Web Audio API is not available)
 * When Web Audio API is working, realtime-vu-meters.js handles updates at 60Hz
 */
function updateMeterDisplay(sourceId, type, levelDb) {
    const safeId = sanitizeId(sourceId);
    const bar = document.getElementById(`${type}-meter-${safeId}`);
    const label = document.getElementById(`${type}-label-${safeId}`);

    if (!bar) return;

    const safeLevel = Number.isFinite(levelDb) ? levelDb : DEFAULT_LEVEL_DB;

    // Convert dB to percentage (assuming -60dB to 0dB range)
    const percentage = Math.max(0, Math.min(100, ((safeLevel + 60) / 60) * 100));

    bar.style.width = `${percentage}%`;
    
    // Update label if it exists (fallback for when Web Audio API is not available)
    if (label && !label.textContent.includes('dBFS')) {
        // Only update if not already being updated by realtime VU meters (which use dBFS format)
        label.textContent = `${type === 'peak' ? 'Peak' : 'RMS'}: ${safeLevel.toFixed(1)} dB`;
    }
}

/**
 * Load audio health status
 */
async function loadAudioHealth() {
    try {
        const fetchFunc = window.cachedFetch || fetch;
        const response = await fetchFunc('/api/audio/health');
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
        const fetchFunc = window.cachedFetch || fetch;
        const response = await fetchFunc('/api/audio/alerts?unresolved_only=true');
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
    const modalEl = document.getElementById('addSourceModal');
    const formEl = document.getElementById('addSourceForm');
    const configEl = document.getElementById('sourceTypeConfig');

    if (!modalEl || !formEl || !configEl) {
        console.error('Required modal elements not found in DOM');
        showError('Modal configuration error - please refresh the page');
        return;
    }

    const modal = new bootstrap.Modal(modalEl);
    formEl.reset();
    configEl.innerHTML = '';

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
    const sourceTypeEl = document.getElementById('sourceType');
    const container = document.getElementById('sourceTypeConfig');

    if (!sourceTypeEl || !container) {
        console.error('Required form elements not found');
        return;
    }

    const sourceType = sourceTypeEl.value;

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
                    <div class="input-group">
                        <input type="url" class="form-control" id="streamUrl"
                               placeholder="https://stream.revma.ihrhls.com/zc####" required>
                        <button class="btn btn-outline-secondary" type="button"
                                onclick="testStreamUrl('streamUrl', 'streamTestResult')">
                            <i class="fas fa-plug"></i> Test
                        </button>
                    </div>
                    <div id="streamTestResult" class="mt-2"></div>
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
                <div class="mb-3">
                    <label class="form-label">Authentication <span class="text-muted">(optional)</span></label>
                    <div class="row g-2">
                        <div class="col-sm-6">
                            <input type="text" class="form-control" id="streamAuthUsername"
                                   placeholder="Username" autocomplete="off">
                        </div>
                        <div class="col-sm-6">
                            <input type="password" class="form-control" id="streamAuthPassword"
                                   placeholder="Password" autocomplete="new-password">
                        </div>
                    </div>
                    <input type="text" class="form-control mt-2" id="streamAuthHeader"
                           placeholder="Or a raw Authorization value, e.g. Bearer &lt;token&gt;" autocomplete="off">
                    <small class="form-text text-muted">
                        For protected streams. Username/password use HTTP Basic auth; the raw value
                        (if set) is sent as the <code>Authorization</code> header and takes precedence.
                    </small>
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
    // Sample rate omitted - backend defaults to 44100 Hz for ALSA/PulseAudio, auto-detected by FFmpeg for streams
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
            deviceParams.url = streamUrl;
            if (streamFormat && streamFormat !== 'mp3') {
                deviceParams.format = streamFormat;
            }
            const authUsername = document.getElementById('streamAuthUsername')?.value?.trim();
            const authPassword = document.getElementById('streamAuthPassword')?.value;
            const authHeader = document.getElementById('streamAuthHeader')?.value?.trim();
            if (authUsername) deviceParams.auth_username = authUsername;
            if (authPassword) deviceParams.auth_password = authPassword;
            if (authHeader) deviceParams.auth_header = authHeader;
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
        // sample_rate omitted - backend defaults to 44100 Hz for ALSA/PulseAudio, auto-detected by FFmpeg for streams
        channels: channels,
        silence_threshold_db: silenceThreshold,
        silence_duration_seconds: silenceDuration,
        device_params: deviceParams,
        auto_start: document.getElementById('autoStart')?.checked || false,
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
            safeCloseModal('addSourceModal');
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
 * Preflight-test a stream URL (with any entered credentials) and show the result.
 * Surfaces authentication-required streams (HTTP 401/403) with a clear message
 * instead of letting them fail silently after the source is added.
 *
 * @param {string} urlInputId  ID of the URL <input> ('streamUrl' or 'editStreamUrl')
 * @param {string} resultElId  ID of the element to render the result into
 */
async function testStreamUrl(urlInputId, resultElId) {
    const urlEl = document.getElementById(urlInputId);
    const resultEl = document.getElementById(resultElId);
    const url = urlEl?.value?.trim();
    if (!resultEl) return;

    if (!url) {
        resultEl.innerHTML = '<div class="alert alert-warning py-2 mb-0">Enter a stream URL first.</div>';
        return;
    }

    // Auth field IDs differ between the add form and the edit form.
    const editing = urlInputId === 'editStreamUrl';
    const prefix = editing ? 'editStream' : 'stream';
    const authUsername = document.getElementById(`${prefix}AuthUsername`)?.value?.trim() || '';
    const authPassword = document.getElementById(`${prefix}AuthPassword`)?.value || '';
    const authHeader = document.getElementById(`${prefix}AuthHeader`)?.value?.trim() || '';

    resultEl.innerHTML = '<div class="text-muted py-1"><i class="fas fa-spinner fa-spin"></i> Testing stream…</div>';

    try {
        const response = await fetch('/api/audio/sources/test-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url,
                auth_username: authUsername,
                auth_password: authPassword,
                auth_header: authHeader,
            }),
        });
        const result = await response.json().catch(() => ({ ok: false, message: 'Invalid response from server.' }));

        if (result.ok) {
            const ct = result.content_type ? ` <span class="text-muted">(${escapeHtml(result.content_type)})</span>` : '';
            resultEl.innerHTML = `<div class="alert alert-success py-2 mb-0">
                <i class="fas fa-check-circle"></i> ${escapeHtml(result.message)}${ct}</div>`;
        } else {
            resultEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">
                <i class="fas fa-exclamation-triangle"></i> ${escapeHtml(result.message || 'Stream test failed.')}</div>`;
        }
    } catch (error) {
        resultEl.innerHTML = `<div class="alert alert-danger py-2 mb-0">
            <i class="fas fa-exclamation-triangle"></i> ${escapeHtml(error.message || 'Network error while testing stream.')}</div>`;
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
 * Update edit source type specific configuration
 */
function updateEditSourceTypeConfig(sourceType, deviceParams) {
    const container = document.getElementById('editSourceTypeConfig');
    
    // Defensive check: if container doesn't exist, log error and return
    if (!container) {
        console.error('editSourceTypeConfig element not found in DOM');
        return;
    }

    let html = '';

    switch (sourceType) {
        case 'stream':
            const streamUrl = deviceParams?.url || '';
            const streamFormat = deviceParams?.format || 'mp3';
            const editAuthUsername = deviceParams?.auth_username || '';
            const editAuthHeader = deviceParams?.auth_header || '';
            const hasStoredPassword = !!(deviceParams?.auth_password_set || deviceParams?.auth_password);
            html = `
                <div class="mb-3">
                    <label for="editStreamUrl" class="form-label">Stream URL <span class="text-danger">*</span></label>
                    <div class="input-group">
                        <input type="url" class="form-control" id="editStreamUrl"
                               value="${escapeHtml(streamUrl)}"
                               placeholder="https://stream.revma.ihrhls.com/zc####" required>
                        <button class="btn btn-outline-secondary" type="button"
                                onclick="testStreamUrl('editStreamUrl', 'editStreamTestResult')">
                            <i class="fas fa-plug"></i> Test
                        </button>
                    </div>
                    <div id="editStreamTestResult" class="mt-2"></div>
                    <small class="form-text text-muted">
                        <strong>Examples:</strong><br>
                        • iHeartRadio: https://stream.revma.ihrhls.com/zc####<br>
                        • Direct MP3: https://example.com/stream.mp3<br>
                        • M3U Playlist: https://example.com/playlist.m3u8<br>
                        Supports MP3, AAC, and OGG formats with automatic reconnection.
                    </small>
                </div>
                <div class="mb-3">
                    <label for="editStreamFormat" class="form-label">Stream Format</label>
                    <select class="form-select" id="editStreamFormat">
                        <option value="mp3" ${streamFormat === 'mp3' ? 'selected' : ''}>MP3 (auto-detect)</option>
                        <option value="aac" ${streamFormat === 'aac' ? 'selected' : ''}>AAC</option>
                        <option value="ogg" ${streamFormat === 'ogg' ? 'selected' : ''}>OGG Vorbis</option>
                        <option value="raw" ${streamFormat === 'raw' ? 'selected' : ''}>Raw PCM</option>
                    </select>
                    <small class="form-text text-muted">Format will be auto-detected from HTTP Content-Type header</small>
                </div>
                <div class="mb-3">
                    <label class="form-label">Authentication <span class="text-muted">(optional)</span></label>
                    <div class="row g-2">
                        <div class="col-sm-6">
                            <input type="text" class="form-control" id="editStreamAuthUsername"
                                   value="${escapeHtml(editAuthUsername)}" placeholder="Username" autocomplete="off">
                        </div>
                        <div class="col-sm-6">
                            <input type="password" class="form-control" id="editStreamAuthPassword"
                                   placeholder="${hasStoredPassword ? 'Leave blank to keep current' : 'Password'}" autocomplete="new-password">
                        </div>
                    </div>
                    <input type="text" class="form-control mt-2" id="editStreamAuthHeader"
                           value="${escapeHtml(editAuthHeader)}"
                           placeholder="Or a raw Authorization value, e.g. Bearer &lt;token&gt;" autocomplete="off">
                    <small class="form-text text-muted">
                        For protected streams. Username/password use HTTP Basic auth; the raw value
                        (if set) is sent as the <code>Authorization</code> header and takes precedence.
                    </small>
                </div>
            `;
            break;
        case 'alsa':
            const deviceName = deviceParams?.device_name || 'default';
            html = `
                <div class="mb-3">
                    <label for="editDeviceName" class="form-label">ALSA Device Name</label>
                    <input type="text" class="form-control" id="editDeviceName"
                           value="${escapeHtml(deviceName)}"
                           placeholder="e.g., default, hw:0,0">
                    <small class="form-text text-muted">Leave as "default" to use system default device</small>
                </div>
            `;
            break;
        case 'pulse':
            const deviceIndex = deviceParams?.device_index || '';
            html = `
                <div class="mb-3">
                    <label for="editDeviceIndex" class="form-label">PulseAudio Device Index (optional)</label>
                    <input type="number" class="form-control" id="editDeviceIndex"
                           value="${deviceIndex}"
                           placeholder="Leave blank for default">
                    <small class="form-text text-muted">Optional: Specific device index from PulseAudio</small>
                </div>
            `;
            break;
        case 'file':
            const filePath = deviceParams?.file_path || '';
            const loop = deviceParams?.loop !== false;
            html = `
                <div class="mb-3">
                    <label for="editFilePath" class="form-label">Audio File Path <span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="editFilePath"
                           value="${escapeHtml(filePath)}"
                           placeholder="/path/to/audio.wav" required>
                    <small class="form-text text-muted">Absolute path to WAV or MP3 file</small>
                </div>
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="editLoop" ${loop ? 'checked' : ''}>
                        <label class="form-check-label" for="editLoop">
                            Loop playback continuously
                        </label>
                    </div>
                </div>
            `;
            break;
        case 'sdr':
            const receiverId = deviceParams?.receiver_id || '';
            html = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i> SDR sources are managed through the Radio Settings page.
                    This source is linked to receiver: <strong>${escapeHtml(receiverId)}</strong>
                </div>
            `;
            break;
    }

    container.innerHTML = html;
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

        // Check for required modal elements
        const modalEl = document.getElementById('editSourceModal');
        if (!modalEl) {
            console.error('Edit modal element not found');
            showError('Modal configuration error - please refresh the page');
            return;
        }

        // Populate the edit modal (with null checks)
        const idEl = document.getElementById('editSourceId');
        const nameEl = document.getElementById('editSourceName');
        const typeEl = document.getElementById('editSourceType');
        const priorityEl = document.getElementById('editPriority');
        const enabledEl = document.getElementById('editEnabled');

        if (idEl) idEl.value = source.id;
        if (nameEl) nameEl.value = source.name;
        if (typeEl) typeEl.value = (source.type || 'unknown').toUpperCase();
        if (priorityEl) priorityEl.value = source.priority || 100;
        if (enabledEl) enabledEl.checked = source.enabled !== false;

        // Set silence detection values from config
        const config = source.config || {};
        const thresholdEl = document.getElementById('editSilenceThreshold');
        const durationEl = document.getElementById('editSilenceDuration');
        if (thresholdEl) thresholdEl.value = config.silence_threshold_db || -60;
        if (durationEl) durationEl.value = config.silence_duration_seconds || 5;

        // Set database-only fields
        const autoStartEl = document.getElementById('editAutoStart');
        const descEl = document.getElementById('editDescription');
        if (autoStartEl) autoStartEl.checked = source.auto_start || false;
        if (descEl) descEl.value = source.description || '';

        // Populate type-specific configuration
        updateEditSourceTypeConfig(source.type, config.device_params || {});

        // Show the modal
        const modal = new bootstrap.Modal(modalEl);
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
        const sourceType = document.getElementById('editSourceType').value.toLowerCase();

        const updates = {
            enabled: document.getElementById('editEnabled').checked,
            priority: parseInt(document.getElementById('editPriority').value),
            silence_threshold_db: parseFloat(document.getElementById('editSilenceThreshold').value),
            silence_duration_seconds: parseFloat(document.getElementById('editSilenceDuration').value),
            auto_start: document.getElementById('editAutoStart').checked,
            description: document.getElementById('editDescription').value,
        };

        // Collect device-specific parameters
        const deviceParams = {};
        let hasDeviceParams = false;

        switch (sourceType) {
            case 'stream':
                const streamUrl = document.getElementById('editStreamUrl')?.value;
                const streamFormat = document.getElementById('editStreamFormat')?.value;
                if (!streamUrl) {
                    showError('Stream URL is required');
                    return;
                }
                deviceParams.url = streamUrl;
                if (streamFormat && streamFormat !== 'mp3') {
                    deviceParams.format = streamFormat;
                }
                // Auth fields are merged server-side; always send username/header so
                // they can be updated or cleared. Only send the password when the
                // user typed one (blank keeps the stored credential).
                deviceParams.auth_username = document.getElementById('editStreamAuthUsername')?.value?.trim() || '';
                deviceParams.auth_header = document.getElementById('editStreamAuthHeader')?.value?.trim() || '';
                const editPassword = document.getElementById('editStreamAuthPassword')?.value;
                if (editPassword) {
                    deviceParams.auth_password = editPassword;
                }
                hasDeviceParams = true;
                break;
            case 'alsa':
                const deviceName = document.getElementById('editDeviceName')?.value;
                if (deviceName) {
                    deviceParams.device_name = deviceName;
                    hasDeviceParams = true;
                }
                break;
            case 'pulse':
                const deviceIndex = document.getElementById('editDeviceIndex')?.value;
                if (deviceIndex) {
                    deviceParams.device_index = parseInt(deviceIndex);
                    hasDeviceParams = true;
                }
                break;
            case 'file':
                const filePath = document.getElementById('editFilePath')?.value;
                const loop = document.getElementById('editLoop')?.checked;
                if (!filePath) {
                    showError('File path is required');
                    return;
                }
                deviceParams.file_path = filePath;
                deviceParams.loop = loop;
                hasDeviceParams = true;
                break;
        }

        // Add device params to updates if present
        if (hasDeviceParams) {
            updates.device_params = deviceParams;
        }

        const response = await fetch(`/api/audio/sources/${encodeURIComponent(sourceId)}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(updates),
        });

        if (response.ok) {
            safeCloseModal('editSourceModal');
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
    const modalEl = document.getElementById('deviceDiscoveryModal');
    if (!modalEl) {
        console.error('Device discovery modal element not found');
        showError('Modal configuration error - please refresh the page');
        return;
    }
    const modal = new bootstrap.Modal(modalEl);
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
    safeCloseModal('deviceDiscoveryModal');

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
 * Resolve every outstanding (unresolved) audio alert at once.
 *
 * Silence/health alerts can pile up into the tens of thousands, so this gives
 * operators a single "Clear All" action instead of resolving them one-by-one.
 */
async function resolveAllAlerts() {
    const countEl = document.getElementById('alerts-count');
    const current = countEl ? parseInt(countEl.textContent, 10) : 0;
    if (!current) {
        showToast('No unresolved alerts to clear', 'info');
        return;
    }

    if (!confirm(`Clear all ${current.toLocaleString()} unresolved alert(s)? This marks them resolved and cannot be undone.`)) {
        return;
    }

    const btn = document.getElementById('clearAlertsBtn');
    if (btn) {
        btn.disabled = true;
        btn.dataset.originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Clearing…';
    }

    try {
        const response = await fetch('/api/audio/alerts/resolve-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                resolved_by: 'web_user',
                resolution_notes: 'Bulk resolved via web interface',
            }),
        });

        if (response.ok) {
            const data = await response.json();
            showSuccess(`Cleared ${(data.resolved_count || 0).toLocaleString()} alert(s)`);
            if (countEl) countEl.textContent = '0';
            loadAudioAlerts();
        } else {
            const error = await response.json().catch(() => ({}));
            showError(`Failed to clear alerts: ${error.error || response.statusText}`);
        }
    } catch (error) {
        console.error('Error clearing alerts:', error);
        showError('Failed to clear alerts');
    } finally {
        if (btn) {
            btn.disabled = false;
            if (btn.dataset.originalHtml) btn.innerHTML = btn.dataset.originalHtml;
        }
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
    // Clear polling intervals
    if (metricsUpdateInterval) clearInterval(metricsUpdateInterval);
    if (waveformUpdateInterval) clearInterval(waveformUpdateInterval);
    if (healthUpdateInterval) clearInterval(healthUpdateInterval);
    if (deviceMonitorInterval) clearInterval(deviceMonitorInterval);

    // Unsubscribe from WebSocket events
    if (wsMetricsUnsubscribe) wsMetricsUnsubscribe();
    if (wsHealthUnsubscribe) wsHealthUnsubscribe();
    if (wsSourcesUnsubscribe) wsSourcesUnsubscribe();
});
