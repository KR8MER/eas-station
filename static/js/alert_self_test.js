(function () {
    const context = window.alertSelfTestContext || {};
    const runButton = document.getElementById('run-self-test');
    const spinner = document.getElementById('self-test-spinner');
    const resultsSection = document.getElementById('self-test-results');
    const tableBody = document.getElementById('self-test-results-body');
    const feedbackSection = document.getElementById('self-test-feedback');
    const statusEl = document.getElementById('self-test-status');
    const summaryEl = document.getElementById('self-test-summary');
    const forwardedEl = document.getElementById('forwarded-count');
    const duplicateEl = document.getElementById('duplicate-count');
    const errorEl = document.getElementById('error-count');
    const timestampEl = document.getElementById('self-test-timestamp');
    const fipsEl = document.getElementById('self-test-fips');
    const cooldownBadge = document.getElementById('self-test-cooldown');
    const sourceBadge = document.getElementById('self-test-source');
    const errorBanner = document.getElementById('self-test-error');
    const selectAllButton = document.getElementById('select-all-samples');
    const cooldownInput = document.getElementById('cooldown-input');
    const defaultCooldown = context.default_cooldown || 30;

    if (cooldownInput && !cooldownInput.value) {
        cooldownInput.value = defaultCooldown;
    }

    if (selectAllButton) {
        selectAllButton.addEventListener('click', (event) => {
            event.preventDefault();
            document.querySelectorAll('.sample-checkbox').forEach((checkbox) => {
                checkbox.checked = true;
            });
        });
    }

    if (runButton) {
        runButton.addEventListener('click', (event) => {
            event.preventDefault();
            runSelfTest();
        });
    }

    function setLoading(isLoading) {
        if (runButton) {
            runButton.disabled = isLoading;
        }
        if (spinner) {
            spinner.classList.toggle('d-none', !isLoading);
        }
    }

    function showBanner(message, variant = 'danger') {
        if (!errorBanner) {
            return;
        }
        errorBanner.textContent = message;
        errorBanner.classList.remove('d-none', 'alert-danger', 'alert-warning', 'alert-success', 'alert-info');
        errorBanner.classList.add(`alert-${variant}`);
    }

    function clearError() {
        if (!errorBanner) {
            return;
        }
        errorBanner.textContent = '';
        errorBanner.classList.add('d-none');
    }

    function gatherSamplePaths() {
        const selected = [];
        document.querySelectorAll('.sample-checkbox:checked').forEach((checkbox) => {
            selected.push(checkbox.value);
        });
        return selected;
    }

    function parseList(value) {
        if (!value) {
            return [];
        }
        return value
            .split(/\n|,/)
            .map((entry) => entry.trim())
            .filter(Boolean);
    }

    function gatherPayload() {
        const audioPaths = gatherSamplePaths().concat(parseList(document.getElementById('custom-audio-paths')?.value));
        const includeDefaults = document.getElementById('include-default-samples')?.checked !== false;
        const cooldownValue = document.getElementById('cooldown-input')?.value;
        const sourceName = document.getElementById('source-name-input')?.value || 'self-test';
        const requireMatch = document.getElementById('require-match')?.checked ?? false;
        const fipsOverrideRaw = document.getElementById('fips-override')?.value;

        return {
            audio_paths: audioPaths,
            use_default_samples: includeDefaults,
            duplicate_cooldown: cooldownValue,
            source_name: sourceName,
            require_match: requireMatch,
            fips_codes: parseList(fipsOverrideRaw),
        };
    }

    async function runSelfTest() {
        setLoading(true);
        clearError();
        try {
            const payload = gatherPayload();
            const response = await fetch('/api/alert-self-test/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await response.json();
            if (!response.ok) {
                showBanner(data.error || 'Unable to run the alert self-test.');
                return;
            }
            updateResults(data);
            if (data.success === false && data.error) {
                showBanner(data.error, 'warning');
            } else {
                clearError();
            }
        } catch (error) {
            console.error('Self-test request failed', error);
            showBanner('Unable to run the alert self-test. Check server logs for details.');
        } finally {
            setLoading(false);
        }
    }

    function updateResults(data) {
        if (!feedbackSection || !tableBody) {
            return;
        }

        feedbackSection.hidden = false;
        resultsSection.hidden = false;

        const duplicates = (data.results || []).filter((item) => item.status === 'duplicate_suppressed').length;
        forwardedEl.textContent = data.forwarded_count ?? 0;
        duplicateEl.textContent = duplicates;
        errorEl.textContent = data.decode_error_count ?? 0;

        const total = data.results?.length || 0;
        const summaryText = data.error || `Forwarded ${data.forwarded_count} of ${total} sample(s).`;
        statusEl.textContent = data.success ? 'PASS' : 'ATTENTION REQUIRED';
        statusEl.classList.toggle('text-success', Boolean(data.success));
        statusEl.classList.toggle('text-danger', !data.success);
        summaryEl.textContent = summaryText;

        if (timestampEl) {
            const when = data.timestamp ? new Date(data.timestamp) : new Date();
            timestampEl.textContent = when.toLocaleString();
        }
        if (fipsEl) {
            fipsEl.textContent = (data.configured_fips && data.configured_fips.length)
                ? data.configured_fips.join(', ')
                : 'None (all alerts filtered)';
        }
        if (cooldownBadge) {
            cooldownBadge.textContent = `Cooldown: ${Number(data.duplicate_cooldown).toFixed(1)}s`;
        }
        if (sourceBadge) {
            sourceBadge.textContent = `Source: ${data.source_name}`;
        }

        renderResultTable(data.results || []);
    }

    function renderResultTable(results) {
        tableBody.innerHTML = '';
        if (!results.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 6;
            cell.className = 'text-center text-muted';
            cell.textContent = 'No samples were processed.';
            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }

        results.forEach((item) => {
            const row = document.createElement('tr');
            row.appendChild(buildStatusCell(item.status));
            row.appendChild(createTextCell(item.event_code || '—'));
            row.appendChild(createTextCell(item.originator || '—'));
            row.appendChild(createTextCell(formatMatchList(item.matched_fips_codes)));
            row.appendChild(createTextCell(item.reason || '—'));
            row.appendChild(buildAudioCell(item.audio_path));
            tableBody.appendChild(row);
        });
    }

    function buildStatusCell(status) {
        const colours = {
            forwarded: 'success',
            filtered: 'secondary',
            duplicate_suppressed: 'warning',
            decode_error: 'danger',
        };
        const labels = {
            forwarded: 'Forwarded',
            filtered: 'Filtered',
            duplicate_suppressed: 'Duplicate',
            decode_error: 'Decode Error',
        };
        const badge = document.createElement('span');
        const variant = colours[status] || 'secondary';
        badge.className = `badge bg-${variant}`;
        badge.textContent = labels[status] || status;
        const cell = document.createElement('td');
        cell.appendChild(badge);
        return cell;
    }

    function buildAudioCell(path) {
        const cell = document.createElement('td');
        const strong = document.createElement('strong');
        const filename = typeof path === 'string' ? path.split(/[/\\]/).pop() : 'audio sample';
        strong.textContent = filename || 'audio sample';
        cell.appendChild(strong);
        if (path) {
            const meta = document.createElement('div');
            meta.className = 'text-muted small';
            meta.textContent = path;
            cell.appendChild(meta);
        }
        return cell;
    }

    function createTextCell(value) {
        const cell = document.createElement('td');
        cell.textContent = value || '—';
        return cell;
    }

    function formatMatchList(values) {
        if (!values || !values.length) {
            return '—';
        }
        return values.join(', ');
    }
})();
