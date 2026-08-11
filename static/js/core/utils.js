(function() {
    'use strict';

    /**
     * The station's configured timezone, stamped onto <body data-timezone> by
     * base.html from LocationSettings.timezone.
     *
     * These clocks used to hardcode 'America/New_York'. The station timezone is
     * configurable (the setup wizard offers 22 US zones, Honolulu and Guam
     * included), so a non-Eastern station got a navbar clock that was hours off
     * *and* labelled itself EDT — the `timeZoneName: 'short'` below means a
     * wrong zone is stated outright rather than left ambiguous.
     *
     * Returns undefined when the attribute is missing or unusable, which makes
     * Intl fall back to the browser's zone — the best available guess, and what
     * the rest of the UI's toLocaleString() calls already do.
     */
    function getStationTimeZone() {
        const configured = document.body && document.body.dataset
            ? document.body.dataset.timezone
            : null;
        if (!configured) {
            return undefined;
        }
        // A bad IANA name makes toLocaleString throw a RangeError, which would
        // kill the 1s interval and freeze every clock on the page.
        try {
            new Intl.DateTimeFormat('en-US', { timeZone: configured });
            return configured;
        } catch (err) {
            return undefined;
        }
    }

    function updateCurrentTime() {
        const now = new Date();
        const timeZone = getStationTimeZone();
        const timeString = now.toLocaleString('en-US', {
            timeZone: timeZone,
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            timeZoneName: 'short'
        });
        const timeElement = document.getElementById('current-time');
        if (timeElement) {
            timeElement.textContent = timeString;
        }

        // Compact live header clock (navbar) — split time/date readouts.
        const navClockTime = document.getElementById('navbar-clock-time');
        if (navClockTime) {
            navClockTime.textContent = now.toLocaleString('en-US', {
                timeZone: timeZone,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            });
        }
        const navClockDate = document.getElementById('navbar-clock-date');
        if (navClockDate) {
            navClockDate.textContent = now.toLocaleString('en-US', {
                timeZone: timeZone,
                month: 'short',
                day: 'numeric',
                timeZoneName: 'short'
            });
        }
    }

    function exportToExcel(data, baseFilename = 'export') {
        if (!Array.isArray(data) || data.length === 0) {
            window.showToast && window.showToast('No data available to export.', 'warning');
            return;
        }

        const headers = Object.keys(data[0]);
        if (headers.length === 0) {
            window.showToast && window.showToast('Export failed: no columns detected.', 'error');
            return;
        }

        const escapeCell = (value) => {
            if (value === null || value === undefined) {
                return '""';
            }
            const stringValue = String(value).replace(/"/g, '""');
            return `"${stringValue}"`;
        };

        const csvRows = [headers.map(escapeCell).join(',')];

        data.forEach((row) => {
            const rowValues = headers.map((header) => escapeCell(row[header] ?? ''));
            csvRows.push(rowValues.join(','));
        });

        const csvContent = '\ufeff' + csvRows.join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);

        const timestamp = new Date().toISOString().split('T')[0];
        const filename = `${baseFilename}_${timestamp}.csv`;

        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        URL.revokeObjectURL(url);
    }

    /**
     * Legacy printPage function for backwards compatibility.
     * Now simply calls window.print() for basic printing needs.
     * For archival PDFs, use server-side PDF export routes.
     */
    function printPage() {
        window.print();
    }

    /**
     * Format date for display
     * @param {string|Date} date - Date to format
     * @param {boolean} includeTime - Whether to include time
     * @returns {string} Formatted date string
     */
    function formatDate(date, includeTime = true) {
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) {
            return 'Invalid Date';
        }

        const options = {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        };

        if (includeTime) {
            options.hour = '2-digit';
            options.minute = '2-digit';
            options.second = '2-digit';
        }

        return d.toLocaleString('en-US', options);
    }

    /**
     * Debounce function to limit how often a function is called
     * @param {Function} func - Function to debounce
     * @param {number} wait - Wait time in milliseconds
     * @returns {Function} Debounced function
     */
    function debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * Escape HTML special characters to prevent XSS.
     *
     * This is THE canonical implementation for the whole application — do not
     * define a local copy in a template or another module. It is published as
     * `window.escapeHtml` (as well as `EASUtils.escapeHtml`) precisely so that
     * inline template scripts can call it directly.
     *
     * All five characters are escaped, including both quote styles. That
     * matters: the previous implementation built a detached <div>, assigned
     * textContent and read back innerHTML, which escapes `&`, `<` and `>` but
     * leaves `"` and `'` untouched. That is safe for text nodes but NOT for
     * attribute values, and this helper is routinely interpolated into
     * attributes, e.g.
     *
     *     onclick="editProfile('${escapeHtml(name)}')"
     *     placeholder="${escapeHtml(fieldDef.placeholder)}"
     *
     * where an unescaped quote closes the attribute early.
     *
     * @param {*} value - Value to escape; null/undefined become ''
     * @returns {string} Escaped text, safe in both text and quoted-attribute contexts
     */
    var HTML_ESCAPES = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };

    function escapeHtml(value) {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value).replace(/[&<>"']/g, function (ch) {
            return HTML_ESCAPES[ch];
        });
    }

    /**
     * Safely set HTML content by escaping user-provided text
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} content - Content to set (will be escaped)
     */
    function setSafeText(element, content) {
        const el = typeof element === 'string' ? document.querySelector(element) : element;
        if (el) {
            el.textContent = content;
        }
    }

    /**
     * Safely append HTML by creating elements programmatically
     * @param {HTMLElement} parent - Parent element
     * @param {string} tag - HTML tag name
     * @param {Object} attributes - Attributes to set
     * @param {string} text - Text content (will be escaped)
     * @returns {HTMLElement} Created element
     */
    function createSafeElement(parent, tag, attributes = {}, text = '') {
        const el = document.createElement(tag);

        // Set attributes safely
        Object.keys(attributes).forEach(key => {
            if (key === 'className') {
                el.className = attributes[key];
            } else if (key.startsWith('data-')) {
                el.setAttribute(key, attributes[key]);
            } else {
                el[key] = attributes[key];
            }
        });

        // Set text content (automatically escaped)
        if (text) {
            el.textContent = text;
        }

        if (parent) {
            parent.appendChild(el);
        }

        return el;
    }

    /**
     * Keep dropdown menus opened inside a card from being clipped.
     *
     * `.card` in styles.css sets `overflow: hidden`, which slices any dropdown
     * menu that extends past the card's edge. The CSS fix keys off
     * `.card:has(.dropdown-menu.show)`; this mirrors it with an explicit class
     * so browsers without `:has()` support behave the same. Bootstrap fires
     * show/hide on the toggle button, so walk up to the owning card.
     */
    function trackOpenDropdowns() {
        document.addEventListener('show.bs.dropdown', function (event) {
            const card = event.target.closest('.card');
            // Bootstrap adds `.show` to the menu *after* this event, so there
            // is nothing to count yet — just mark the card.
            if (card) {
                card.classList.add('has-open-dropdown');
            }
        });

        document.addEventListener('hidden.bs.dropdown', function (event) {
            const card = event.target.closest('.card');
            if (!card) {
                return;
            }
            // A card can hold several dropdowns (the Received Alerts filter
            // panel holds two), and clicking straight from one to the next
            // gives no guaranteed ordering between this event and the other
            // menu's show. Re-read the card instead of assuming.
            card.classList.toggle(
                'has-open-dropdown',
                card.querySelector('.dropdown-menu.show') !== null
            );
        });
    }

    /**
     * Initialize utility functions
     */
    function init() {
        // Update time immediately and then every second
        updateCurrentTime();
        setInterval(updateCurrentTime, 1000);

        trackOpenDropdowns();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export functions to window
    window.exportToExcel = exportToExcel;
    window.printPage = printPage;
    // Published as a bare global on purpose. It was previously reachable only
    // as EASUtils.escapeHtml, which is why 22 templates each grew their own
    // local copy — 16 behaviourally different implementations between them.
    window.escapeHtml = escapeHtml;
    window.EASUtils = {
        updateCurrentTime: updateCurrentTime,
        exportToExcel: exportToExcel,
        printPage: printPage,
        formatDate: formatDate,
        debounce: debounce,
        escapeHtml: escapeHtml,
        setSafeText: setSafeText,
        createSafeElement: createSafeElement
    };
})();
