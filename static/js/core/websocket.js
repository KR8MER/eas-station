/**
 * EAS Station - WebSocket Client Module
 * Centralized WebSocket connection management with automatic fallback to polling
 *
 * This module replaces setInterval-based polling with WebSocket real-time updates.
 * When WebSocket is unavailable, it gracefully falls back to HTTP polling.
 */

(function(window) {
    'use strict';

    // WebSocket connection state
    let socket = null;
    let isConnected = false;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 5;
    const RECONNECT_DELAY_MS = 1000;

    // Event subscribers: { eventName: [{ callback, fallbackFn, fallbackInterval, intervalHandle }] }
    const subscribers = {};

    // Polling fallback intervals (ms) for each event type
    const FALLBACK_INTERVALS = {
        // Audio monitoring events
        'audio_monitoring_update': 2000,      // 2s - VU meters, EAS monitor
        'audio_sources_update': 30000,        // 30s - source list
        'audio_health_update': 30000,         // 30s - health dashboard

        // System events
        'system_health_update': 60000,        // 60s - system health indicator
        'system_status_update': 60000,        // 60s - system status

        // Operations events
        'operation_status_update': 10000,     // 10s - operation status

        // Settings events
        'ipaws_status_update': 30000,         // 30s - IPAWS status
        'radio_status_update': 15000,         // 15s - radio diagnostics
        'gpio_status_update': 3000,           // 3s - GPIO pin states
        'zigbee_status_update': 10000,        // 10s - Zigbee devices

        // LED/Display events
        'led_status_update': 30000,           // 30s - LED status
        'display_preview_update': 1000,       // 1s - display preview

        // Analytics events
        'analytics_update': 30000,            // 30s - analytics dashboard

        // Alert events
        'alert_verification_update': 10000,   // 10s - alert verification
        'alerts_update': 5000,                // 5s - active CAP alert list

        // Log events
        'logs_update': 10000,                 // 10s - log viewer

        // Airchain broadcast state (global countdown timer)
        'broadcast_state_update': 1000,       // 1s - broadcast active state
    };

    // API endpoints for polling fallback
    const FALLBACK_ENDPOINTS = {
        'audio_monitoring_update': '/api/audio/metrics',
        'audio_sources_update': '/api/audio/sources',
        'audio_health_update': '/api/audio/health',
        'system_health_update': '/api/system_status',
        'system_status_update': '/api/system_status',
        'operation_status_update': '/admin/operations/status',
        'ipaws_status_update': '/api/ipaws/status',
        'radio_status_update': '/api/radio/diagnostics',
        'gpio_status_update': '/api/gpio/status',
        'zigbee_status_update': '/api/zigbee/devices',
        'led_status_update': '/api/led/status',
        'display_preview_update': '/api/displays/preview',
        'analytics_update': '/api/analytics/dashboard',
        'alert_verification_update': '/api/alerts/verification/status',
        'alerts_update': '/api/alerts',
        'logs_update': '/api/logs/recent',
    };

    /**
     * Initialize WebSocket connection
     * Call this once when the page loads
     */
    function init() {
        if (typeof io === 'undefined') {
            console.warn('[EASWebSocket] Socket.IO not available - using polling mode only');
            startAllFallbackPolling();
            return;
        }

        connect();
    }

    /**
     * Connect to WebSocket server
     */
    function connect() {
        if (socket && socket.connected) {
            return;
        }

        try {
            socket = io({
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionDelay: RECONNECT_DELAY_MS,
                reconnectionAttempts: MAX_RECONNECT_ATTEMPTS,
                timeout: 5000,
            });

            socket.on('connect', onConnect);
            socket.on('disconnect', onDisconnect);
            socket.on('connect_error', onConnectError);

            // Register all known event handlers
            registerEventHandlers();

            console.info('[EASWebSocket] Initializing connection...');
        } catch (error) {
            console.error('[EASWebSocket] Failed to initialize:', error);
            startAllFallbackPolling();
        }
    }

    /**
     * Handle successful connection
     */
    function onConnect() {
        console.info('[EASWebSocket] Connected - real-time updates active');
        isConnected = true;
        reconnectAttempts = 0;

        // Stop all polling since WebSocket is now active
        stopAllFallbackPolling();

        // Dispatch custom event for pages that need to know
        window.dispatchEvent(new CustomEvent('eas-websocket-connected'));
    }

    /**
     * Handle disconnection
     */
    function onDisconnect(reason) {
        console.warn('[EASWebSocket] Disconnected:', reason);
        isConnected = false;

        // Start fallback polling for subscribed events
        startAllFallbackPolling();

        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('eas-websocket-disconnected', { detail: { reason } }));
    }

    /**
     * Handle connection error
     */
    function onConnectError(error) {
        console.error('[EASWebSocket] Connection error:', error.message || error);
        reconnectAttempts++;

        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.warn('[EASWebSocket] Max reconnection attempts reached - using polling mode');
            startAllFallbackPolling();
        }
    }

    /**
     * Register event handlers for all known WebSocket events
     */
    function registerEventHandlers() {
        if (!socket) return;

        // Listen for all known event types
        Object.keys(FALLBACK_INTERVALS).forEach(eventName => {
            socket.on(eventName, (data) => {
                notifySubscribers(eventName, data);
            });
        });
    }

    /**
     * Subscribe to a WebSocket event with optional polling fallback
     *
     * @param {string} eventName - The WebSocket event name
     * @param {function} callback - Function to call when event is received
     * @param {object} options - Optional configuration
     * @param {function} options.fallbackFn - Custom polling function (called when WebSocket unavailable)
     * @param {number} options.fallbackInterval - Custom polling interval in ms
     * @returns {function} Unsubscribe function
     */
    function subscribe(eventName, callback, options = {}) {
        if (!subscribers[eventName]) {
            subscribers[eventName] = [];
        }

        const subscription = {
            callback,
            fallbackFn: options.fallbackFn || null,
            fallbackInterval: options.fallbackInterval || FALLBACK_INTERVALS[eventName] || 30000,
            intervalHandle: null,
        };

        subscribers[eventName].push(subscription);

        // If not connected, start polling immediately for this subscriber
        if (!isConnected && subscription.fallbackFn) {
            startFallbackPolling(eventName, subscription);
        }

        // Return unsubscribe function
        return () => unsubscribe(eventName, subscription);
    }

    /**
     * Unsubscribe from an event
     */
    function unsubscribe(eventName, subscription) {
        if (!subscribers[eventName]) return;

        // Stop polling for this subscription
        if (subscription.intervalHandle) {
            clearInterval(subscription.intervalHandle);
            subscription.intervalHandle = null;
        }

        // Remove from subscribers list
        const index = subscribers[eventName].indexOf(subscription);
        if (index > -1) {
            subscribers[eventName].splice(index, 1);
        }
    }

    /**
     * Notify all subscribers of an event
     */
    function notifySubscribers(eventName, data) {
        const eventSubscribers = subscribers[eventName];
        if (!eventSubscribers || eventSubscribers.length === 0) return;

        eventSubscribers.forEach(sub => {
            try {
                sub.callback(data);
            } catch (error) {
                console.error(`[EASWebSocket] Error in subscriber callback for ${eventName}:`, error);
            }
        });
    }

    /**
     * Start fallback polling for a specific subscription
     */
    function startFallbackPolling(eventName, subscription) {
        if (subscription.intervalHandle) return; // Already polling
        if (!subscription.fallbackFn) return; // No fallback function

        // Execute immediately
        try {
            subscription.fallbackFn();
        } catch (error) {
            console.debug(`[EASWebSocket] Error in initial fallback for ${eventName}:`, error);
        }

        // Start interval
        subscription.intervalHandle = setInterval(() => {
            try {
                subscription.fallbackFn();
            } catch (error) {
                console.debug(`[EASWebSocket] Error in fallback polling for ${eventName}:`, error);
            }
        }, subscription.fallbackInterval);
    }

    /**
     * Start fallback polling for all subscribed events
     */
    function startAllFallbackPolling() {
        Object.keys(subscribers).forEach(eventName => {
            subscribers[eventName].forEach(subscription => {
                startFallbackPolling(eventName, subscription);
            });
        });
    }

    /**
     * Stop fallback polling for all subscriptions
     */
    function stopAllFallbackPolling() {
        Object.keys(subscribers).forEach(eventName => {
            subscribers[eventName].forEach(subscription => {
                if (subscription.intervalHandle) {
                    clearInterval(subscription.intervalHandle);
                    subscription.intervalHandle = null;
                }
            });
        });
    }

    /**
     * Create a simple polling fallback function for an API endpoint
     *
     * @param {string} endpoint - API endpoint to poll
     * @param {function} callback - Function to call with response data
     * @returns {function} Polling function
     */
    function createPollingFallback(endpoint, callback) {
        return async function() {
            try {
                const fetchFunc = window.cachedFetch || fetch;
                const response = await fetchFunc(endpoint, { cache: 'no-store' });
                if (response.ok) {
                    const data = await response.json();
                    callback(data);
                }
            } catch (error) {
                console.debug(`[EASWebSocket] Polling error for ${endpoint}:`, error);
            }
        };
    }

    /**
     * Emit an event to the server (bidirectional communication)
     *
     * @param {string} eventName - Event name
     * @param {*} data - Data to send
     */
    function emit(eventName, data) {
        if (socket && isConnected) {
            socket.emit(eventName, data);
        } else {
            console.warn(`[EASWebSocket] Cannot emit ${eventName} - not connected`);
        }
    }

    /**
     * Check if WebSocket is currently connected
     * @returns {boolean}
     */
    function connected() {
        return isConnected;
    }

    /**
     * Get the underlying socket instance (for advanced usage)
     * @returns {Socket|null}
     */
    function getSocket() {
        return socket;
    }

    /**
     * Disconnect and cleanup
     */
    function disconnect() {
        stopAllFallbackPolling();
        if (socket) {
            socket.disconnect();
            socket = null;
        }
        isConnected = false;
    }

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // Small delay to ensure Socket.IO script is loaded
        setTimeout(init, 100);
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', disconnect);

    // Export API
    window.EASWebSocket = {
        init,
        connect,
        disconnect,
        subscribe,
        emit,
        connected,
        getSocket,
        createPollingFallback,
        FALLBACK_INTERVALS,
        FALLBACK_ENDPOINTS,
    };

})(window);
