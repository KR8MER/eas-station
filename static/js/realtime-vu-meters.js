/**
 * Real-time VU Meter Implementation using Web Audio API
 * Updates at 60Hz for smooth, professional-looking level meters
 * 
 * This analyzes the actual audio stream playing in the browser,
 * providing true real-time visual feedback without server polling.
 */

// Store audio contexts and analyzers for each source
const audioAnalyzers = new Map();
let animationFrameId = null;

/**
 * Initialize real-time VU meter for an audio element
 * @param {HTMLAudioElement} audioElement - The audio element to analyze
 * @param {string} sourceName - Name of the audio source
 */
function initializeRealtimeVUMeter(audioElement, sourceName) {
    if (!audioElement || !sourceName) {
        console.warn('Invalid audio element or source name for VU meter');
        return;
    }

    // Clean up existing analyzer if present
    cleanupRealtimeVUMeter(sourceName);

    try {
        // Create audio context
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) {
            console.warn('Web Audio API not supported - VU meters will use server data');
            return;
        }

        const audioContext = new AudioContext();
        
        // Create analyzer node
        const analyzer = audioContext.createAnalyser();
        analyzer.fftSize = 256; // Small FFT for fast response
        analyzer.smoothingTimeConstant = 0.3; // Moderate smoothing for realistic VU behavior
        
        // Create source from audio element
        const source = audioContext.createMediaElementSource(audioElement);
        
        // Connect: source -> analyzer -> destination
        source.connect(analyzer);
        analyzer.connect(audioContext.destination);
        
        // Store analyzer info
        const bufferLength = analyzer.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        
        audioAnalyzers.set(sourceName, {
            audioContext,
            analyzer,
            dataArray,
            bufferLength,
            audioElement,
            lastPeak: -120,
            lastRMS: -120,
            peakHold: -120,
            peakHoldTime: 0
        });
        
        console.log(`Real-time VU meter initialized for ${sourceName}`);
        
        // Start animation loop if not already running
        if (!animationFrameId) {
            startVUMeterAnimation();
        }
    } catch (error) {
        console.error(`Failed to initialize real-time VU meter for ${sourceName}:`, error);
    }
}

/**
 * Clean up VU meter resources for a source
 */
function cleanupRealtimeVUMeter(sourceName) {
    const analyzer = audioAnalyzers.get(sourceName);
    if (analyzer) {
        try {
            if (analyzer.audioContext && analyzer.audioContext.state !== 'closed') {
                analyzer.audioContext.close();
            }
        } catch (error) {
            console.debug(`Error closing audio context for ${sourceName}:`, error);
        }
        audioAnalyzers.delete(sourceName);
    }
}

/**
 * Start the animation loop that updates all VU meters at 60Hz
 */
function startVUMeterAnimation() {
    function animate() {
        // Update all active VU meters
        audioAnalyzers.forEach((analyzer, sourceName) => {
            updateVUMeterForSource(sourceName, analyzer);
        });
        
        // Continue animation loop if we have active analyzers
        if (audioAnalyzers.size > 0) {
            animationFrameId = requestAnimationFrame(animate);
        } else {
            animationFrameId = null;
        }
    }
    
    animationFrameId = requestAnimationFrame(animate);
}

/**
 * Update VU meter display for a specific source
 */
function updateVUMeterForSource(sourceName, analyzer) {
    const safeId = sanitizeId(sourceName);
    const peakBar = document.getElementById(`peak-meter-${safeId}`);
    const rmsBar = document.getElementById(`rms-meter-${safeId}`);
    const peakLabel = document.getElementById(`peak-label-${safeId}`);
    const rmsLabel = document.getElementById(`rms-label-${safeId}`);
    
    if (!peakBar || !analyzer.analyzer) {
        return;
    }
    
    // Get frequency data
    analyzer.analyzer.getByteFrequencyData(analyzer.dataArray);
    
    // Calculate peak and RMS levels
    let sum = 0;
    let peak = 0;
    
    for (let i = 0; i < analyzer.bufferLength; i++) {
        const value = analyzer.dataArray[i];
        sum += value * value;
        if (value > peak) {
            peak = value;
        }
    }
    
    // Convert to dBFS (0-255 range to -120 to 0 dBFS)
    // Uint8Array from analyzer: 0 = silence, 255 = maximum
    const peakDb = peak > 0 ? (20 * Math.log10(peak / 255)) : -120;
    const rmsValue = Math.sqrt(sum / analyzer.bufferLength);
    const rmsDb = rmsValue > 0 ? (20 * Math.log10(rmsValue / 255)) : -120;
    
    // Apply smoothing for realistic VU meter ballistics
    const PEAK_ATTACK = 0.7;  // Fast attack
    const PEAK_RELEASE = 0.2; // Slow release
    const RMS_SMOOTHING = 0.3;
    const PEAK_HOLD_TIME_MS = 1500;
    
    // Smooth peak value
    let smoothedPeak;
    if (peakDb > analyzer.lastPeak) {
        smoothedPeak = analyzer.lastPeak * (1 - PEAK_ATTACK) + peakDb * PEAK_ATTACK;
    } else {
        smoothedPeak = analyzer.lastPeak * (1 - PEAK_RELEASE) + peakDb * PEAK_RELEASE;
    }
    
    // Update peak hold
    const now = Date.now();
    if (peakDb > analyzer.peakHold) {
        analyzer.peakHold = peakDb;
        analyzer.peakHoldTime = now;
    } else if (now - analyzer.peakHoldTime > PEAK_HOLD_TIME_MS) {
        analyzer.peakHold = peakDb;
        analyzer.peakHoldTime = now;
    }
    
    // Smooth RMS value
    const smoothedRMS = analyzer.lastRMS * (1 - RMS_SMOOTHING) + rmsDb * RMS_SMOOTHING;
    
    // Update stored values
    analyzer.lastPeak = smoothedPeak;
    analyzer.lastRMS = smoothedRMS;
    
    // Check if audio is playing
    const isPlaying = analyzer.audioElement && 
                      !analyzer.audioElement.paused && 
                      analyzer.audioElement.currentTime > 0;
    
    // Update UI
    const peakWidth = calculateFillWidth(smoothedPeak);
    const rmsWidth = calculateFillWidth(smoothedRMS);
    
    peakBar.style.width = `${peakWidth}%`;
    peakBar.style.opacity = isPlaying ? 1 : 0.35;
    
    if (rmsBar) {
        rmsBar.style.width = `${rmsWidth}%`;
        rmsBar.style.opacity = isPlaying ? 0.9 : 0.3;
    }
    
    if (peakLabel) {
        peakLabel.textContent = `Peak: ${formatDbLabel(smoothedPeak)}`;
    }
    
    if (rmsLabel) {
        rmsLabel.textContent = `RMS: ${formatDbLabel(smoothedRMS)}`;
    }
}

/**
 * Helper function to calculate fill width from dB value
 */
function calculateFillWidth(dbValue) {
    if (typeof dbValue !== 'number' || Number.isNaN(dbValue) || dbValue <= -120) {
        return 0;
    }
    
    // Professional VU meter mapping: -60 dBFS to 0 dBFS
    const MIN_DB = -60;
    const MAX_DB = 0;
    const clamped = Math.max(MIN_DB, Math.min(MAX_DB, dbValue));
    
    // Convert to 0-1 range
    const normalized = (clamped - MIN_DB) / (MAX_DB - MIN_DB);
    
    // Apply slight curve for better visual response
    const curved = Math.pow(normalized, 0.8);
    
    return curved * 100;
}

/**
 * Format dB value for display
 */
function formatDbLabel(value) {
    if (typeof value !== 'number' || Number.isNaN(value) || value <= -120) {
        return '-- dBFS';
    }
    return `${value.toFixed(1)} dBFS`;
}

/**
 * Sanitize ID for use in DOM selectors
 */
function sanitizeId(text) {
    return (text || '').toString().replace(/[^a-zA-Z0-9_-]/g, '-');
}

/**
 * Enable real-time VU meters for all audio players on the page
 */
function enableRealtimeVUMeters() {
    // Find all audio elements
    const audioElements = document.querySelectorAll('audio[data-source-name]');
    
    audioElements.forEach(audioElement => {
        const sourceName = audioElement.dataset.sourceName;
        if (sourceName) {
            // Initialize when audio starts playing
            audioElement.addEventListener('playing', () => {
                initializeRealtimeVUMeter(audioElement, sourceName);
            });
            
            // Cleanup when audio pauses/ends
            audioElement.addEventListener('pause', () => {
                // Keep analyzer but stop showing active levels
            });
            
            audioElement.addEventListener('ended', () => {
                cleanupRealtimeVUMeter(sourceName);
            });
            
            // If already playing, initialize now
            if (!audioElement.paused && audioElement.currentTime > 0) {
                initializeRealtimeVUMeter(audioElement, sourceName);
            }
        }
    });
    
    console.log(`Real-time VU meters enabled for ${audioElements.length} audio sources`);
}

/**
 * Disable real-time VU meters and clean up resources
 */
function disableRealtimeVUMeters() {
    // Clean up all analyzers
    audioAnalyzers.forEach((analyzer, sourceName) => {
        cleanupRealtimeVUMeter(sourceName);
    });
    
    // Cancel animation frame
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
    
    console.log('Real-time VU meters disabled');
}

// Export functions for use in other scripts
window.enableRealtimeVUMeters = enableRealtimeVUMeters;
window.disableRealtimeVUMeters = disableRealtimeVUMeters;
window.initializeRealtimeVUMeter = initializeRealtimeVUMeter;
window.cleanupRealtimeVUMeter = cleanupRealtimeVUMeter;
