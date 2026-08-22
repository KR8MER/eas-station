/**
 * Real-time VU meters driven by the Web Audio API.
 *
 * Design notes — the constraints that shaped this file:
 *
 *  * ONE shared AudioContext. Each AudioContext spins up its own audio render
 *    thread, so the previous one-per-source arrangement multiplied that cost
 *    by the number of players on the page.
 *  * Time-domain sampling, not FFT. `getByteFrequencyData()` runs an FFT on
 *    every call and returns spectral magnitudes — which are not signal
 *    amplitude, so deriving "peak" and "RMS" from them was measuring the wrong
 *    quantity. `getByteTimeDomainData()` just copies the sample buffer: it is
 *    both cheaper and the correct input for a level meter.
 *  * Frame-rate-independent ballistics. Attack/release are expressed as time
 *    constants and applied against the real elapsed interval, so the meter
 *    behaves identically whatever rate the loop actually achieves. Fixed
 *    per-frame coefficients silently changed the decay whenever the rate did,
 *    which is what made raising the frame rate risky before.
 *  * The loop is `requestAnimationFrame`, never a tight timer. rAF is capped
 *    at the display refresh rate and is suspended entirely while the tab is
 *    hidden, so a backgrounded page costs nothing.
 *  * Work is skipped, not repeated. Sources that are paused and fully decayed
 *    are not analysed at all, and DOM writes happen only when the rendered
 *    value actually changes — style and text writes trigger layout and cost
 *    considerably more than the sampling itself.
 */

const audioAnalyzers = new Map();

// Web Audio graph nodes, keyed by media element. `createMediaElementSource`
// throws if called twice for the same element on one context, and once an
// element is routed through the graph its audio reaches the speakers only via
// that graph — so these nodes are built once and left wired for the element's
// lifetime rather than torn down whenever a meter stops.
const elementNodes = new WeakMap();

let sharedAudioContext = null;
let animationFrameId = null;
let lastVUMeterUpdateTime = 0;

// ~30 fps, twice the previous 15 fps. Each update now does strictly less work
// (no FFT, fewer DOM writes, paused sources skipped entirely), so this is both
// more responsive and cheaper than what it replaces.
const VU_METER_UPDATE_INTERVAL_MS = 33;

// Largest interval fed to the ballistics. Without this the first frame — and
// the frame after a hidden tab resumes — would apply a multi-second decay in
// one step and slam every meter to zero.
const MAX_BALLISTIC_DELTA_S = 0.25;

// Ballistic time constants, in seconds. Attack is quick enough to catch
// transients; release is slow enough to read as a VU meter rather than a
// flicker. Expressed as time constants so they hold at any frame rate.
const PEAK_ATTACK_TAU_S = 0.025;
const PEAK_RELEASE_TAU_S = 0.30;
const RMS_TAU_S = 0.15;

const SILENCE_DB = -120;

// Text labels are re-rendered far more slowly than the bars: reflowing text at
// 30 fps costs more than the audio analysis and is unreadable anyway.
const LABEL_UPDATE_INTERVAL_MS = 125;

/**
 * Lazily create the single shared AudioContext.
 */
function getSharedAudioContext() {
    if (sharedAudioContext && sharedAudioContext.state !== 'closed') {
        return sharedAudioContext;
    }
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) {
        console.warn('Web Audio API not supported - VU meters will use server data');
        return null;
    }
    sharedAudioContext = new Ctor();
    return sharedAudioContext;
}

function resumeSharedAudioContext() {
    if (sharedAudioContext && sharedAudioContext.state === 'suspended') {
        sharedAudioContext.resume().catch((err) => {
            console.debug('Could not resume audio context:', err);
        });
    }
}

/**
 * Build (or reuse) the source -> analyser -> destination chain for an element.
 */
function getElementNodes(audioElement) {
    const existing = elementNodes.get(audioElement);
    if (existing) {
        return existing;
    }

    const audioContext = getSharedAudioContext();
    if (!audioContext) {
        return null;
    }

    let source;
    try {
        source = audioContext.createMediaElementSource(audioElement);
    } catch (error) {
        // Already bound to a different context elsewhere on the page. Nothing
        // to do but leave this element's audio alone.
        console.debug('Audio element already has a source node - skipping Web Audio VU meter');
        return null;
    }

    const analyser = audioContext.createAnalyser();
    // 256 samples ≈ 5 ms at 48 kHz — a short window, so the meter tracks
    // transients instead of averaging them away.
    analyser.fftSize = 256;
    // Only affects getByteFrequencyData(), which this file no longer calls.
    // Left at 0 so nothing adds hidden lag on top of the ballistics below.
    analyser.smoothingTimeConstant = 0;

    // Passing audio through to the speakers is not optional: routing an element
    // through the graph and failing to reach the destination mutes it.
    source.connect(analyser);
    analyser.connect(audioContext.destination);

    const nodes = { source, analyser };
    elementNodes.set(audioElement, nodes);
    return nodes;
}

function initializeRealtimeVUMeter(audioElement, sourceName) {
    if (!audioElement || !sourceName) {
        console.warn('Invalid audio element or source name for VU meter');
        return;
    }

    // Already metering this source with this element — re-initialising would
    // only rebuild identical state and discard the current ballistics.
    const current = audioAnalyzers.get(sourceName);
    if (current && current.audioElement === audioElement) {
        resumeSharedAudioContext();
        return;
    }

    try {
        const nodes = getElementNodes(audioElement);
        if (!nodes) {
            return;
        }
        resumeSharedAudioContext();

        const safeId = sanitizeId(sourceName);

        audioAnalyzers.set(sourceName, {
            analyser: nodes.analyser,
            // Time-domain bytes: one per sample, centred on 128.
            dataArray: new Uint8Array(nodes.analyser.fftSize),
            audioElement,
            lastPeak: SILENCE_DB,
            lastRMS: SILENCE_DB,
            // Last values actually written to the DOM, so redundant writes can
            // be skipped.
            renderedPeakWidth: null,
            renderedRmsWidth: null,
            renderedPeakLabel: null,
            renderedRmsLabel: null,
            renderedPlaying: null,
            lastLabelUpdate: 0,
            settled: false,
            // Cached DOM elements to avoid repeated lookups in the loop.
            peakBar: document.getElementById(`peak-meter-${safeId}`),
            rmsBar: document.getElementById(`rms-meter-${safeId}`),
            peakLabel: document.getElementById(`peak-label-${safeId}`),
            rmsLabel: document.getElementById(`rms-label-${safeId}`),
        });

        if (!animationFrameId) {
            startVUMeterAnimation();
        }
    } catch (error) {
        console.error(`Failed to initialize real-time VU meter for ${sourceName}:`, error);
    }
}

/**
 * Stop metering a source.
 *
 * The Web Audio nodes are deliberately left connected: the element may still be
 * playing, and disconnecting the chain would silence it. They are released only
 * by `pruneDetachedMeters()`, once the element has left the document.
 */
function cleanupRealtimeVUMeter(sourceName) {
    audioAnalyzers.delete(sourceName);
}

/**
 * Drop meters whose audio element is no longer in the document.
 *
 * The source list re-renders on a timer, replacing the audio elements. Without
 * this, every render left its predecessor's meter in the map — re-analysed on
 * every frame, forever, against an element nothing could play again.
 */
function pruneDetachedMeters() {
    audioAnalyzers.forEach((meter, sourceName) => {
        if (!meter.audioElement || !document.contains(meter.audioElement)) {
            const nodes = meter.audioElement ? elementNodes.get(meter.audioElement) : null;
            if (nodes) {
                try {
                    nodes.source.disconnect();
                    nodes.analyser.disconnect();
                } catch (error) {
                    console.debug(`Nodes already disconnected for ${sourceName}`);
                }
                elementNodes.delete(meter.audioElement);
            }
            audioAnalyzers.delete(sourceName);
        }
    });
}

/**
 * Animation loop. requestAnimationFrame only — never a timer-driven spin.
 */
function startVUMeterAnimation() {
    function animate(timestamp) {
        const elapsedMs = timestamp - lastVUMeterUpdateTime;

        if (elapsedMs >= VU_METER_UPDATE_INTERVAL_MS) {
            const deltaSeconds = Math.min(elapsedMs / 1000, MAX_BALLISTIC_DELTA_S);
            lastVUMeterUpdateTime = timestamp;

            audioAnalyzers.forEach((meter, sourceName) => {
                updateVUMeterForSource(sourceName, meter, deltaSeconds, timestamp);
            });
        }

        if (audioAnalyzers.size > 0) {
            animationFrameId = requestAnimationFrame(animate);
        } else {
            animationFrameId = null;
        }
    }

    lastVUMeterUpdateTime = 0;
    animationFrameId = requestAnimationFrame(animate);
}

/**
 * Exponential smoothing coefficient for an elapsed interval and time constant.
 * Deriving the factor per interval is what makes the ballistics independent of
 * how fast the loop happens to run.
 */
function smoothingFactor(deltaSeconds, tauSeconds) {
    if (tauSeconds <= 0) {
        return 1;
    }
    return 1 - Math.exp(-deltaSeconds / tauSeconds);
}

/**
 * Update one source's meter.
 */
function updateVUMeterForSource(sourceName, meter, deltaSeconds, timestamp) {
    const peakBar = meter.peakBar;
    if (!peakBar || !meter.analyser) {
        return;
    }

    const audioElement = meter.audioElement;
    const isPlaying = Boolean(
        audioElement && !audioElement.paused && audioElement.currentTime > 0
    );

    // A paused source whose meter has already decayed to silence has nothing
    // left to show. Skip it entirely rather than re-running the arithmetic and
    // rewriting identical styles on every frame.
    if (!isPlaying && meter.settled) {
        if (meter.renderedPlaying !== false) {
            applyPlayingState(meter, false);
        }
        return;
    }

    let peakDb = SILENCE_DB;
    let rmsDb = SILENCE_DB;

    if (isPlaying) {
        meter.analyser.getByteTimeDomainData(meter.dataArray);

        const samples = meter.dataArray;
        const sampleCount = samples.length;
        let sumSquares = 0;
        let peakAmplitude = 0;

        for (let i = 0; i < sampleCount; i++) {
            // Bytes are centred on 128; convert to -1..1.
            const amplitude = (samples[i] - 128) / 128;
            sumSquares += amplitude * amplitude;
            const magnitude = amplitude < 0 ? -amplitude : amplitude;
            if (magnitude > peakAmplitude) {
                peakAmplitude = magnitude;
            }
        }

        peakDb = peakAmplitude > 0 ? 20 * Math.log10(peakAmplitude) : SILENCE_DB;
        const rmsAmplitude = Math.sqrt(sumSquares / sampleCount);
        rmsDb = rmsAmplitude > 0 ? 20 * Math.log10(rmsAmplitude) : SILENCE_DB;
    }

    const peakTau = peakDb > meter.lastPeak ? PEAK_ATTACK_TAU_S : PEAK_RELEASE_TAU_S;
    const peakAlpha = smoothingFactor(deltaSeconds, peakTau);
    const rmsAlpha = smoothingFactor(deltaSeconds, RMS_TAU_S);

    const smoothedPeak = meter.lastPeak + (peakDb - meter.lastPeak) * peakAlpha;
    const smoothedRMS = meter.lastRMS + (rmsDb - meter.lastRMS) * rmsAlpha;

    meter.lastPeak = smoothedPeak;
    meter.lastRMS = smoothedRMS;

    // Once a stopped source has decayed to the floor there is nothing left to
    // animate, so the next frame can skip it (see the guard above).
    meter.settled =
        !isPlaying &&
        smoothedPeak <= SILENCE_DB + 0.5 &&
        smoothedRMS <= SILENCE_DB + 0.5;

    // DOM writes dominate this loop. Quantise to 0.1% and write only on change
    // — the bar cannot render finer than that anyway.
    const peakWidth = Math.round(calculateFillWidth(smoothedPeak) * 10) / 10;
    if (peakWidth !== meter.renderedPeakWidth) {
        peakBar.style.width = `${peakWidth}%`;
        meter.renderedPeakWidth = peakWidth;
    }

    if (meter.rmsBar) {
        const rmsWidth = Math.round(calculateFillWidth(smoothedRMS) * 10) / 10;
        if (rmsWidth !== meter.renderedRmsWidth) {
            meter.rmsBar.style.width = `${rmsWidth}%`;
            meter.renderedRmsWidth = rmsWidth;
        }
    }

    if (meter.renderedPlaying !== isPlaying) {
        applyPlayingState(meter, isPlaying);
    }

    // Labels change far more slowly than the bars.
    if (timestamp - meter.lastLabelUpdate >= LABEL_UPDATE_INTERVAL_MS) {
        meter.lastLabelUpdate = timestamp;

        if (meter.peakLabel) {
            const text = `Peak: ${formatDbLabel(smoothedPeak)}`;
            if (text !== meter.renderedPeakLabel) {
                meter.peakLabel.textContent = text;
                meter.renderedPeakLabel = text;
                // Marks this label as under this script's control, so
                // audio_monitoring.js's updateMeterDisplay() (which also
                // writes "Peak: X dBFS" text, on pages where this script
                // isn't loaded) knows to leave it alone rather than
                // fighting over it. A substring check on the text itself
                // can't tell the two apart: the static HTML placeholder is
                // "Peak: -- dBFS", which already contains "dBFS".
                meter.peakLabel.dataset.liveVu = 'true';
            }
        }
        if (meter.rmsLabel) {
            const text = `RMS: ${formatDbLabel(smoothedRMS)}`;
            if (text !== meter.renderedRmsLabel) {
                meter.rmsLabel.textContent = text;
                meter.renderedRmsLabel = text;
                meter.rmsLabel.dataset.liveVu = 'true';
            }
        }
    }
}

function applyPlayingState(meter, isPlaying) {
    if (meter.peakBar) {
        meter.peakBar.style.opacity = isPlaying ? 1 : 0.35;
    }
    if (meter.rmsBar) {
        meter.rmsBar.style.opacity = isPlaying ? 0.9 : 0.3;
    }
    meter.renderedPlaying = isPlaying;
}

/**
 * Helper function to calculate fill width from dB value
 */
function calculateFillWidth(dbValue) {
    if (typeof dbValue !== 'number' || Number.isNaN(dbValue) || dbValue <= SILENCE_DB) {
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
    if (typeof value !== 'number' || Number.isNaN(value) || value <= SILENCE_DB) {
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
 * Enable real-time VU meters for all audio players on the page.
 *
 * Safe to call repeatedly — the source list re-renders on a timer and calls
 * this each time. Listeners are registered once per element, and meters left
 * behind by a previous render are pruned.
 */
function enableRealtimeVUMeters() {
    pruneDetachedMeters();

    const audioElements = document.querySelectorAll('audio[data-source-name]');

    audioElements.forEach((audioElement) => {
        const sourceName = audioElement.dataset.sourceName;
        if (!sourceName) {
            return;
        }

        // Without this guard every re-render stacked another set of listeners
        // onto the same element.
        if (!audioElement.dataset.vuMeterBound) {
            audioElement.dataset.vuMeterBound = '1';

            audioElement.addEventListener('playing', () => {
                initializeRealtimeVUMeter(audioElement, sourceName);
            });
            audioElement.addEventListener('ended', () => {
                cleanupRealtimeVUMeter(sourceName);
            });
        }

        if (!audioElement.paused && audioElement.currentTime > 0) {
            initializeRealtimeVUMeter(audioElement, sourceName);
        }
    });
}

/**
 * Disable real-time VU meters and clean up resources
 */
function disableRealtimeVUMeters() {
    audioAnalyzers.clear();

    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
}

// Export functions for use in other scripts
window.enableRealtimeVUMeters = enableRealtimeVUMeters;
window.disableRealtimeVUMeters = disableRealtimeVUMeters;
window.initializeRealtimeVUMeter = initializeRealtimeVUMeter;
window.cleanupRealtimeVUMeter = cleanupRealtimeVUMeter;
