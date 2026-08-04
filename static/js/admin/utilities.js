/**
 * Admin Panel - Utilities Module
 * Shared utility functions for keyboard shortcuts, confirmations, status messages, and formatting
 */

/**
 * Setup keyboard shortcuts for admin panel
 */
window.setupKeyboardShortcuts = function() {
    document.addEventListener('keydown', function(e) {
        if (e.altKey) {
            switch(e.key) {
                case '1': switchTab('upload-tab'); break;
                case '2': switchTab('preview-tab'); break;
                case '3': switchTab('manage-tab'); break;
                case '4': switchTab('operations-tab'); break;
                case '5': switchTab('alerts-tab'); break;
                case '6': switchTab('location-tab'); break;
                case '8': switchTab('eas-tab'); break;
                case '9': switchTab('users-tab'); break;
                case 'r': e.preventDefault(); location.reload(); break;
            }
        }
    });
};

/**
 * Switch to a specific tab
 * @param {string} tabId - Tab element ID
 */
function switchTab(tabId) {
    const tab = document.getElementById(tabId);
    if (tab) {
        tab.click();
    }
}

/**
 * Show confirmation dialog
 * @param {Object} options - Confirmation options
 * @param {string} options.title - Dialog title
 * @param {string} options.message - Confirmation message
 * @param {string} options.warning - Warning text (optional)
 * @param {string} options.type - Bootstrap alert type (default: 'danger')
 * @param {string} options.confirmText - Confirm button text (default: 'Confirm')
 * @param {string} options.cancelText - Cancel button text (default: 'Cancel')
 * @param {Function} options.onConfirm - Callback function on confirm
 */
window.showConfirmation = function(options) {
    const { title, message, warning, type = 'danger', confirmText = 'Confirm', cancelText = 'Cancel', onConfirm } = options;
    const body = document.getElementById('confirmationBody');
    const footer = document.getElementById('confirmationFooter');
    body.innerHTML = `
        <div class="alert alert-${type}">
            <h6>${message}</h6>
            ${warning ? `<p class="mb-0"><strong>⚠️ Warning:</strong> ${warning}</p>` : ''}
        </div>
    `;
    footer.innerHTML = `
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${cancelText}</button>
        <button type="button" class="btn btn-${type}" id="confirmButton">${confirmText}</button>
    `;
    document.getElementById('confirmButton').onclick = function() {
        window.confirmationModal.hide();
        if (onConfirm) onConfirm();
    };
    window.confirmationModal.show();
};

/**
 * Show multi-step confirmation dialog
 * @param {Object} options - Multi-step options
 * @param {Array} options.steps - Array of step objects
 * @param {Function} options.onComplete - Callback function on completion
 */
window.showMultiStepConfirmation = function(options) {
    const { steps, onComplete } = options;
    let currentStep = 0;
    
    function showStep() {
        const step = steps[currentStep];
        const body = document.getElementById('confirmationBody');
        const footer = document.getElementById('confirmationFooter');
        body.innerHTML = `
            <div class="alert alert-danger">
                <h6>${step.message}</h6>
                ${step.warning ? `<p class="mb-2"><strong>⚠️ Warning:</strong> ${step.warning}</p>` : ''}
                ${step.textConfirmation ? `
                    <div class="mt-3">
                        <label class="form-label fw-bold">Type "${step.textConfirmation}" to confirm:</label>
                        <input type="text" class="form-control" id="textConfirmInput" placeholder="Type confirmation text">
                    </div>
                ` : ''}
            </div>
        `;
        footer.innerHTML = `
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-danger" id="stepConfirmButton">
                ${currentStep === steps.length - 1 ? 'CONFIRM DELETION' : 'Continue'}
            </button>
        `;
        document.getElementById('stepConfirmButton').onclick = function() {
            if (step.textConfirmation) {
                const input = document.getElementById('textConfirmInput');
                if (input.value !== step.textConfirmation) {
                    showStatus('Text confirmation does not match. Please try again.', 'danger');
                    return;
                }
            }
            currentStep++;
            if (currentStep < steps.length) {
                showStep();
            } else {
                window.confirmationModal.hide();
                if (onComplete) onComplete();
            }
        };
    }
    
    showStep();
    window.confirmationModal.show();
};

/**
 * Show status message
 * @param {string} message - Status message (can include HTML)
 * @param {string} type - Bootstrap alert type (info, success, danger, warning)
 * @param {number} duration - Duration in milliseconds (0 = don't auto-hide)
 */
window.showStatus = function(message, type = 'info', duration = 5000) {
    const statusDiv = document.getElementById('operationStatus');
    if (!statusDiv) {
        return;
    }
    statusDiv.className = `alert alert-${type}`;
    statusDiv.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'danger' ? 'exclamation-triangle' : 'info-circle'}"></i>
        ${message}
    `;
    statusDiv.style.display = 'block';
    if (type === 'success' && duration > 0) {
        setTimeout(() => {
            statusDiv.style.display = 'none';
        }, duration);
    }
};

/**
 * Format date/time for display
 * @param {string} value - ISO timestamp
 * @returns {string} Formatted HTML string
 */
function formatDateTimeDisplay(value) {
    if (!value) {
        return '<span class="text-muted">—</span>';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return escapeHtml(String(value));
    }
    return escapeHtml(parsed.toLocaleString());
}

/**
 * Convert ISO timestamp to local input value
 * @param {string} value - ISO timestamp
 * @returns {string} Local datetime-local input value
 */
function isoToLocalInputValue(value) {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return '';
    }
    const offsetMinutes = parsed.getTimezoneOffset();
    const localTime = new Date(parsed.getTime() - offsetMinutes * 60000);
    return localTime.toISOString().slice(0, 16);
}

/**
 * Convert local input value to ISO timestamp
 * @param {string} value - Local datetime-local input value
 * @returns {string|null} ISO timestamp or null
 */
function localInputToIso(value) {
    if (!value) {
        return null;
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return null;
    }
    const offsetMinutes = parsed.getTimezoneOffset();
    const utcTime = new Date(parsed.getTime() - offsetMinutes * 60000);
    return utcTime.toISOString();
}

/**
 * Set input element value
 * @param {string} id - Element ID
 * @param {string} value - Value to set
 */
function setInputValue(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.value = value || '';
    }
}

/**
 * Escape HTML special characters (also available in operations.js, duplicated here for independence)
 * @param {string} value - String to escape
 * @returns {string} Escaped string
 */

// Export functions to window for global access
window.formatDateTimeDisplay = formatDateTimeDisplay;
window.isoToLocalInputValue = isoToLocalInputValue;
window.localInputToIso = localInputToIso;
window.setInputValue = setInputValue;
// Alias only. The name exists because operations.js and utilities.js each
// used to declare their own top-level `escapeHtml`, which clobbered each other
// and the global; both are gone now and this simply forwards to the canonical
// implementation in js/core/utils.js.
window.escapeHtmlAdmin = window.escapeHtml;
