/**
 * EAS Station - Frontend API Cache Module
 * Copyright (c) 2025 Timothy Kramer (KR8MER)
 * 
 * Provides client-side caching for API requests to reduce server load.
 * Implements time-based cache expiration and automatic cache invalidation.
 */

(function(window) {
    'use strict';

    /**
     * API Cache Manager
     * Caches fetch responses with configurable TTL per endpoint
     */
    class APICache {
        constructor() {
            this.cache = new Map();
            this.config = {
                // Default TTLs in milliseconds for different endpoint patterns
                '/api/audio/sources': 30000,        // 30s - frequently polled
                '/api/audio/metrics': 2000,         // 2s - VU meter data (matches server cache)
                '/api/audio/health': 15000,         // 15s - health data
                '/api/audio/devices': 30000,        // 30s - device list
                '/api/audio/alerts': 10000,         // 10s - active alerts
                '/api/system_status': 10000,        // 10s - system status
                '/api/system_health': 15000,        // 15s - health checks
                '/api/alerts': 30000,               // 30s - active alerts
                '/api/boundaries': 300000,          // 5min - static data
                '/api/receivers': 15000,            // 15s - receiver status
                'default': 15000                    // 15s - default for unknown endpoints
            };
        }

        /**
         * Get TTL for a given URL
         */
        getTTL(url) {
            // Extract path from full URL
            const path = new URL(url, window.location.origin).pathname;
            
            // Find matching config by path prefix
            for (const [pattern, ttl] of Object.entries(this.config)) {
                if (path.startsWith(pattern)) {
                    return ttl;
                }
            }
            
            return this.config.default;
        }

        /**
         * Generate cache key from URL and options
         */
        getCacheKey(url, options = {}) {
            const urlObj = new URL(url, window.location.origin);
            
            // Include method and query string in key
            const method = options.method || 'GET';
            const key = `${method}:${urlObj.pathname}${urlObj.search}`;
            
            return key;
        }

        /**
         * Get cached response if still valid
         */
        get(url, options = {}) {
            const key = this.getCacheKey(url, options);
            const cached = this.cache.get(key);
            
            if (!cached) {
                return null;
            }
            
            // Check if cache entry has expired
            const now = Date.now();
            if (now > cached.expiresAt) {
                this.cache.delete(key);
                return null;
            }
            
            return cached.data;
        }

        /**
         * Store response in cache
         */
        set(url, options = {}, data) {
            const key = this.getCacheKey(url, options);
            const ttl = this.getTTL(url);
            const expiresAt = Date.now() + ttl;
            
            this.cache.set(key, {
                data: data,
                expiresAt: expiresAt,
                createdAt: Date.now()
            });
        }

        /**
         * Clear cache entries matching a pattern
         */
        clear(pattern) {
            if (!pattern) {
                // Clear all cache
                this.cache.clear();
                return;
            }
            
            // Clear entries matching pattern
            for (const key of this.cache.keys()) {
                if (key.includes(pattern)) {
                    this.cache.delete(key);
                }
            }
        }

        /**
         * Clear cache for a specific URL
         */
        delete(url, options = {}) {
            const key = this.getCacheKey(url, options);
            this.cache.delete(key);
        }

        /**
         * Get cache statistics
         */
        getStats() {
            const now = Date.now();
            let validEntries = 0;
            let expiredEntries = 0;
            
            for (const [key, entry] of this.cache.entries()) {
                if (now > entry.expiresAt) {
                    expiredEntries++;
                } else {
                    validEntries++;
                }
            }
            
            return {
                totalEntries: this.cache.size,
                validEntries: validEntries,
                expiredEntries: expiredEntries,
                hitRate: this._hitRate || 0
            };
        }
    }

    // Create global cache instance
    const apiCache = new APICache();

    // Track cache statistics
    let cacheHits = 0;
    let cacheMisses = 0;

    /**
     * Cached fetch wrapper
     * Drop-in replacement for fetch() with automatic caching
     */
    async function cachedFetch(url, options = {}) {
        // Only cache GET requests
        const method = options.method || 'GET';
        if (method !== 'GET') {
            // For non-GET requests, clear related cache entries
            const urlObj = new URL(url, window.location.origin);
            apiCache.clear(urlObj.pathname);
            return fetch(url, options);
        }

        // Check cache first
        const cached = apiCache.get(url, options);
        if (cached) {
            cacheHits++;
            apiCache._hitRate = cacheHits / (cacheHits + cacheMisses);
            
            // Only log in development
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                console.debug(`[Cache HIT] ${url}`, apiCache.getStats());
            }
            
            // Return cached data as a Response-like object
            const urlObj = new URL(url, window.location.origin);
            const mockResponse = {
                ok: true,
                status: 200,
                statusText: 'OK',
                url: urlObj.href,
                type: 'basic',
                body: null,
                bodyUsed: false,
                headers: new Headers({ 'content-type': 'application/json' }),
                json: async function() { 
                    this.bodyUsed = true;
                    return cached;
                },
                text: async function() { 
                    this.bodyUsed = true;
                    return JSON.stringify(cached);
                },
                clone: function() {
                    // Create a new instance with the same data
                    return Object.assign({}, this, { bodyUsed: false });
                },
                _fromCache: true
            };
            return mockResponse;
        }

        // Cache miss - fetch from server
        cacheMisses++;
        apiCache._hitRate = cacheHits / (cacheHits + cacheMisses);
        
        // Only log in development
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            console.debug(`[Cache MISS] ${url}`, apiCache.getStats());
        }
        
        try {
            const response = await fetch(url, options);
            
            // Only cache successful responses
            if (response.ok && response.status === 200) {
                // Clone response before reading (responses can only be read once)
                const clonedResponse = response.clone();
                const data = await clonedResponse.json();
                apiCache.set(url, options, data);
            }
            
            return response;
        } catch (error) {
            console.error(`[Cache] Fetch error for ${url}:`, error);
            throw error;
        }
    }

    /**
     * Clear cache for specific endpoints or patterns
     */
    function clearCache(pattern) {
        apiCache.clear(pattern);
        console.info(`[Cache] Cleared cache${pattern ? ' for: ' + pattern : ''}`);
    }

    /**
     * Get cache statistics
     */
    function getCacheStats() {
        return apiCache.getStats();
    }

    /**
     * Configure cache TTL for specific endpoints
     */
    function configureCacheTTL(pattern, ttlMs) {
        apiCache.config[pattern] = ttlMs;
        console.info(`[Cache] Configured TTL for ${pattern}: ${ttlMs}ms`);
    }

    // Export to global scope
    window.cachedFetch = cachedFetch;
    window.clearAPICache = clearCache;
    window.getCacheStats = getCacheStats;
    window.configureCacheTTL = configureCacheTTL;
    window.apiCache = apiCache;

    // Log cache initialization
    console.info('[Cache] API caching initialized with default TTLs:', apiCache.config);

})(window);
