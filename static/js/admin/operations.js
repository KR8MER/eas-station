/**
 * Admin Panel - Operations Module
 * Handles backup/upgrade operations, manual imports, database optimization, and system maintenance
 */

/**
 * Truncate string to maxLength with ellipsis
 * @param {string} value - String to truncate
 * @param {number} maxLength - Maximum length
 * @returns {string} Truncated string
 */
function truncate(value, maxLength = 180) {
    if (!value || typeof value !== 'string') {
        return '';
    }
    if (value.length <= maxLength) {
        return value;
    }
    return `${value.slice(0, maxLength - 1)}…`;
}

/**
 * Format operation timestamp for display
 * @param {string} value - ISO timestamp
 * @returns {string|null} Formatted timestamp or null
 */
function formatOperationTimestamp(value) {
    if (!value) {
        return null;
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return null;
    }
    return parsed.toLocaleString();
}

/**
 * Escape HTML special characters
 * @param {string} value - String to escape
 * @returns {string} Escaped string
 */

/**
 * Set operation status indicator
 * @param {string} name - Operation name (backup, upgrade)
 * @param {Object} state - Operation state object
 */
function setOperationIndicator(name, state) {
    const statusElement = document.getElementById(`${name}Status`);
    const buttonElement = document.getElementById(`${name}Button`);
    if (!statusElement) {
        return;
    }
    if (buttonElement) {
        buttonElement.disabled = !!(state && state.running);
    }
    if (!state) {
        statusElement.textContent = 'Status unavailable.';
        return;
    }
    if (state.running) {
        const started = formatOperationTimestamp(state.last_started_at) || 'just now';
        statusElement.textContent = `⏳ Running (started ${started})`;
        return;
    }
    if (!state.last_status) {
        statusElement.textContent = 'No runs recorded yet.';
        return;
    }
    const finished = formatOperationTimestamp(state.last_finished_at);
    const message = state.last_message ? escapeHtml(state.last_message) : '';
    if (state.last_status === 'success') {
        const summary = finished ? `✅ Completed ${finished}` : '✅ Completed';
        statusElement.innerHTML = message ? `${summary}<br><span class="text-muted">${message}</span>` : summary;
        return;
    }
    if (state.last_status === 'failed') {
        const summary = finished ? `❌ Failed ${finished}` : '❌ Failed';
        let details = message;
        if (!details && state.last_error_output) {
            details = escapeHtml(truncate(state.last_error_output, 180));
        }
        statusElement.innerHTML = details ? `${summary}<br><span class="text-muted">${details}</span>` : summary;
        return;
    }
    statusElement.textContent = message || 'Status unknown.';
}

/**
 * Update operation status indicators
 * @param {Object} operations - Operations status object
 */
function updateOperationStatusIndicators(operations) {
    if (!operations || typeof operations !== 'object') {
        return;
    }
    window.latestOperationStatus = { ...window.latestOperationStatus, ...operations };
    setOperationIndicator('backup', window.latestOperationStatus.backup);
    setOperationIndicator('upgrade', window.latestOperationStatus.upgrade);
}

/**
 * Refresh operation status from server
 */
window.refreshOperationStatus = async function() {
    try {
        const response = await fetch('/admin/operations/status');
        if (!response.ok) {
            throw new Error('Failed to load operation status');
        }
        const result = await response.json();
        updateOperationStatusIndicators(result.operations);
    } catch (error) {
        console.warn('Unable to refresh operation status', error);
    }
};

/**
 * Run one-click backup operation
 */
window.runOneClickBackup = async function() {
    const labelInput = document.getElementById('backupLabel');
    const payload = {};
    if (labelInput && labelInput.value.trim()) {
        payload.label = labelInput.value.trim();
    }
    try {
        showStatus('💾 Starting backup…', 'info');
        const response = await fetch('/admin/operations/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (result.operation) {
            updateOperationStatusIndicators({ backup: result.operation });
        } else {
            window.refreshOperationStatus();
        }
        if (response.ok) {
            showStatus(`✅ ${result.message || 'Backup started.'}`, 'success');
        } else {
            showStatus(`❌ ${result.error || 'Backup request failed.'}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
};

/**
 * Run one-click upgrade operation
 */
window.runOneClickUpgrade = async function() {
    const payload = {};
    const skipMigrationsInput = document.getElementById('upgradeSkipMigrations');
    if (skipMigrationsInput && skipMigrationsInput.checked) {
        payload.skip_migrations = true;
    }
    const allowDirtyInput = document.getElementById('upgradeAllowDirty');
    if (allowDirtyInput && allowDirtyInput.checked) {
        payload.allow_dirty = true;
    }
    try {
        showStatus('⬆️ Starting upgrade…', 'info');
        const response = await fetch('/admin/operations/upgrade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (result.operation) {
            updateOperationStatusIndicators({ upgrade: result.operation });
        } else {
            window.refreshOperationStatus();
        }
        if (response.ok) {
            showStatus(`✅ ${result.message || 'Upgrade started.'}`, 'success', 8000);
        } else {
            showStatus(`❌ ${result.error || 'Upgrade request failed.'}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
};

/**
 * Render query details for manual import
 * @param {HTMLElement} container - Container element
 * @param {string} queryUrl - Query URL
 * @param {Object} params - Query parameters
 */
const renderQueryDetails = (container, queryUrl, params) => {
    if (!container || !queryUrl) {
        return;
    }
    const detailsContainer = document.createElement('div');
    detailsContainer.className = 'mt-3 alert alert-light border manual-import-query-details';
    const heading = document.createElement('div');
    heading.className = 'small fw-semibold text-uppercase text-muted';
    heading.textContent = 'NOAA API Query';
    detailsContainer.appendChild(heading);
    const urlWrapper = document.createElement('div');
    urlWrapper.className = 'small text-break';
    const urlCode = document.createElement('code');
    urlCode.textContent = queryUrl;
    urlWrapper.appendChild(urlCode);
    detailsContainer.appendChild(urlWrapper);
    const paramEntries = params && typeof params === 'object' ? Object.entries(params) : [];
    if (paramEntries.length > 0) {
        const list = document.createElement('dl');
        list.className = 'row small mb-0 mt-2';
        paramEntries.forEach(([key, value]) => {
            const dt = document.createElement('dt');
            dt.className = 'col-sm-4';
            dt.textContent = key;
            const dd = document.createElement('dd');
            dd.className = 'col-sm-8 text-break';
            const codeEl = document.createElement('code');
            codeEl.textContent = String(value);
            dd.appendChild(codeEl);
            list.appendChild(dt);
            list.appendChild(dd);
        });
        detailsContainer.appendChild(list);
    } else {
        const noParams = document.createElement('div');
        noParams.className = 'small text-muted mt-2 mb-0';
        noParams.textContent = 'No additional query parameters were sent.';
        detailsContainer.appendChild(noParams);
    }
    container.appendChild(detailsContainer);
};

/**
 * Manual import alert from NOAA API
 */
window.manualImportAlert = async function() {
    const identifierInput = document.getElementById('manualAlertIdentifier');
    const startInput = document.getElementById('manualAlertStart');
    const endInput = document.getElementById('manualAlertEnd');
    const areaInput = document.getElementById('manualAlertArea');
    const eventInput = document.getElementById('manualAlertEvent');
    const limitInput = document.getElementById('manualAlertLimit');
    const resultsDiv = document.getElementById('manualImportResults');
    if (resultsDiv) {
        resultsDiv.textContent = '';
    }
    const identifier = identifierInput ? identifierInput.value.trim() : '';
    const startValue = startInput ? startInput.value : '';
    const endValue = endInput ? endInput.value : '';
    const rawState = areaInput ? areaInput.value.trim().toUpperCase() : '';
    const sanitizedState = rawState.replace(/[^A-Z]/g, '').slice(0, 2);
    const eventFilter = eventInput ? eventInput.value.trim() : '';
    const limit = limitInput ? parseInt(limitInput.value, 10) : 5;
    const normalizeDate = (value) => {
        if (!value) {
            return null;
        }
        const parsed = Date.parse(value);
        if (Number.isNaN(parsed)) {
            return null;
        }
        return new Date(parsed).toISOString();
    };
    const startIso = normalizeDate(startValue);
    const endIso = normalizeDate(endValue);
    if (!identifier && (!startIso || !endIso)) {
        showStatus('Please provide an alert identifier or both start and end timestamps.', 'warning');
        return;
    }
    if (!identifier) {
        if (!sanitizedState || sanitizedState.length !== 2) {
            showStatus('Provide the two-letter state code when searching without an identifier.', 'warning');
            return;
        }
    } else if (sanitizedState && sanitizedState.length !== 2) {
        showStatus('State filters must use the two-letter postal abbreviation.', 'warning');
        return;
    }
    const payload = {
        identifier,
        event: eventFilter,
        limit: Number.isNaN(limit) ? 5 : limit,
    };
    if (sanitizedState && sanitizedState.length === 2) {
        payload.area = sanitizedState;
    }
    if (startIso) {
        payload.start = startIso;
    }
    if (endIso) {
        payload.end = endIso;
    }
    if (resultsDiv) {
        resultsDiv.textContent = 'Contacting NOAA API…';
    }
    try {
        const response = await fetch('/admin/import_alert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        let rawBody = '';
        let result = null;
        try {
            rawBody = await response.text();
            result = rawBody ? JSON.parse(rawBody) : {};
        } catch (parseError) {
            console.error('Manual NOAA import response was not valid JSON', parseError, rawBody);
        }
        if (response.ok && result && !result.error) {
            const summaryParts = [];
            if (typeof result.inserted === 'number') {
                summaryParts.push(`${result.inserted} inserted`);
            }
            if (typeof result.updated === 'number') {
                summaryParts.push(`${result.updated} updated`);
            }
            if (typeof result.skipped === 'number' && result.skipped > 0) {
                summaryParts.push(`${result.skipped} skipped`);
            }
            const identifiers = (result.identifiers || []).map(id => `<code>${escapeHtml(id)}</code>`).join(', ');
            showStatus(`✅ ${result.message || 'Alert import completed successfully.'}`, 'success');
            if (resultsDiv) {
                resultsDiv.innerHTML = `
                    ${summaryParts.length ? `<div>${summaryParts.join(' • ')}</div>` : ''}
                    ${identifiers ? `<div class="mt-1">Identifiers: ${identifiers}</div>` : ''}
                `;
                renderQueryDetails(resultsDiv, result.query_url, result.params);
            }
            if (result.query_url) {
                console.info('Manual NOAA import executed', {
                    url: result.query_url,
                    params: result.params,
                });
            }
        } else {
            const fallbackMessage = rawBody && rawBody.trim() ? rawBody.trim() : 'Manual alert import failed.';
            const message = (result && result.error) || fallbackMessage;
            showStatus(`❌ ${message}`, response.status === 404 ? 'warning' : 'danger');
            if (resultsDiv) {
                resultsDiv.textContent = '';
                if (result && result.query_url) {
                    renderQueryDetails(resultsDiv, result.query_url, result.params);
                }
            }
        }
    } catch (error) {
        showStatus(`❌ NOAA import failed: ${error.message}`, 'danger');
        if (resultsDiv) {
            resultsDiv.textContent = '';
        }
    }
};

/**
 * Optimize database
 */
window.optimizeDatabase = async function() {
    try {
        showStatus('🔧 Optimizing database...', 'info');
        const response = await fetch('/admin/optimize_db', { method: 'POST' });
        const result = await response.json();
        if (response.ok) {
            showStatus(`✅ ${result.message}`, 'success');
        } else {
            showStatus(`❌ ${result.error}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
};

/**
 * Open environment configuration editor
 */
window.openEnvEditor = async function() {
    try {
        showStatus('📖 Loading environment configuration...', 'info');
        const response = await fetch('/admin/env_config', { method: 'GET' });

        if (response.status === 401) {
            window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
            return;
        }

        const result = await response.json().catch(() => ({}));

        if (response.ok) {
            document.getElementById('envContent').value = result.content || '';
            const modal = new bootstrap.Modal(document.getElementById('envEditorModal'));
            modal.show();
            showStatus('✅ Configuration loaded', 'success');
        } else {
            showStatus(`❌ ${result.error || 'Failed to load configuration'}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Failed to load configuration: ${error.message}`, 'danger');
    }
};

/**
 * Save environment configuration
 */
window.saveEnvConfig = async function() {
    const content = document.getElementById('envContent').value;

    if (!content.trim()) {
        showStatus('❌ Configuration cannot be empty', 'danger');
        return;
    }

    if (!confirm('⚠️ Save changes to stack.env?\n\n' +
                'This will:\n' +
                '- Create a backup (stack.env.backup)\n' +
                '- Update the configuration file\n' +
                '- REQUIRE application restart\n\n' +
                'Are you sure?')) {
        return;
    }

    try {
        showStatus('💾 Saving configuration...', 'info');
        const response = await fetch('/admin/env_config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
            },
            body: JSON.stringify({ content })
        });

        if (response.status === 401) {
            window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
            return;
        }

        const result = await response.json().catch(() => ({}));

        if (response.ok) {
            showStatus(`✅ ${result.message || 'Configuration saved'}`, 'success');
            const modal = bootstrap.Modal.getInstance(document.getElementById('envEditorModal'));
            if (modal) modal.hide();

            setTimeout(() => {
                showStatus('⚠️ Remember to restart the application for changes to take effect!', 'warning');
            }, 2000);
        } else {
            showStatus(`❌ ${result.error || 'Failed to save configuration'}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Failed to save configuration: ${error.message}`, 'danger');
    }
};

/**
 * Recalculate alert-boundary intersections
 */
window.recalculateIntersections = async function() {
    showConfirmation({
        title: 'Recalculate Intersections',
        message: 'This will recalculate all alert-boundary intersections.',
        warning: 'This may take several minutes for large datasets.',
        type: 'info',
        confirmText: 'Recalculate',
        onConfirm: async () => {
            try {
                showStatus('🔗 Recalculating intersections...', 'info');
                const response = await fetch('/admin/recalculate_intersections', { method: 'POST' });
                const result = await response.json();
                if (response.ok) {
                    showStatus(`✅ ${result.success}`, 'success');
                } else {
                    showStatus(`❌ ${result.error}`, 'danger');
                }
            } catch (error) {
                showStatus(`❌ Error: ${error.message}`, 'danger');
            }
        }
    });
};

/**
 * Check database health
 */
window.checkDatabaseHealth = async function() {
    try {
        showStatus('🔍 Checking database health...', 'info');
        const response = await fetch('/admin/check_db_health');
        const result = await response.json();
        if (response.ok) {
            let healthHtml = '<div class="alert alert-info"><h6>Database Health Report:</h6>';
            healthHtml += `<p><strong>Connectivity:</strong> ${result.connectivity}</p>`;
            healthHtml += `<p><strong>Database Size:</strong> ${result.database_size}</p>`;
            healthHtml += `<p><strong>Active Connections:</strong> ${result.active_connections}</p>`;
            healthHtml += '</div>';
            showStatus(healthHtml, 'info', 10000);
        } else {
            showStatus(`❌ ${result.error}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
};

/**
 * Trigger CAP poll
 */
window.triggerCAPPoll = async function() {
    try {
        showStatus('📡 Triggering CAP poll...', 'info');
        const response = await fetch('/admin/trigger_poll', { method: 'POST' });
        const result = await response.json();
        if (response.ok) {
            showStatus(`✅ ${result.message}`, 'success');
        } else {
            showStatus(`❌ ${result.error}`, 'danger');
        }
    } catch (error) {
        showStatus(`❌ Error: ${error.message}`, 'danger');
    }
};
