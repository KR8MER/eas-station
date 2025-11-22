/**
 * EAS Station - System Health Monitoring Module
 * Monitors system health status and updates UI indicators
 */

(function() {
    'use strict';

    let systemStatusBannerState = {
        message: null,
        severity: null,
        dismissed: false,
    };

    /**
     * Update system status banner
     */
    function updateSystemStatusBanner(severity, summary, label) {
        const banner = document.getElementById('system-status-banner');
        const bannerTitle = document.getElementById('system-status-banner-title');
        const bannerText = document.getElementById('system-status-banner-text');

        if (!banner || !bannerTitle || !bannerText) {
            return;
        }

        const normalizedSeverity = (severity || '').toString().toLowerCase();

        // Hide banner for healthy status
        if (!normalizedSeverity || ['healthy', 'online'].includes(normalizedSeverity)) {
            banner.classList.add('d-none');
            banner.classList.remove('alert-warning', 'alert-danger');
            systemStatusBannerState.message = null;
            systemStatusBannerState.severity = null;
            systemStatusBannerState.dismissed = false;
            return;
        }

        const displaySeverity = normalizedSeverity === 'critical' ? 'critical' : 'warning';
        const message = (summary || label || 'System status update').toString();

        // Don't re-show if user dismissed this exact message
        if (
            systemStatusBannerState.dismissed &&
            systemStatusBannerState.message === message &&
            systemStatusBannerState.severity === displaySeverity
        ) {
            return;
        }

        // Update banner styling and content
        banner.classList.remove('alert-warning', 'alert-danger');
        banner.classList.add(displaySeverity === 'critical' ? 'alert-danger' : 'alert-warning');
        bannerTitle.textContent = displaySeverity === 'critical' ? 'Critical System Notice' : 'System Warning';
        bannerText.textContent = message;
        banner.classList.remove('d-none');

        systemStatusBannerState.message = message;
        systemStatusBannerState.severity = displaySeverity;
        systemStatusBannerState.dismissed = false;
    }

    /**
     * Check system health status
     */
    async function checkSystemHealth() {
        try {
            const fetchFunc = window.cachedFetch || fetch;
            const response = await fetchFunc('/api/system_status');
            const data = await response.json();

            const healthDot = document.getElementById('system-health-dot');
            const healthText = document.getElementById('system-health-text');
            const indicator = document.getElementById('system-health-indicator');

            if (healthDot && healthText) {
                const statusKey = (data.status || '').toString().toLowerCase();
                const statusStyles = {
                    healthy: { className: 'health-dot health-good', label: 'Healthy' },
                    online: { className: 'health-dot health-good', label: 'Healthy' },
                    warning: { className: 'health-dot health-warning', label: 'Warning' },
                    critical: { className: 'health-dot health-critical', label: 'Critical' },
                };

                const fallback = { className: 'health-dot health-warning', label: 'Status' };
                const style = statusStyles[statusKey] || fallback;
                const summary = (data.status_summary || '').toString().trim();

                healthDot.className = style.className;

                const isHealthy = ['healthy', 'online'].includes(statusKey);
                const displayText = isHealthy ? (summary || 'System OK') : style.label;

                healthText.textContent = displayText;

                if (indicator) {
                    const indicatorMessage = summary || displayText;
                    indicator.setAttribute('title', indicatorMessage);
                    indicator.setAttribute('aria-label', `System status: ${indicatorMessage}`);

                    indicator.classList.remove('status-healthy', 'status-warning', 'status-critical');
                    const indicatorState = statusKey === 'critical'
                        ? 'status-critical'
                        : statusKey === 'warning'
                            ? 'status-warning'
                            : ['healthy', 'online'].includes(statusKey)
                                ? 'status-healthy'
                                : 'status-warning';
                    indicator.classList.add(indicatorState);
                }

                updateSystemStatusBanner(statusKey, summary, style.label);
            }
        } catch (error) {
            console.warn('Could not check system health:', error);

            const healthDot = document.getElementById('system-health-dot');
            const healthText = document.getElementById('system-health-text');
            const indicator = document.getElementById('system-health-indicator');

            if (healthDot && healthText) {
                healthDot.className = 'health-dot health-warning';
                const fallbackText = 'Status unavailable';
                healthText.textContent = fallbackText;

                if (indicator) {
                    indicator.setAttribute('title', fallbackText);
                    indicator.setAttribute('aria-label', `System status: ${fallbackText}`);
                    indicator.classList.remove('status-healthy', 'status-warning', 'status-critical');
                    indicator.classList.add('status-warning');
                }
            }

            updateSystemStatusBanner('warning', 'Unable to contact the system status service.', 'Warning');
        }
    }

    /**
     * Setup banner close handler
     */
    function setupBannerCloseHandler() {
        const bannerCloseButton = document.getElementById('system-status-banner-close');
        if (bannerCloseButton) {
            bannerCloseButton.addEventListener('click', function() {
                const banner = document.getElementById('system-status-banner');
                if (banner) {
                    banner.classList.add('d-none');
                }
                systemStatusBannerState.dismissed = true;
            });
        }
    }

    /**
     * Initialize health monitoring
     */
    function init() {
        // Check immediately
        checkSystemHealth();

        // REDUCED: Check every 60 seconds instead of 30 (cache serves intermediate requests)
        setInterval(checkSystemHealth, 60000);

        // Setup banner close handler
        setupBannerCloseHandler();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export functions
    window.EASHealth = {
        checkSystemHealth: checkSystemHealth,
        updateSystemStatusBanner: updateSystemStatusBanner
    };
})();
