/**
 * EAS Station - API Client Module
 * Handles API requests with CSRF token management
 */

(function() {
    'use strict';

    // Store CSRF token globally
    window.CSRF_TOKEN = window.CSRF_TOKEN || null;

    /**
     * Override native fetch to automatically inject CSRF token
     */
    function setupCSRFProtection() {
        const originalFetch = window.fetch;
        window.fetch = function(input, init) {
            init = init || {};
            const method = (init.method || 'GET').toUpperCase();

            // Add CSRF token for state-changing requests
            if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
                const headers = new Headers(init.headers || {});
                if (window.CSRF_TOKEN && !headers.has('X-CSRF-Token')) {
                    headers.set('X-CSRF-Token', window.CSRF_TOKEN);
                }
                init.headers = headers;
            }

            return originalFetch.call(this, input, init);
        };
    }

    /**
     * Add CSRF token to forms
     */
    function injectCSRFTokenToForms() {
        document.querySelectorAll('form').forEach((form) => {
            const method = (form.getAttribute('method') || 'GET').toUpperCase();
            if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
                return;
            }
            if (!form.querySelector('input[name="csrf_token"]')) {
                const tokenField = document.createElement('input');
                tokenField.type = 'hidden';
                tokenField.name = 'csrf_token';
                tokenField.value = window.CSRF_TOKEN || '';
                form.appendChild(tokenField);
            }
        });
    }

    /**
     * Handle form submission to ensure CSRF token is present
     */
    function setupFormSubmitHandler() {
        document.addEventListener('submit', function(event) {
            const form = event.target;
            if (!(form instanceof HTMLFormElement)) {
                return;
            }

            const method = (form.getAttribute('method') || 'GET').toUpperCase();
            if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
                return;
            }

            let tokenField = form.querySelector('input[name="csrf_token"]');
            if (!tokenField) {
                tokenField = document.createElement('input');
                tokenField.type = 'hidden';
                tokenField.name = 'csrf_token';
                form.appendChild(tokenField);
            }
            tokenField.value = window.CSRF_TOKEN || '';
        }, true);
    }

    /**
     * Initialize API client
     */
    function init() {
        setupCSRFProtection();
        injectCSRFTokenToForms();
        setupFormSubmitHandler();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export utility functions
    window.EASApi = {
        init: init,
        injectCSRFTokenToForms: injectCSRFTokenToForms
    };
})();
