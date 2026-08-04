/*
 * EAS Station™ - Alert Verification pre-upload audio inspector.
 * Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
 *
 * Parses the RIFF/WAV header of the selected file in the browser BEFORE
 * upload so the user gets instant feedback ("file is 12.3s @ 44100 Hz,
 * estimated processing ≈4 s") and obviously-broken files are rejected
 * locally instead of after a multi-megabyte round-trip.  This is the
 * "uses .js to feel instant" win without shipping a half-baked client-
 * side SAME demodulator — the actual demod still runs server-side.
 *
 * NOTE on a future fully-client-side decoder:
 *   The remaining piece (full Goertzel-based SAME demod in an
 *   AudioWorklet — preamble lock on 0xAB, then ZCZC parser) is sketched
 *   out in docs/ but intentionally NOT shipped here.  Getting bit
 *   slicing and FEC majority-vote correct requires a dedicated test
 *   harness; it's a feature for its own PR rather than a half-tested
 *   addition smuggled into a perf fix.
 */

(function () {
    'use strict';

    /**
     * Parse the leading bytes of an audio file and return high-level
     * metadata.  Only WAV is fully understood — for other containers we
     * return ``{ kind: 'unknown' }`` and let the server handle it.
     *
     * The implementation reads at most the first 4 KiB of the file (the
     * RIFF header is well under 1 KiB even with extra chunks) so it is
     * cheap regardless of total file size.
     *
     * @param {File} file
     * @returns {Promise<{kind: string, sampleRate?: number, channels?: number,
     *                    bitsPerSample?: number, durationSeconds?: number,
     *                    sizeBytes: number, warnings: string[]}>}
     */
    async function inspectAudioFile(file) {
        const result = {
            kind: 'unknown',
            sizeBytes: file.size,
            warnings: [],
        };

        if (!file || file.size < 12) {
            result.warnings.push('File is empty or too small to contain audio.');
            return result;
        }

        // Read the first 4 KiB; the RIFF header is far smaller but some
        // encoders stash extra chunks before "data".
        const headerBytes = await file.slice(0, Math.min(file.size, 4096)).arrayBuffer();
        const view = new DataView(headerBytes);

        const readAscii = (offset, length) => {
            let s = '';
            for (let i = 0; i < length; i += 1) s += String.fromCharCode(view.getUint8(offset + i));
            return s;
        };

        // ── WAV / RIFF ─────────────────────────────────────────────────
        if (readAscii(0, 4) === 'RIFF' && readAscii(8, 4) === 'WAVE') {
            result.kind = 'wav';

            // Walk chunks: each chunk is { id[4] | size[4 LE] | data[size] }.
            let offset = 12;
            let fmtFound = false;
            let dataSize = 0;
            const limit = Math.min(view.byteLength, file.size);
            while (offset + 8 <= limit) {
                const chunkId = readAscii(offset, 4);
                const chunkSize = view.getUint32(offset + 4, /* little-endian */ true);
                if (chunkId === 'fmt ') {
                    fmtFound = true;
                    // PCM/IEEE-float layout: format[2], channels[2], rate[4],
                    //                       byterate[4], blockalign[2], bps[2].
                    if (offset + 8 + 16 <= limit) {
                        const audioFormat = view.getUint16(offset + 8, true);
                        result.channels = view.getUint16(offset + 10, true);
                        result.sampleRate = view.getUint32(offset + 12, true);
                        result.bitsPerSample = view.getUint16(offset + 22, true);
                        result.audioFormat = audioFormat;
                    }
                } else if (chunkId === 'data') {
                    dataSize = chunkSize;
                    break;
                }
                // Chunks are word-aligned; pad odd sizes.
                offset += 8 + chunkSize + (chunkSize & 1);
            }

            if (!fmtFound || !result.sampleRate) {
                result.warnings.push('WAV file is missing a valid "fmt " chunk.');
                return result;
            }

            const bytesPerSample = (result.bitsPerSample || 16) / 8;
            const frameSize = bytesPerSample * (result.channels || 1);
            if (frameSize > 0) {
                // Prefer the declared data-chunk size when present; fall
                // back to total file size minus a generous header budget.
                const audioBytes = dataSize > 0 ? dataSize : Math.max(0, file.size - 44);
                result.durationSeconds = audioBytes / frameSize / result.sampleRate;
            }

            // Sanity checks.
            if (result.sampleRate < 8000 || result.sampleRate > 192000) {
                result.warnings.push(
                    `Unusual sample rate: ${result.sampleRate} Hz. SAME bursts are typically recorded at 11025–48000 Hz.`
                );
            }
            if (result.durationSeconds !== undefined && result.durationSeconds < 1.0) {
                result.warnings.push(
                    `Audio is only ${result.durationSeconds.toFixed(2)}s — too short to contain a full SAME burst (~2.6s minimum).`
                );
            }
            return result;
        }

        // ── MP3 (ID3 or sync word) ────────────────────────────────────
        if (readAscii(0, 3) === 'ID3' || (view.getUint8(0) === 0xff && (view.getUint8(1) & 0xe0) === 0xe0)) {
            result.kind = 'mp3';
            return result;
        }

        result.warnings.push('File does not appear to be a WAV or MP3.');
        return result;
    }

    /**
     * Return a human-readable processing-time estimate for the given
     * inspection result.  These coefficients are derived from
     * server-side measurements on a Pi-class box for the optimised
     * pipeline (single-rate decode + tone scan, no narration when not
     * storing).  The estimate is intentionally optimistic so we don't
     * scare users away — the server's progress bar will tell the truth.
     *
     * @param {object} info
     * @param {boolean} willStore - whether store_results is checked
     * @returns {string|null}
     */
    function estimateProcessingTime(info, willStore) {
        if (!info || info.durationSeconds === undefined) return null;
        const dur = info.durationSeconds;
        // Decode roughly tracks audio duration. Storage adds the
        // narration + composite passes which double the work.
        const baseSeconds = Math.max(0.5, dur * 0.15);
        const totalSeconds = willStore ? baseSeconds * 2.2 : baseSeconds;
        if (totalSeconds < 1) return '<1 s';
        if (totalSeconds < 60) return `≈${totalSeconds.toFixed(0)} s`;
        return `≈${(totalSeconds / 60).toFixed(1)} min`;
    }

    /**
     * Render a one-line summary into the supplied container.
     */
    function renderSummary(container, info, willStore) {
        if (!container) return;

        const sizeMB = (info.sizeBytes / 1048576).toFixed(2);
        const parts = [];

        if (info.kind === 'wav') {
            parts.push(`<i class="fas fa-circle-check text-success"></i>`);
            parts.push(`<strong>WAV</strong>`);
            if (info.sampleRate) {
                const rateLabel = `${info.sampleRate.toLocaleString()} Hz`;
                const channelLabel = info.channels === 2 ? 'stereo' : 'mono';
                parts.push(`${rateLabel} ${channelLabel}, ${info.bitsPerSample || '?'}-bit`);
            }
            if (info.durationSeconds !== undefined) {
                parts.push(`${info.durationSeconds.toFixed(1)}s`);
            }
            parts.push(`(${sizeMB} MB)`);
            const estimate = estimateProcessingTime(info, willStore);
            if (estimate) parts.push(`— estimated decode ${estimate}`);
        } else if (info.kind === 'mp3') {
            parts.push(`<i class="fas fa-circle-info text-info"></i>`);
            parts.push(`<strong>MP3</strong> (${sizeMB} MB)`);
            parts.push('— full multi-rate sweep will run server-side');
        } else {
            parts.push(`<i class="fas fa-triangle-exclamation text-warning"></i>`);
            parts.push(`Unknown format (${sizeMB} MB)`);
        }

        let html = `<span class="small">${parts.join(' ')}</span>`;
        if (info.warnings && info.warnings.length) {
            const warnList = info.warnings
                .map((w) => `<li>${escapeHtml(w)}</li>`)
                .join('');
            html += `<ul class="mb-0 mt-1 small text-warning">${warnList}</ul>`;
        }
        container.innerHTML = html;
    }


    function init() {
        const fileInput = document.getElementById('audio_file');
        const storeCheckbox = document.getElementById('store_results');
        if (!fileInput) return;

        // Inject a placeholder <div> directly under the existing
        // form-text help block so the summary appears in-line without
        // disturbing layout.
        const helpBlock = fileInput.parentElement
            ? fileInput.parentElement.querySelector('.form-text')
            : null;
        const summary = document.createElement('div');
        summary.id = 'audio-file-summary';
        summary.className = 'mt-2';
        summary.setAttribute('aria-live', 'polite');
        if (helpBlock && helpBlock.parentNode) {
            helpBlock.parentNode.insertBefore(summary, helpBlock.nextSibling);
        } else if (fileInput.parentNode) {
            fileInput.parentNode.appendChild(summary);
        }

        let lastInfo = null;

        const refresh = async () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) {
                summary.innerHTML = '';
                lastInfo = null;
                return;
            }
            try {
                lastInfo = await inspectAudioFile(file);
            } catch (err) {
                summary.innerHTML =
                    '<span class="small text-danger">Could not read audio file header.</span>';
                lastInfo = null;
                return;
            }
            renderSummary(summary, lastInfo, !!(storeCheckbox && storeCheckbox.checked));
        };

        fileInput.addEventListener('change', refresh);
        if (storeCheckbox) {
            storeCheckbox.addEventListener('change', () => {
                if (lastInfo) renderSummary(summary, lastInfo, !!storeCheckbox.checked);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose for tests / future composition.
    window.AlertVerificationPreupload = {
        inspectAudioFile,
        estimateProcessingTime,
        renderSummary,
    };
})();
